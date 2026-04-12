import csv
import json
import threading
import os
import platform
import base64
from pathlib import Path
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from nicegui import app, ui
from string import Template

import label_helper as h
import print_it

log = h.log
config = {}

FONT_EXTENSIONS = {'.ttf', '.otf'}
STATS_FILE = Path('print_stats.csv')
STATS_FIELDS = [
    'printed_total',
    'printed_cats',
    'printed_dogs',
    'printed_uploaded_images',
    'printed_webcam_images',
    'printed_without_image',
]
STATS_LOCK = threading.Lock()


def load_config() -> None:
    global config
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    app.colors(
        primary=config['colours']['primary'],
        secondary=config['colours']['secondary'],
        brand=config['colours']['brand'],
        accent=config['colours']['accent'],
        dark_pages=config['colours']['dark_pages'],
        positive=config['colours']['positive'],
        negative=config['colours']['negative'],
        info=config['colours']['info'],
        warning=config['colours']['warning'],
    )
    log.info('Configuration loaded.')


def write_config() -> None:
    log.debug('Saving configuration to config.json...')
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)


def list_fonts(font_dir: Path = Path('fonts'), use_system_fonts: bool = False) -> list[tuple[str, str]]:
    log.debug(f'Listing fonts from {font_dir} with use_system_fonts={use_system_fonts}...')
    fonts: list[tuple[str, str]] = {}

    # Load from custom directory
    if font_dir.exists():
        for entry in sorted(font_dir.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and entry.suffix.lower() in FONT_EXTENSIONS:
                fonts[entry.stem] = str(entry)

    # Optionally load system fonts
    if use_system_fonts:
        system_font_dirs = []
        system = platform.system()

        if system == 'Darwin':  # macOS
            system_font_dirs = [
                Path('/Library/Fonts'),
                Path(os.path.expanduser('~/Library/Fonts')),
            ]
        elif system == 'Linux':
            system_font_dirs = [
                Path('/usr/share/fonts'),
                Path(os.path.expanduser('~/.fonts')),
            ]
        elif system == 'Windows':
            system_font_dirs = [
                Path('C:/Windows/Fonts'),
            ]

        for font_dir_sys in system_font_dirs:
            if font_dir_sys.exists():
                for entry in sorted(font_dir_sys.rglob('*'), key=lambda p: p.name.lower()):
                    if entry.is_file() and entry.suffix.lower() in FONT_EXTENSIONS:
                        # Use font file name as key to avoid duplicates
                        # Prefer custom fonts over system fonts if there's a conflict
                        if entry.stem not in fonts:
                            fonts[entry.stem] = str(entry)
    log.info(f'Found {len(fonts)} fonts: {list(fonts.keys())}')
    return list(fonts.items())

def render_preview(state: dict, fonts_by_name: dict[str, str]) -> Image.Image:
    log.debug('Rendering preview image with current state...')
    printer = config['printers'][state['selected_printer']]
    label = printer['label']
    dpi = printer.get('dpi', 300)
    width_mm = label['width']
    length_mm = label.get('length', 0)

    source_image = state['image'] if state['image'] is not None else h.clear_image(
    )
    offset_mm = (
        state['img_offset_x'] * 25.4 / dpi,
        state['img_offset_y'] * 25.4 / dpi,
    )

    resized = h.resize_image(
        source_image,
        width=width_mm,
        height=length_mm,
        dpi=dpi,
        crop=state['crop_image'],
        offset=offset_mm,
    )

    with_text = h.draw_text_overlay(
        base_image=resized.convert('RGB'),
        state=state,
        font_path=fonts_by_name.get(state['font_name']),
    )

    if state['dither_preview']:
        return h.dither_image(
            with_text,
            black_point=state['black_point'],
            white_point=state['white_point'],
            contrast=state['contrast'],
        ).convert('RGB')
    return with_text


def reset_stats() -> None:
    log.warning('Resetting statistics...')
    with STATS_LOCK:
        init_stats_csv(overwrite=True)


def init_stats_csv(overwrite: bool = False) -> None:
    log.debug(f'Initializing stats CSV with overwrite={overwrite}...')
    if STATS_FILE.exists() and not overwrite:
        return

    with STATS_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
        writer.writeheader()
        writer.writerow({field: 0 for field in STATS_FIELDS})


def generate_fonts_preview() -> None:
    """Generate a preview image showing all available fonts."""
    fonts_dir = Path(config.get('fonts_dir', 'fonts'))
    use_system_fonts = config.get('use_system_fonts', False)
    fonts = list_fonts(font_dir=fonts_dir, use_system_fonts=use_system_fonts)

    if not fonts:
        log.warning('No fonts available for preview generation.')
        return

    # Create docs directory if it doesn't exist
    docs_dir = Path('docs')
    docs_dir.mkdir(exist_ok=True)

    # Image settings
    font_size = 30
    line_height = font_size + 10
    left_margin = 20
    top_margin = 20
    content_width = 1000

    # Calculate total height
    total_height = top_margin + (len(fonts) * line_height) + top_margin

    # Create image
    preview_image = Image.new(
        'RGB', (content_width + 2 * left_margin, total_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(preview_image)

    # Draw each font
    y_pos = top_margin
    for font_name, font_path in sorted(fonts):
        try:
            font = ImageFont.truetype(font_path, size=font_size)
        except OSError:
            log.warning(f'Could not load font {font_name} from {font_path}')
            font = ImageFont.load_default()

        # Draw font name and sample text
        sample_text = f"{font_name}: The quick brown fox jumps over the lazy dog"
        draw.text((left_margin, y_pos), sample_text, font=font, fill=(0, 0, 0))
        y_pos += line_height

    # Save preview image
    preview_path = docs_dir / 'fonts_preview.jpg'
    preview_image.save(preview_path, quality=90)
    log.info(f'Fonts preview generated: {preview_path}')


def _read_stats() -> dict[str, int]:
    init_stats_csv()
    with STATS_FILE.open('r', newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return {field: 0 for field in STATS_FIELDS}

    row = rows[0]
    return {field: int(row.get(field, 0) or 0) for field in STATS_FIELDS}


def _write_stats(stats: dict[str, int]) -> None:
    with STATS_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
        writer.writeheader()
        writer.writerow(stats)


def load_about_markdown() -> str:
    about_path = Path('README.md')
    if not about_path.exists():
        return '# About\n\nNo README.md file found.'
    return about_path.read_text(encoding='utf-8')


def record_print(source_kind: str) -> None:
    with STATS_LOCK:
        stats = _read_stats()
        stats['printed_total'] += 1

        if source_kind == 'cat':
            stats['printed_cats'] += 1
        elif source_kind == 'dog':
            stats['printed_dogs'] += 1
        elif source_kind == 'upload':
            stats['printed_uploaded_images'] += 1
        elif source_kind == 'webcam':
            stats['printed_webcam_images'] += 1
        else:
            stats['printed_without_image'] += 1

        _write_stats(stats)


def get_printer_labels() -> dict[int, str]:
    labels: dict[int, str] = {}
    for idx, printer in enumerate(config['printers']):
        label = printer['label']
        labels[idx] = (
            f"{printer['name']} - {printer['serial'][-4:]} - "
            f"{label['width']}x{label['length']}"
        )
    return labels


@ui.page('/')
def homepage() -> None:
    fonts_dir = Path(config.get('fonts_dir', 'fonts'))
    use_system_fonts = config.get('use_system_fonts', False)
    fonts = list_fonts(font_dir=fonts_dir, use_system_fonts=use_system_fonts)
    fonts_by_name = {name: path for name, path in fonts}
    font_names = list(fonts_by_name.keys())

    printer_options = get_printer_labels()
    default_printer = next(iter(printer_options), 0)

    state = {
        'selected_printer': default_printer,
        'image': None,
        'original_image': None,
        'image_source_kind': 'none',
        'crop_image': False,
        'dither_preview': False,
        'img_offset_x': 0,
        'img_offset_y': 0,
        'text': '',
        'font_name': font_names[0] if font_names else '',
        'text_size': 36,
        'h_align': 'Center',
        'v_align': 'Center',
        'text_offset_x': 0,
        'text_offset_y': 0,
        'rotate_text': 0,
        'rotate_image_angle': 0,
        'black_text': True,
        'outline': False,
        'black_point': 5,
        'white_point': 250,
        'contrast': 1.0,
    }

    webcam_video_id = f'webcam-video-{id(state)}'
    webcam_canvas_id = f'webcam-canvas-{id(state)}'

    async def stop_webcam_stream() -> None:
        await ui.run_javascript(f'''
            (() => {{
                const video = document.getElementById('{webcam_video_id}');
                if (!video || !video.srcObject) return false;
                const stream = video.srcObject;
                stream.getTracks().forEach(track => track.stop());
                video.srcObject = null;
                return true;
            }})()
        ''')

    async def open_webcam_dialog() -> None:
        webcam_dialog.open()
        result = await ui.run_javascript(f'''
            (async () => {{
                const video = document.getElementById('{webcam_video_id}');
                if (!video) return 'missing-video';
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'unsupported';
                try {{
                    const stream = await navigator.mediaDevices.getUserMedia({{ video: true }});
                    video.srcObject = stream;
                    await video.play();
                    return 'ok';
                }} catch (error) {{
                    const reason = error?.message || error?.name || 'unknown';
                    return `error:${{reason}}`;
                }}
            }})()
        ''')

        if result == 'ok':
            return

        await stop_webcam_stream()
        webcam_dialog.close()
        if result == 'unsupported':
            ui.notify(
                'Browser webcam API is not supported on this device.', type='negative')
        else:
            ui.notify(
                'Could not access webcam. Please allow camera permission.', type='negative')

    async def close_webcam_dialog() -> None:
        await stop_webcam_stream()
        webcam_dialog.close()

    async def capture_webcam_image() -> None:
        data_url = await ui.run_javascript(f'''
            (() => {{
                const video = document.getElementById('{webcam_video_id}');
                const canvas = document.getElementById('{webcam_canvas_id}');
                if (!video || !canvas) return '';
                if (!video.videoWidth || !video.videoHeight) return '';

                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                return canvas.toDataURL('image/png');
            }})()
        ''')

        if not data_url:
            ui.notify(
                'No webcam frame available yet. Try again in a moment.', type='warning')
            return

        payload = data_url.split(',', 1)[1] if ',' in data_url else data_url
        with Image.open(BytesIO(base64.b64decode(payload))) as captured:
            captured_rgb = captured.convert('RGB')

        state['original_image'] = captured_rgb.copy()
        state['image'] = captured_rgb
        state['rotate_image_angle'] = 0
        state['image_source_kind'] = 'webcam'
        await close_webcam_dialog()
        refresh_preview()

    webcam_dialog = ui.dialog().props('persistent')
    with webcam_dialog, ui.card().classes('w-full max-w-2xl'):
        ui.label('Take a photo').classes('text-xl font-bold text-secondary')
        ui.html(
            f'<video id="{webcam_video_id}" autoplay playsinline muted style="width:100%; max-height:70vh; border-radius: 8px; background: #000;"></video>'
        )
        ui.html(
            f'<canvas id="{webcam_canvas_id}" style="display:none"></canvas>')
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=close_webcam_dialog).props('outline')
            ui.button('Capture', on_click=capture_webcam_image).classes(
                'bg-brand text-white')

    async def upload_handler(e) -> None:
        log.debug('[magenta]Upload[/magenta] clicked... loading uploaded image')
        try:
            uploaded = await h.uploaded_file_to_image(e)
            state['original_image'] = uploaded.copy()
            state['image'] = uploaded
            state['rotate_image_angle'] = 0
            state['image_source_kind'] = 'upload'
            refresh_preview()
        except Exception as exc:
            log.error(f'Could not process uploaded file: {exc}')
            ui.notify(
                'Upload failed. Please provide an image or a valid PDF file.', type='negative')

    ui.dark_mode(config.get('dark_mode', True))

    css_template = Template('''
        p {
            font-size: 1.1rem;
        }

        p a {
            color: $secondary_color;
        }


        h2 {
            font-size: 2.25rem;
            font-weight: 700;
            color: $brand_color;
        }
                            
        h3 {
            font-size: 1.5rem;
            font-weight: 500;
            color: $brand_color;
        }

        h4 {
            font-size: 1.25rem;
            font-weight: 500;
            color: $brand_color;
        }
        
        em, strong {
            color: color-mix(in srgb, $brand_color 100%, #fff 80%);
            font-style: normal;
        }
                                   
        code {
            background-color: color-mix(in srgb, $brand_color 40%, #000 80%);
            padding: 2px 4px;
        }
                            
        pre {
            background-color: color-mix(in srgb, $brand_color 40%, #000 80%);
            padding: 12px;
            border-radius: 6px;
            }

        @media (max-width: 1023px) {
            .mobile-stack {
                grid-template-columns: 1fr !important;
            }
        }
    ''')

    ui.add_css(css_template.substitute(brand_color=config['colours']['brand'], secondary_color=config['colours']
               ['secondary'], accent=config['colours']['accent'], primary_color=config['colours']['primary']))

    with ui.card().tight().classes('w-full lg:w-2/3 mx-auto'):
        with ui.card_section().classes('w-full'):
            ui.label(config['name']).classes('text-3xl lg:text-5xl font-bold').classes('text-center text-brand')
            ui.label(config['subtitle']).classes('text-lg lg:text-2xl').classes('text-center text-secondary')

        with ui.card_section().classes('w-full'):
            with ui.tabs() as tabs:
                ui.tab('h', label='Label')
                ui.tab('f', label="Available Fonts")
                ui.tab('a', label='About')

            with ui.tab_panels(tabs, value='h').classes('w-full'):
                with ui.tab_panel('h'):
                    ui.label('Oi, print some stickaz. By ‘da way red iz fasta.').classes('w-full text-secondary text-lg lg:text-2xl font-bold')
                    with ui.card_section().classes('w-full'):
                        with ui.grid(columns='2fr 1fr 1fr').classes('w-full gap-4 mobile-stack'):
                            ui.select(options=printer_options,value=default_printer,label='Select a printer',on_change=lambda e: update_state(selected_printer=e.value)).classes('w-full')
                            ui.button('Download').classes('bg-secondary text-2xl font-bold').on('click', lambda e: stikka_handler(e, download=True))
                            ui.button('Print').classes('bg-brand text-2xl font-bold').on('click', lambda e: stikka_handler(e, download=False))
                        ui.separator().classes('my-4')

                    with ui.card_section().classes('w-full'):
                        with ui.grid(columns='1fr 3fr').classes('w-full gap-4 mobile-stack'):
                            with ui.card().tight():
                                preview = ui.interactive_image().classes( 'w-full max-h-[50vh] lg:max-h-[72vh] bg-white')

                            with ui.card():
                                ui.label('Image').classes('w-full text-secondary text-2xl font-bold')
                                with ui.grid(columns=3).classes('w-full gap-4 mobile-stack'):
                                    ui.button('Get Cat').classes( 'w-full').on('click', lambda e: get_cat_handler())
                                    ui.button('Get Dog').classes( 'w-full').on('click', lambda e: get_dog_handler())
                                    ui.button('Webcam').classes( 'w-full').on('click', open_webcam_dialog)

                                    ui.select([0, 90, 180, 270],label='Rotate Image',value=0,on_change=lambda e: rotate_image_handler(int(e.value)),).classes('w-full')
                                    with ui.grid(columns=2).classes('w-full gap-2 mobile-stack'):
                                        ui.switch('Crop Image',value=False,on_change=lambda e: update_state( crop_image=bool(e.value))).classes('w-full')
                                        ui.switch('Dither Preview',value=False,on_change=lambda e: update_state( dither_preview=bool(e.value))).classes('w-full')
                                    ui.button('Clear').classes('w-full').on('click', lambda e: clear_handler())

                                    with ui.card():
                                        with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                            ui.label('X-offset')
                                            x_offset_img = ui.slider(min=-200, max=200,value=0,on_change=lambda e: update_state( img_offset_x=int(e.value)))
                                            ui.label().bind_text_from(x_offset_img, 'value')
                                            ui.label('Pixel')
                                    with ui.card():
                                        with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                            ui.label('Y-offset')
                                            y_offset_img = ui.slider(min=-200, max=200,value=0,on_change=lambda e: update_state( img_offset_y=int(e.value)))
                                            ui.label().bind_text_from(y_offset_img, 'value')
                                            ui.label('Pixel')
                                    ui.space()

                                    with ui.card():
                                        with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                            ui.label('Black')
                                            black_point_img = ui.slider(min=0, max=255, value=5, on_change=lambda e: update_state(black_point=int(e.value)))
                                            ui.label().bind_text_from(black_point_img, 'value')
                                            ui.space()
                                    with ui.card():
                                        with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                            ui.label('White')
                                            white_point_img = ui.slider(min=0, max=255, value=250, on_change=lambda e: update_state(white_point=int(e.value)))
                                            ui.label().bind_text_from(white_point_img, 'value')
                                            ui.space()
                                    with ui.card():
                                        with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                            ui.label('Contrast')
                                            contrast_img = ui.slider( min=0.3, max=3.0, value=1.0, step=0.1, on_change=lambda e: update_state(contrast=float(e.value)))
                                            ui.label().bind_text_from(contrast_img, 'value')
                                            ui.space()

                            with ui.card().tight():
                                ui.upload(on_upload=upload_handler).props('accept=image/*,.pdf,application/pdf auto-upload').classes('w-full')

                            with ui.card():
                                ui.label('Text').classes('w-full text-secondary text-lg lg:text-2xl font-bold')
                                with ui.grid(columns='1fr 2fr').classes('w-full gap-4 mobile-stack'):
                                    ui.textarea(label='Text',placeholder='start typing',on_change=lambda e: update_state(text=e.value or ''),).classes('h-full')
                                    with ui.grid(columns=2).classes('w-full gap-4 mobile-stack'):
                                        ui.select(font_names,value=state['font_name'],label='Select font',on_change=lambda e: update_state(font_name=e.value or ''))
                                        with ui.card():
                                            with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                                ui.label('Size')
                                                size_text = ui.slider(min=8,max=180,value=state['text_size'],on_change=lambda e: update_state(text_size=int(e.value)))
                                                ui.label().bind_text_from(size_text, 'value')
                                                ui.space()

                                        ui.select(['Left', 'Center', 'Right'],value='Center',label='Horizontal Alignment',on_change=lambda e: update_state(h_align=e.value or 'Center')).classes('w-full')
                                        ui.select(['Top', 'Center', 'Bottom'],value='Center',label='Vertical Alignment',on_change=lambda e: update_state(v_align=e.value or 'Center')).classes('w-full')

                                        with ui.card():
                                            with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                                ui.label('X-offset')
                                                x_offset_text = ui.slider(min=-200,max=200,value=0,on_change=lambda e: update_state(text_offset_x=int(e.value)))
                                                ui.label().bind_text_from(x_offset_text, 'value')
                                                ui.label('Pixel')
                                        with ui.card():
                                            with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                                ui.label('Y-offset')
                                                y_offset_text = ui.slider(min=-200,max=200,value=0,on_change=lambda e: update_state(text_offset_y=int(e.value)))
                                                ui.label().bind_text_from(y_offset_text, 'value')
                                                ui.label('Pixel')

                                        ui.select([0, 90, 180, 270],value=0,label='Rotate Text',on_change=lambda e: update_state(rotate_text=int(e.value))).classes('w-full')

                                        with ui.grid(columns=2).classes('w-full gap-2 mobile-stack'):
                                            ui.switch('Black Text',value=True,on_change=lambda e: update_state(black_text=bool(e.value)))
                                            ui.switch('Outline', value=False,on_change=lambda e: update_state(outline=bool(e.value)))

                with ui.tab_panel('f'):
                    ui.label("Available Fonts ").classes('w-full text-secondary text-2xl font-bold')
                    ui.image("docs/fonts_preview.jpg")
                with ui.tab_panel('a'):
                    current_stats = _read_stats()
                    ui.label('Statistics').classes('w-full text-secondary text-2xl font-bold')
                    with ui.grid(columns=2).classes('w-full gap-4 mobile-stack text-lg'):
                        ui.label('Total Stikkas printed').classes('font-bold')
                        ui.label(str(current_stats['printed_total'])).classes('font-bold')
                        ui.label('Cat stikkas printed').classes('text-accent')
                        ui.label(str(current_stats['printed_cats'])).classes('text-accent')
                        ui.label('Dog stikkas printed')
                        ui.label(str(current_stats['printed_dogs']))
                        ui.label('Uploaded image stikkas printed').classes('text-accent')
                        ui.label(str(current_stats['printed_uploaded_images'])).classes('text-accent')
                        ui.label('Webcam image stikkas printed')
                        ui.label(str(current_stats['printed_webcam_images']))
                        ui.label('Stikkas without image printed').classes('text-accent')
                        ui.label(str(current_stats['printed_without_image'])).classes('text-accent')

                    ui.separator().classes('my-4')
                    ui.label('About').classes('w-full text-secondary text-2xl font-bold')
                    ui.markdown(load_about_markdown()).classes('w-full')

    def refresh_preview() -> None:
        rendered = render_preview(state=state, fonts_by_name=fonts_by_name)
        preview.set_source(h.pil_to_data_url(rendered))

    def update_state(**kwargs) -> None:
        state.update(kwargs)
        refresh_preview()

    def get_cat_handler() -> None:
        log.debug('[magenta]Get Cat[/magenta] clicked... getting cat image from cat API')
        cat_image = h.get_cat().convert('RGB')
        state['original_image'] = cat_image.copy()
        state['image'] = cat_image
        state['rotate_image_angle'] = 0
        state['image_source_kind'] = 'cat'
        refresh_preview()

    def get_dog_handler() -> None:
        log.debug('[magenta]Get Dog[/magenta] clicked... getting dog image from dog API')
        dog_image = h.get_dog().convert('RGB')
        state['original_image'] = dog_image.copy()
        state['image'] = dog_image
        state['rotate_image_angle'] = 0
        state['image_source_kind'] = 'dog'
        refresh_preview()

    def clear_handler() -> None:
        log.debug('[magenta]Clear clicked[/magenta] ... reset to blank image')
        state['image'] = None
        state['original_image'] = None
        state['rotate_image_angle'] = 0
        state['image_source_kind'] = 'none'
        refresh_preview()

    def rotate_image_handler(angle: int) -> None:
        if state['original_image'] is None:
            return
        log.debug('[magenta]Rotate Image[/magenta] clicked... rotating image to absolute angle: {angle}°')
        state['rotate_image_angle'] = angle
        # Rotate from the original image to the target angle (absolute rotation)
        state['image'] = h.rotate_image(state['original_image'], angle)
        refresh_preview()

    def stikka_handler(e, download=False) -> None:
        log.info('[magenta]Stikka[/magenta] clicked... printing out sticker on selected printer')
        printer_type = config['printers'][state['selected_printer']]['type']
        log.debug(f'Selected printer type: {printer_type}')
        log.info(f'Rendering final image for printing...')
        img = render_preview(state=state, fonts_by_name=fonts_by_name)

        output_dir = Path(config.get('output_dir', 'output'))
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if printer_type == "file":
            ui.download.content(h.pil_to_bytes(img, fmt='PNG'),filename=f'sticka_{timestamp}.png',media_type='image/png')
        elif printer_type == "zpl":
            printer = config['printers'][state['selected_printer']]
            dpi = printer.get('dpi', 300)
            label_width_mm = printer['label'].get('width', 80)
            label_length_mm = printer['label'].get('length', 80)
            vertical_offset_mm = printer['label'].get('vertical_offset', 0)
            log.debug(f'{printer["name"]} DPI: {dpi}, Label size: {label_width_mm}mm x {label_length_mm}mm, Vertical offset: {vertical_offset_mm}mm')
            zpl = print_it.img_to_zpl(img, dpi=dpi, label_width_mm=label_width_mm,label_length_mm=label_length_mm, vertical_offset_mm=vertical_offset_mm)
            if download:
                ui.download.content(zpl.encode('utf-8'), filename=f'sticka_{timestamp}.zpl')
            else:
                host, port = printer.get('connection', {}).split(':')
                print_it.print_zpl(zpl, host=host, port=int(port))
                record_print(state['image_source_kind'])
                ui.notify( f"Print recorded: {state['image_source_kind']}", type='positive')

        elif printer_type == "brother_ql":
            if download:
                ui.download.content(h.pil_to_bytes(img, fmt='PNG'),filename=f'sticka_{timestamp}.png',media_type='image/png')
            else:
                printer = config['printers'][state['selected_printer']]
                dpi = printer.get('dpi', 300)
                label_width_mm = printer['label'].get('width', 80)
                label_length_mm = printer['label'].get('length', 80)
                # Extract model name (e.g., QL-800) from printer name
                model = printer.get('name', '').split()[-1]
                if not model:
                    log.error(f'Printer model not specified for Brother QL printer: {printer["name"]}')
                    ui.notify('Printer model not configured for Brother QL printer.', type='negative')
                    return
                log.debug(f'Printing to Brother QL printer: {printer["name"]} with model {model} at {dpi} DPI')
                print_it.print_ql(img, identfier=printer['connection'], backend_name=printer.get('backend_name', 'pyusb'), model=model, dpi=dpi, label_width_mm=label_width_mm, label_length_mm=label_length_mm)
                record_print(state['image_source_kind'])
                ui.notify(f"Print recorded: {state['image_source_kind']}", type='positive')
        else:
            log.error(f'Unsupported printer type: {printer_type}')
            ui.notify('Selected printer has an unsupported type.',type='negative')
    refresh_preview()


@ui.page('/config')
def config_page() -> None:
    ui.dark_mode(config.get('dark_mode', True))
    expected_password = str(config.get('config_pwd', ''))

    access_state = {'granted': expected_password == ''}

    def set_access(granted: bool) -> None:
        access_state['granted'] = granted
        auth_section.set_visibility(not granted)
        editor_section.set_visibility(granted)

    def unlock_config() -> None:
        if access_state['granted']:
            return
        entered = password_input.value or ''
        if entered == expected_password:
            password_input.set_value('')
            set_access(True)
            ui.notify('Config unlocked.', type='positive')
        else:
            password_input.set_value('')
            ui.notify('Wrong password.', type='negative')

    with ui.card().tight().classes('w-full lg:w-2/3 mx-auto'):
        with ui.card_section().classes('w-full'):
            ui.label(config['name'] + ' Configuration').classes('text-4xl md:text-5xl font-bold text-center text-brand')
            ui.label('With great power comes great responsibility').classes('text-xl md:text-2xl text-center text-secondary')

        auth_section = ui.card_section().classes('w-full')
        with auth_section:
            ui.label('Enter config password').classes('text-lg font-bold text-secondary')
            with ui.row().classes('w-full gap-2 items-end'):
                password_input = ui.input('Password').props('type=password clearable').classes('w-full')
                ui.button('Unlock', on_click=unlock_config).classes('bg-brand text-white')
            password_input.on('keydown.enter', lambda e: unlock_config())

        editor_section = ui.card_section().classes('w-full')
        with editor_section:
            editor = ui.json_editor({'content': {'json': config}}, on_change=lambda e: config.update(e.content['json']))
            editor.classes('h-240 w-full')

            with ui.grid(columns=3).classes('w-full mt-4 gap-4 sm:grid-cols-2'):
                ui.button('Save', on_click=write_config).classes('w-full')
                ui.button('Reload', on_click=load_config).classes('w-full')
                ui.button('Reset Stats', on_click=reset_stats).classes('w-full')

    set_access(access_state['granted'])


if __name__ in {'__main__', '__mp_main__'}:
    load_config()
    init_stats_csv()
    generate_fonts_preview()

    app.title = config['name']

    host = config.get('host', '0.0.0.0')
    port = int(config.get('port', 8080))
    ui.run(port=port, host=host)
