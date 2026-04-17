"""
stikka_webui.py
===============
NiceGUI page definitions and application-level helpers for Stikka-NG.

Covers:
- Application configuration loading / persistence
- Print statistics (CSV read/write)
- Printer selection helpers
- Homepage route (``/``)
- Configuration page route (``/config``)

All image and label logic is delegated to :mod:`stikka_label_helper`.
All printing logic is delegated to :mod:`stikka_print_it`.
All UI event handlers live in :class:`stikka_webui_handler.HomepageHandlers`.
"""

from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from string import Template

from nicegui import app, ui

import stikka_label_helper as lh
import stikka_print_it as pi
from stikka_webui_handler import HomepageHandlers

log = lh.log

# ---------------------------------------------------------------------------
# Global application state
# ---------------------------------------------------------------------------

config: dict = {}
"""Live application configuration dict. Updated by :func:`load_config`."""

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

# ---------------------------------------------------------------------------
# Configuration management
# ---------------------------------------------------------------------------


def load_config() -> None:
    """Load ``config.json`` into the global :data:`config` dict.

    Also updates NiceGUI's colour theme from the ``colours`` section.
    """
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
    """Persist the current in-memory :data:`config` dict to ``config.json``."""
    log.debug('Saving configuration to config.json...')
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def init_stats_csv(overwrite: bool = False) -> None:
    """Initialise the print-statistics CSV file if it does not yet exist.

    Args:
        overwrite: If ``True``, replace any existing file with a blank one.
    """
    log.debug(f'Initialising stats CSV (overwrite={overwrite})...')
    if STATS_FILE.exists() and not overwrite:
        return
    with STATS_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
        writer.writeheader()
        writer.writerow({field: 0 for field in STATS_FIELDS})


def _read_stats() -> dict[str, int]:
    """Read the first row of the statistics CSV.

    Returns:
        Dict mapping each field name to its integer value.
    """
    init_stats_csv()
    with STATS_FILE.open('r', newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {field: 0 for field in STATS_FIELDS}
    row = rows[0]
    return {field: int(row.get(field, 0) or 0) for field in STATS_FIELDS}


def _write_stats(stats: dict[str, int]) -> None:
    """Overwrite the statistics CSV with a single data row.

    Args:
        stats: Dict mapping field names to integer counts.
    """
    with STATS_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
        writer.writeheader()
        writer.writerow(stats)


def record_print(source_kind: str) -> None:
    """Increment print counters in the statistics CSV (thread-safe).

    Args:
        source_kind: One of ``'cat'``, ``'dog'``, ``'upload'``, ``'webcam'``,
            or any other string (counted under ``'printed_without_image'``).
    """
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


def reset_stats() -> None:
    """Reset all print statistics to zero (thread-safe)."""
    log.warning('Resetting statistics...')
    with STATS_LOCK:
        init_stats_csv(overwrite=True)


# ---------------------------------------------------------------------------
# Printer helpers
# ---------------------------------------------------------------------------

def get_printer_labels() -> dict[int, str]:
    """Build a display-label dict for every printer in the config.

    Returns:
        Mapping of printer index → human-readable label string.
    """
    labels: dict[int, str] = {}
    for idx, printer in enumerate(config['printers']):
        label = printer['label']
        labels[idx] = (
            f"{printer['name']} – {printer['serial'][-4:]} – "
            f"{label['width']}×{label.get('length', 0)}"
        )
    return labels


def get_zpl_printer_labels() -> dict[int, str]:
    """Build a display-label dict for ZPL-type printers only.
    Used in the Raw ZPL tab, where only ZPL printers are relevant.

    Returns:
        Mapping of global printer index → human-readable label string.
    """
    labels: dict[int, str] = {}
    for idx, printer in enumerate(config['printers']):
        if printer.get('type') == 'zpl':
            label = printer['label']
            labels[idx] = (
                f"{printer['name']} – {printer['serial'][-4:]} – "
                f"{label['width']}×{label.get('length', 0)}"
            )
    return labels


def get_first_zpl_printer_index() -> int:
    """Return the index of the last ZPL printer (typically the production unit).

    Returns:
        Global printer index, or 0 if no ZPL printers are configured.
    """
    zpl_printers = get_zpl_printer_labels()
    return max(zpl_printers.keys()) if zpl_printers else 0


def load_about_markdown() -> str:
    """Read ``README.md`` and return its contents as a string.

    Returns:
        Markdown text of the README, or a fallback message if not found.
    """
    about_path = Path('README.md')
    if not about_path.exists():
        return '# About\n\nNo README.md file found.'
    return about_path.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# Homepage – main label-printing UI
# ---------------------------------------------------------------------------

@ui.page('/')
def homepage() -> None:
    """Render the main label-printing homepage.

    Builds the full NiceGUI layout and wires up all event handlers via
    :class:`stikka_webui_handler.HomepageHandlers`.
    """
    fonts_dir = Path(config.get('fonts_dir', 'fonts'))
    use_system_fonts = config.get('use_system_fonts', False)
    fonts = lh.list_fonts(font_dir=fonts_dir, use_system_fonts=use_system_fonts)
    fonts_by_name = {name: path for name, path in fonts}
    font_names = list(fonts_by_name.keys())

    printer_options = get_printer_labels()
    default_printer = next(iter(printer_options), 0)

    zpl_printer_options = get_zpl_printer_labels()
    zpl_default_printer = get_first_zpl_printer_index()

    state = {
        'selected_printer': default_printer,
        'image': None,
        'original_image': None,
        'image_source_kind': 'none',
        'crop_image': False,
        'dither_preview': True,
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
        'outline': True,
        'black_point': 5,
        'white_point': 250,
        'contrast': 1.0,
        'raw_zpl': config.get('zpl_example', '^XA\n^CFA,30\n^FO50,20\n^FDHello ZPL^FS\n^XZ'),
    }

    webcam_video_id = f'webcam-video-{id(state)}'
    webcam_canvas_id = f'webcam-canvas-{id(state)}'

    h = HomepageHandlers(
        state=state,
        config=config,
        fonts_by_name=fonts_by_name,
        record_print=record_print,
        webcam_video_id=webcam_video_id,
        webcam_canvas_id=webcam_canvas_id,
    )

    # ------------------------------------------------------------------
    # Webcam dialog – built first so handlers can reference it
    # ------------------------------------------------------------------
    webcam_dialog = ui.dialog().props('persistent')
    h.webcam_dialog = webcam_dialog
    with webcam_dialog, ui.card().classes('w-full max-w-2xl'):
        ui.label('Take a photo').classes('text-xl font-bold text-secondary')
        ui.html(
            f'<video id="{webcam_video_id}" autoplay playsinline muted '
            'style="width:100%; max-height:70vh; border-radius:8px; background:#000;"></video>'
        )
        ui.html(f'<canvas id="{webcam_canvas_id}" style="display:none"></canvas>')
        countdown_label = ui.label().classes('text-6xl font-bold text-center text-brand')
        countdown_label.visible = False
        h.countdown_label = countdown_label
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button('Cancel', on_click=h.close_webcam_dialog).props('outline')
            capture_button = ui.button('Capture', on_click=h.capture_webcam_image).classes('bg-brand text-white')
            h.capture_button = capture_button

    # ------------------------------------------------------------------
    # Global page setup
    # ------------------------------------------------------------------
    ui.dark_mode(config.get('dark_mode', True))

    css_template = Template('''
@font-face {
    font-family: 'FiveByFiveTami';
    src: url('/fonts/5x5-Tami.ttf') format('truetype');
    font-display: swap;
}
.title-5x5-tami { font-family: 'FiveByFiveTami', sans-serif; }
p a { color: $brand_color; }
h2 { font-size: 2.25rem; font-weight: 700; color: $secondary_color; }
h3 { font-size: 1.5rem;  font-weight: 500; color: $secondary_color; }
h4 { font-size: 1.25rem; font-weight: 500; color: $secondary_color; }
em, strong {
    color: color-mix(in srgb, $secondary_color 100%, #fff 80%);
    font-style: normal;
}
code { background-color: color-mix(in srgb, $secondary_color 40%, #000 80%); }
pre  {
    background-color: color-mix(in srgb, $secondary_color 40%, #000 80%);
    padding: 20px; border-radius: 6px;
}
@media (max-width: 1100px) {
    .mobile-stack { grid-template-columns: 1fr !important; }
}
    ''')
    ui.add_css(css_template.substitute(
        brand_color=config['colours']['brand'],
        secondary_color=config['colours']['secondary'],
        accent=config['colours']['accent'],
        primary_color=config['colours']['primary'],
    ))

    # ------------------------------------------------------------------
    # Main card
    # ------------------------------------------------------------------
    with ui.card().tight().classes('w-full min-[1800px]:w-2/3 mx-auto'):
        with ui.card_section().classes('w-full'):
            ui.label(config['name']).classes(
                'text-3xl lg:text-7xl font-bold title-5x5-tami text-center text-brand'
            )
            ui.label(config['subtitle']).classes('w-full text-secondary text-lg lg:text-2xl font-bold title-5x5-tami text-center')

        with ui.card_section().classes('w-full'):
            with ui.tabs() as tabs:
                ui.tab('h', label='Label')
                if config.get('raw_zpl_enabled', True):
                    ui.tab('r', label='Raw ZPL')
                ui.tab('f', label='Available Fonts')
                ui.tab('a', label='About')

            # --- Label tab ---
            with ui.tab_panels(tabs, value='h').classes('w-full'):
                with ui.tab_panel('h'):
                    ui.label('Oi, print some stikkaz').classes(
                        'w-full text-secondary text-lg lg:text-2xl font-bold title-5x5-tami text-center'
                    )
                    with ui.card_section().classes('w-full'):
                        with ui.grid(columns='2fr 1fr 1fr').classes('w-full gap-4 mobile-stack'):
                            ui.select(
                                options=printer_options,
                                value=default_printer,
                                label='Select a printer',
                                on_change=lambda e: h.update_state(selected_printer=e.value),
                            ).classes('w-full')
                            ui.button('Download Stikka').classes('bg-accent text-2xl font-bold').on(
                                'click', lambda e: h.stikka_handler(e, download=True)
                            )
                            ui.button('Print Stikka').classes('bg-secondary text-2xl font-bold').on(
                                'click', lambda e: h.stikka_handler(e, download=False)
                            )
                        ui.separator().classes('my-4')

                    with ui.card_section().classes('w-full'):
                        with ui.grid(columns=4).classes('w-full gap-4 mobile-stack'):
                            
                            # Preview & upload column 
                            with ui.card().tight():
                                
                                preview = ui.interactive_image().classes(
                                    'w-full max-h-[50vh] lg:max-h-[72vh] bg-white'
                                )
                                h.preview = preview

                                ui.upload(on_upload=h.upload_handler).props(
                                    'accept=image/*,.pdf,application/pdf auto-upload'
                                ).classes('w-full')

                            # Image column
                            with ui.expansion() as img_expansion:
                                with img_expansion.add_slot('header'):
                                    ui.label('Image Options').classes('w-full text-brand text-2xl font-bold  title-5x5-tami')
                                img_expansion.value = True

                                ui.button('Get Cat').classes('w-full').on(
                                    'click', lambda _e: h.get_cat_handler()
                                )
                                ui.button('Get Dog').classes('w-full').on(
                                    'click', lambda _e: h.get_dog_handler()
                                )
                                ui.button('Webcam').classes('w-full').on(
                                    'click', h.open_webcam_dialog
                                )
                                ui.button('Clear').classes('w-full').on(
                                    'click', lambda _e: h.clear_handler()
                                )
                                    
                                ui.select(
                                    [0, 90, 180, 270],
                                    label='Rotate Image',
                                    value=0,
                                    on_change=lambda e: h.rotate_image_handler(int(e.value)),
                                ).classes('w-full')
        
                                with ui.grid(columns=2).classes('w-full gap-2 mobile-stack'):
                                    ui.switch(
                                        'Crop Image', value=False,
                                        on_change=lambda e: h.update_state(crop_image=bool(e.value)),
                                    ).classes('w-full')
                                    ui.switch(
                                        'Dither Preview', value=True,
                                        on_change=lambda e: h.update_state(dither_preview=bool(e.value)),
                                    ).classes('w-full')

                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('X-offset')
                                    x_offset_img = ui.slider(
                                        min=-200, max=200, value=0,
                                        on_change=lambda e: h.update_state(img_offset_x=int(e.value)),
                                    )
                                    ui.label().bind_text_from(x_offset_img, 'value')
                                    ui.label('Pixel')

                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('Y-offset')
                                    y_offset_img = ui.slider(
                                        min=-200, max=200, value=0,
                                        on_change=lambda e: h.update_state(img_offset_y=int(e.value)),
                                    )
                                    ui.label().bind_text_from(y_offset_img, 'value')
                                    ui.label('Pixel')
               
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('Black')
                                    black_pt = ui.slider(
                                        min=0, max=255, value=5,
                                        on_change=lambda e: h.update_state(black_point=int(e.value)),
                                    )
                                    ui.label().bind_text_from(black_pt, 'value')
                                    ui.space()
                                        
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('White')
                                    white_pt = ui.slider(
                                        min=0, max=255, value=250,
                                        on_change=lambda e: h.update_state(white_point=int(e.value)),
                                    )
                                    ui.label().bind_text_from(white_pt, 'value')

                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('Contrast')
                                    contrast_sl = ui.slider(
                                        min=0.3, max=3.0, value=1.0, step=0.1,
                                        on_change=lambda e: h.update_state(contrast=float(e.value)),
                                    )
                                    ui.label().bind_text_from(contrast_sl, 'value')
                                       

                            with ui.expansion() as text_expansion:
                                with text_expansion.add_slot('header'):
                                    ui.label('Text Options').classes('w-full text-brand text-2xl font-bold  title-5x5-tami')
                                text_expansion.value = True
                        
                                ui.textarea(
                                    label='Text',
                                    placeholder='start typing',
                                    on_change=lambda e: h.update_state(text=e.value or ''),
                                ).classes('h-full w-full mobile-stack')
                                ui.select(
                                    font_names,
                                    value=state['font_name'],
                                    label='Select font',
                                    on_change=lambda e: h.update_state(font_name=e.value or ''),
                                ).classes('w-full w-full mobile-stack')
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full mobile-stack'):
                                    ui.label('Size')
                                    size_sl = ui.slider(
                                        min=8, max=180, value=state['text_size'],
                                        on_change=lambda e: h.update_state(text_size=int(e.value)),
                                    )
                                    ui.label().bind_text_from(size_sl, 'value')
                                    ui.space()
                                ui.select(
                                    ['Left', 'Center', 'Right'],
                                    value='Center',
                                    label='Horizontal Alignment',
                                    on_change=lambda e: h.update_state(h_align=e.value or 'Center'),
                                ).classes('w-full mobile-stack')
                                ui.select(
                                    ['Top', 'Center', 'Bottom'],
                                    value='Center',
                                    label='Vertical Alignment',
                                    on_change=lambda e: h.update_state(v_align=e.value or 'Center'),
                                ).classes('w-full mobile-stack')
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('X-offset')
                                    x_off_txt = ui.slider(
                                        min=-200, max=200, value=0,
                                        on_change=lambda e: h.update_state(text_offset_x=int(e.value)),
                                    )
                                    ui.label().bind_text_from(x_off_txt, 'value')
                                    ui.label('Pixel')
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('Y-offset')
                                    y_off_txt = ui.slider(
                                        min=-200, max=200, value=0,
                                        on_change=lambda e: h.update_state(text_offset_y=int(e.value)),
                                    )
                                    ui.label().bind_text_from(y_off_txt, 'value')
                                    ui.label('Pixel')
                                ui.select(
                                    [0, 90, 180, 270],
                                    value=0,
                                    label='Rotate Text',
                                    on_change=lambda e: h.update_state(rotate_text=int(e.value)),
                                ).classes('w-full')
                                with ui.grid(columns=2).classes('w-full gap-2 mobile-stack'):
                                    ui.switch(
                                        'Black Text', value=True,
                                        on_change=lambda e: h.update_state(black_text=bool(e.value)),
                                    )
                                    ui.switch(
                                        'Outline', value=True,
                                        on_change=lambda e: h.update_state(outline=bool(e.value)),
                                    )

                            with ui.expansion() as bc_expansion:
                                with bc_expansion.add_slot('header'):
                                    ui.label('Barcode Options').classes('w-full text-brand text-2xl font-bold  title-5x5-tami')
                                bc_expansion.value = True

                                bc_text = ui.textarea(
                                    label='Barcode Data',
                                    placeholder='Enter text to encode as barcode',
                                    on_change=lambda e: h.update_state(barcode_data=e.value or ''),
                                ).classes('h-full w-full mobile-stack')
                                bc_type = ui.select(
                                    ['Code128', 'Code39', 'EAN13', 'EAN8', 'UPC', 'QR'],
                                    value='Code128',
                                    label='Select barcode type',
                                    on_change=lambda e: h.update_state(barcode_type=e.value or 'Code128'),
                                ).classes('w-full mobile-stack')
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('Size')
                                    size_sl = ui.slider(
                                        min=1, max=10, value=3,
                                        on_change=lambda e: h.update_state(barcode_size=int(e.value)),
                                    )
                                    ui.label().bind_text_from(size_sl, 'value')
                                    ui.space()
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('X-offset')
                                    x_off_bc = ui.slider(
                                        min=-200, max=200, value=0,
                                        on_change=lambda e: h.update_state(barcode_offset_x=int(e.value)),
                                    )
                                    ui.label().bind_text_from(x_off_bc, 'value')
                                    ui.label('Pixel')
                                with ui.grid(columns='1fr 3fr 0.5fr 0.5fr').classes('w-full gap-2 mobile-stack'):
                                    ui.label('Y-offset')
                                    y_off_bc = ui.slider(
                                        min=-200, max=200, value=0,
                                        on_change=lambda e: h.update_state(barcode_offset_y=int(e.value)),
                                    )
                                    ui.label().bind_text_from(y_off_bc, 'value')
                                    ui.label('Pixel')   
                                ui.button('Generate Barcode').classes('w-full').on(
                                    'click', lambda e: h.generate_barcode_handler(e)
                                )  

                                with ui.grid(columns=2).classes('w-full gap-2 mobile-stack'):
                                    ui.switch(
                                        'Attach at end', value=False,
                                        on_change=lambda e: h.update_state(crop_image=bool(e.value)),
                                    ).classes('w-full')
                                    ui.switch(
                                        'Show Value', value=False,
                                        on_change=lambda e: h.update_state(dither_preview=bool(e.value)),
                                    ).classes('w-full')


                # --- Raw ZPL tab (separate tab_panels to avoid value clash) ---
                with ui.tab_panel('r'):
                    ui.label('Hic sunt dracones!').classes(
                        'w-full text-warning text-lg lg:text-2xl font-bold title-5x5-tami text-center'

                    )
                    ui.markdown(
                        '''
                        This tab is for users who want to send raw ZPL commands directly to a ZPL-compatible printer.
                        
                        There are nice tools online to help you build ZPL code, such as [Labelary](https://labelary.com/viewer.html) or [ZPL Designer](https://app.zpldesigner.com/).                
                        '''
                    ).classes('w-full mb-4')


                    with ui.card_section().classes('w-full'):
                        with ui.grid(columns='2fr 1fr 1fr').classes('w-full gap-4 mobile-stack'):
                            ui.select(
                                options=zpl_printer_options,
                                value=zpl_default_printer,
                                label='Select a ZPL printer',
                                on_change=lambda e: h.update_state(selected_printer=e.value),
                            ).classes('w-full')
                            state['selected_printer'] = zpl_default_printer
                            ui.button('Preview ZPL').classes('bg-accent text-2xl font-bold').on(
                                'click', lambda e: h.preview_zpl_handler(e)
                            )
                            ui.button('Send to Printer').classes('bg-secondary text-2xl font-bold').on(
                                'click', lambda e: h.raw_zpl_handler(e)
                            )
                        ui.separator().classes('my-4')
                        with ui.grid(columns=2).classes('w-full gap-4 mobile-stack items-start'):
                            raw_zpl_area = ui.textarea(
                                label='Raw ZPL',
                                placeholder='Enter raw ZPL code here...',
                                value= state['raw_zpl'],
                                on_change=lambda e: h.update_state(raw_zpl=e.value or ''),
                            ).classes('w-full').props('input-class=h-100')
                            h.raw_zpl_area = raw_zpl_area
                            zpl_preview_img = ui.image().classes('w-full h-auto border max-h-none')
                            h.zpl_preview = zpl_preview_img


                # --- Fonts tab ---
                with ui.tab_panel('f'):
                    ui.label('Available Fonts').classes('w-full text-secondary text-lg lg:text-2xl font-bold title-5x5-tami text-center')
                    ui.image('docs/fonts_preview.jpg')

                # --- About / Stats tab ---
                with ui.tab_panel('a'):
                    current_stats = _read_stats()
                    ui.label('Statistics').classes('w-full text-secondary text-2xl font-bold title-5x5-tami text-center')
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
                    ui.label('About').classes('w-full text-secondary text-lg lg:text-2xl font-bold title-5x5-tami text-center')
                    ui.markdown(load_about_markdown()).classes('w-full')


    # Initial preview render
    h.refresh_preview()


# ---------------------------------------------------------------------------
# Configuration page
# ---------------------------------------------------------------------------

@ui.page('/config')
def config_page() -> None:
    """Render the password-protected configuration editor page.

    Provides a JSON editor for the live config, plus Save / Reload /
    Reset Stats buttons.
    """
    ui.dark_mode(config.get('dark_mode', True))
    expected_password = str(config.get('config_pwd', ''))
    access_state = {'granted': expected_password == ''}

    def set_access(granted: bool) -> None:
        """Show or hide the auth/editor sections based on *granted*."""
        access_state['granted'] = granted
        auth_section.set_visibility(not granted)
        editor_section.set_visibility(granted)

    def unlock_config() -> None:
        """Validate the entered password and grant access on match."""
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

    with ui.card().tight().classes('w-full min-[1700px]:w-2/3 mx-auto'):
        with ui.card_section().classes('w-full'):
            ui.label(config['name'] + ' Configuration').classes(
                'text-4xl md:text-5xl font-bold text-center text-brand'
            )
            ui.label('With great power comes great responsibility').classes(
                'text-xl md:text-2xl text-center text-secondary'
            )

        auth_section = ui.card_section().classes('w-full')
        with auth_section:
            ui.label('Enter config password').classes('text-lg font-bold text-secondary')
            with ui.row().classes('w-full gap-2 items-end'):
                password_input = ui.input('Password').props('type=password clearable').classes('w-full')
                ui.button('Unlock', on_click=unlock_config).classes('bg-brand text-white')
            password_input.on('keydown.enter', lambda _e: unlock_config())

        editor_section = ui.card_section().classes('w-full')
        with editor_section:
            editor = ui.json_editor(
                {'content': {'json': config}},
                on_change=lambda e: config.update(e.content['json']),
            )
            editor.classes('h-240 w-full')
            with ui.grid(columns=3).classes('w-full mt-4 gap-4 sm:grid-cols-2'):
                ui.button('Save', on_click=write_config).classes('w-full')
                ui.button('Reload', on_click=load_config).classes('w-full')
                ui.button('Reset Stats', on_click=reset_stats).classes('w-full')

    set_access(access_state['granted'])
