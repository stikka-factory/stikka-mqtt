"""Image and label creation utilities for Stikka-NG."""
from __future__ import annotations

import base64
import importlib
import inspect
import logging
import os
import platform
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler

# ---------------------------------------------------------------------------
# Logging – configured once and shared app-wide through the ``log`` reference
# ---------------------------------------------------------------------------

import json as _json

_config = _json.load(open('config.json'))

FORMAT = '%(message)s'
logging.basicConfig(
    level=getattr(logging, _config.get('debug_level', 'INFO').upper(), logging.INFO),
    format=FORMAT,
    datefmt='[%X]',
    handlers=[RichHandler(markup=True, highlighter=NullHighlighter())],
)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)

log: logging.Logger = logging.getLogger('rich')

FONT_EXTENSIONS: set[str] = {'.ttf', '.otf'}


# ---------------------------------------------------------------------------
# Image acquisition
# ---------------------------------------------------------------------------

def get_cat() -> Image.Image:
    """Fetch a random cat image from The Cat API."""
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Stikka-NG/1.0)'}
    log.debug('Fetching a cat image...')
    data = requests.get('https://api.thecatapi.com/v1/images/search', headers=headers).json()
    image_url = data[0]['url']
    img = Image.open(BytesIO(requests.get(image_url, headers=headers).content))
    log.info(f'Cat image fetched: {image_url} ({img.width}x{img.height})')
    return img


def get_dog() -> Image.Image:
    """Fetch a random dog image from the Dog CEO API."""
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Stikka-NG/1.0)'}
    log.debug('Fetching a dog image...')
    data = requests.get('https://dog.ceo/api/breeds/image/random', headers=headers).json()
    image_url = data['message']
    img = Image.open(BytesIO(requests.get(image_url, headers=headers).content))
    log.info(f'Dog image fetched: {image_url} ({img.width}x{img.height})')
    return img


def get_dino() -> Image.Image:
    """Fetch a random dinosaur image from dinosaurpictures.org."""
    import time
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; Stikka-NG/1.0)',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    }
    log.debug('Fetching a dino image...')
    data = requests.get(
        'https://dinosaurpictures.org/api/dinosaur/random',
        headers=headers,
        params={'_': int(time.time() * 1000)},
    ).json()
    image_url = data['pics'][0]['url']
    img = Image.open(BytesIO(requests.get(image_url, headers=headers).content))
    log.info(f'Dino image fetched: {image_url} ({img.width}x{img.height})')
    return img


def clear_image() -> Image.Image:
    """Return a small blank white placeholder image."""
    return Image.new('RGB', (200, 10), color='white')


# ---------------------------------------------------------------------------
# Image manipulation
# ---------------------------------------------------------------------------

def rotate_image(image: Image.Image, angle: int) -> Image.Image:
    """Rotate image by angle degrees counter-clockwise, expanding the canvas."""
    return image.rotate(angle, expand=True)


def resize_image(
    image: Image.Image,
    width: int,
    height: int,
    dpi: int,
    crop: bool = False,
    offset: tuple[float, float] = (0.0, 0.0),
    target_px: tuple[int, int] | None = None,
) -> Image.Image:
    """Resize image to fit a label (mm). height=0 means proportional.

    If *target_px* is given it is used as the exact canvas size in pixels,
    overriding the mm/DPI calculation.  A height of 0 in *target_px* means
    the height is still derived from *height* (mm) or proportionally.
    """
    if target_px is not None:
        target_width = target_px[0]
        if target_px[1] > 0:
            target_height = target_px[1]
        elif height > 0:
            target_height = int(round(height / 25.4 * dpi))
        else:
            target_height = int(round(image.height / image.width * target_width))
    else:
        target_width = int(round(width / 25.4 * dpi))
        if height > 0:
            target_height = int(round(height / 25.4 * dpi))
        else:
            target_height = int(round(image.height / image.width * target_width))

    offset_x_px = int(round(offset[0] / 25.4 * dpi))
    offset_y_px = int(round(offset[1] / 25.4 * dpi))

    log.debug(
        f'Resizing image to {target_width}x{target_height} for label size '
        f'{width}mm x {height}mm at {dpi} DPI (crop={crop}, offset_px=({offset_x_px}, {offset_y_px}))'
    )

    if height <= 0:
        return image.resize((target_width, target_height), Image.LANCZOS)

    source_ratio = image.width / image.height
    target_ratio = target_width / target_height

    if crop:
        if source_ratio > target_ratio:
            scaled_h = target_height
            scaled_w = int(round(target_height * source_ratio))
        else:
            scaled_w = target_width
            scaled_h = int(round(target_width / source_ratio))

        resized = image.resize((scaled_w, scaled_h), Image.LANCZOS)
        left = max(0, min((scaled_w - target_width) // 2 + offset_x_px, scaled_w - target_width))
        top = max(0, min((scaled_h - target_height) // 2 + offset_y_px, scaled_h - target_height))
        return resized.crop((left, top, left + target_width, top + target_height))

    # Letterbox
    if source_ratio > target_ratio:
        scaled_w = target_width
        scaled_h = int(round(target_width / source_ratio))
    else:
        scaled_h = target_height
        scaled_w = int(round(target_height * source_ratio))

    resized = image.resize((scaled_w, scaled_h), Image.LANCZOS)
    result = Image.new('RGB', (target_width, target_height), 'white')

    paste_x = max(-(scaled_w), min((target_width - scaled_w) // 2 + offset_x_px, target_width))
    paste_y = max(-(scaled_h), min((target_height - scaled_h) // 2 + offset_y_px, target_height))

    if resized.mode in ('RGBA', 'LA'):
        result.paste(resized.convert('RGB'), (paste_x, paste_y), resized.split()[-1])
    else:
        result.paste(resized, (paste_x, paste_y))

    return result


def dither_image(
    image: Image.Image,
    black_point: int = 0,
    white_point: int = 255,
    contrast: float = 1.0,
) -> Image.Image:
    """Convert image to 1-bit dithered output with level mapping and contrast."""
    log.debug(
        f'Dithering image (black_point={black_point}, white_point={white_point}, contrast={contrast})...'
    )
    gray = image.convert('L')

    if contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast)

    pixels = []
    for pixel in gray.getdata(band=0):
        if pixel <= black_point:
            pixels.append(0)
        elif pixel >= white_point:
            pixels.append(255)
        else:
            pixels.append(int((pixel - black_point) / (white_point - black_point) * 255))
    gray.putdata(pixels)

    result = gray.convert('1')
    log.info(f'Image dithered to {result.width}x{result.height} pixels for printing.')
    return result


# ---------------------------------------------------------------------------
# Text overlay
# ---------------------------------------------------------------------------

def _estimate_wrap_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    lines: list[str] = []
    for paragraph in text.splitlines() or ['']:
        words = paragraph.split()
        if not words:
            lines.append('')
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f'{current} {word}'
            if font.getlength(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_text_overlay(
    base_image: Image.Image,
    state: dict,
    font_path: str | None,
) -> Image.Image:
    """Composite text onto base_image per state. Rotation is image-space."""
    text = state['text'].strip()
    if not text or not font_path:
        return base_image

    font_size = max(5, int(state['text_size']))
    try:
        font = ImageFont.truetype(font_path, size=font_size)
    except OSError:
        log.warning(f'Could not load font from {font_path}; using default font.')
        font = ImageFont.load_default()

    # Measure lines using a scratch draw
    _tmp = Image.new('RGBA', (1, 1))
    _tmp_draw = ImageDraw.Draw(_tmp)
    margin_x = 8
    max_width = max(20, base_image.width - 2 * margin_x)
    lines = _estimate_wrap_width(text, font, max_width)

    line_sizes = [_tmp_draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [(bbox[3] - bbox[1]) for bbox in line_sizes] if line_sizes else [font_size]
    line_widths = [(bbox[2] - bbox[0]) for bbox in line_sizes] if line_sizes else [0]
    line_spacing = max(2, font_size // 5)
    block_height = sum(line_heights) + line_spacing * (len(line_heights) - 1)
    block_width = max(line_widths) if line_widths else 1

    h_align = state['h_align']
    fill = (0, 0, 0, 255) if state['black_text'] else (255, 255, 255, 255)
    stroke_width = max(1, font_size // 12) if state['outline'] else 0
    stroke_fill = ((255, 255, 255, 255) if state['black_text'] else (0, 0, 0, 255)) if state['outline'] else None

    # Pad the canvas by stroke_width on all sides so the stroke isn't clipped at the edges
    pad = stroke_width
    # Render text into a padded canvas (no image-space alignment yet)
    canvas = Image.new('RGBA', (block_width + pad * 2, block_height + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    current_y = pad
    for idx, line in enumerate(lines):
        lw = line_widths[idx]
        bbox = line_sizes[idx]
        if h_align == 'Left':
            line_x = pad
        elif h_align == 'Right':
            line_x = pad + block_width - lw
        else:
            line_x = pad + (block_width - lw) // 2
        # Offset by bbox origin so visual pixels start at (line_x, current_y)
        # rather than at (line_x + bbox[0], current_y + bbox[1])
        draw.text(
            (line_x - bbox[0], current_y - bbox[1]), line, font=font, fill=fill,
            stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        current_y += line_heights[idx] + line_spacing

    # Rotate the tight canvas (expand=True keeps the full rotated content)
    rotation = int(state['rotate_text']) % 360
    if rotation:
        canvas = canvas.rotate(rotation, expand=True, fillcolor=(0, 0, 0, 0))

    # Position on base image using alignment (image-space, after rotation)
    v_align = state['v_align']
    if v_align == 'Top':
        base_y = 10
    elif v_align == 'Bottom':
        base_y = base_image.height - canvas.height - 10
    else:
        base_y = (base_image.height - canvas.height) // 2

    if h_align == 'Left':
        base_x = 10
    elif h_align == 'Right':
        base_x = base_image.width - canvas.width - 10
    else:
        base_x = (base_image.width - canvas.width) // 2

    # Apply offsets (image-space, post-rotation — always right/down)
    paste_x = base_x + int(state['text_offset_x'])
    paste_y = base_y + int(state['text_offset_y'])

    result = base_image.convert('RGBA')
    result.paste(canvas, (paste_x, paste_y), mask=canvas)
    return result.convert('RGB')


# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

def list_fonts(
    font_dir: Path = Path('fonts'),
    use_system_fonts: bool = False,
) -> list[tuple[str, str]]:
    """Discover font files; returns (name, path) pairs."""
    log.debug(f'Listing fonts from {font_dir} with use_system_fonts={use_system_fonts}...')
    fonts: dict[str, str] = {}

    if font_dir.exists():
        for entry in sorted(font_dir.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and entry.suffix.lower() in FONT_EXTENSIONS:
                fonts[entry.stem] = str(entry)

    if use_system_fonts:
        system = platform.system()
        if system == 'Darwin':
            system_dirs = [Path('/Library/Fonts'), Path(os.path.expanduser('~/Library/Fonts'))]
        elif system == 'Linux':
            system_dirs = [Path('/usr/share/fonts'), Path(os.path.expanduser('~/.fonts'))]
        elif system == 'Windows':
            system_dirs = [Path('C:/Windows/Fonts')]
        else:
            system_dirs = []

        for sdir in system_dirs:
            if sdir.exists():
                for entry in sorted(sdir.rglob('*'), key=lambda p: p.name.lower()):
                    if entry.is_file() and entry.suffix.lower() in FONT_EXTENSIONS:
                        if entry.stem not in fonts:
                            fonts[entry.stem] = str(entry)

    log.info(f'Found {len(fonts)} fonts')
    log.debug(f'Fonts: {list(fonts.keys())}')
    return list(fonts.items())


def generate_fonts_preview(font_dir: Path, use_system_fonts: bool = False) -> None:
    """Render a JPEG sheet of all available fonts and save to docs/."""
    fonts = list_fonts(font_dir=font_dir, use_system_fonts=use_system_fonts)
    if not fonts:
        log.warning('No fonts available for preview generation.')
        return

    docs_dir = Path('docs')
    docs_dir.mkdir(exist_ok=True)

    font_size = 30
    line_height = font_size + 10
    left_margin = 20
    top_margin = 20
    content_width = 1000
    total_height = top_margin + len(fonts) * line_height + top_margin

    preview_image = Image.new('RGB', (content_width + 2 * left_margin, total_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(preview_image)

    y_pos = top_margin
    for font_name, font_path in sorted(fonts):
        try:
            font = ImageFont.truetype(font_path, size=font_size)
        except OSError:
            log.warning(f'Could not load font {font_name} from {font_path}')
            font = ImageFont.load_default()
        draw.text(
            (left_margin, y_pos),
            f'{font_name}: The quick brown fox jumps over the lazy dog',
            font=font,
            fill=(0, 0, 0),
        )
        y_pos += line_height

    preview_path = docs_dir / 'fonts_preview.jpg'
    preview_image.save(preview_path, quality=90)
    log.info(f'Fonts preview generated: {preview_path}')


# ---------------------------------------------------------------------------
# Label render pipeline
# ---------------------------------------------------------------------------

def calculate_text_height_mm(
    state: dict,
    width_mm: float,
    dpi: int,
    fonts_by_name: dict[str, str],
    native_width_px: int | None = None,
) -> float:
    """Estimate the label height in mm required for the current text."""
    text = state['text'].strip()
    if not text:
        return 0.0

    font_path = fonts_by_name.get(state['font_name'])
    if not font_path:
        return 0.0

    font_size = max(5, int(state['text_size']))
    try:
        font = ImageFont.truetype(font_path, size=font_size)
    except OSError:
        font = ImageFont.load_default()

    target_width_px = native_width_px if native_width_px is not None else int(round(width_mm / 25.4 * dpi))
    max_width = max(20, target_width_px - 16)
    lines = _estimate_wrap_width(text, font, max_width)

    draw = ImageDraw.Draw(Image.new('RGB', (target_width_px, 100)))
    line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [(bbox[3] - bbox[1]) for bbox in line_sizes] if line_sizes else [font_size]
    line_widths = [(bbox[2] - bbox[0]) for bbox in line_sizes] if line_sizes else [0]
    line_spacing = max(2, font_size // 5)
    block_height_px = sum(line_heights) + line_spacing * (len(line_heights) - 1)
    block_width_px = max(line_widths) if line_widths else 1

    rotation = int(state.get('rotate_text', 0)) % 360
    if rotation in (90, 270):
        # After 90/270° rotation the text block's width becomes the height on the label
        total_height_px = block_width_px + 2 * font_size
    else:
        total_height_px = block_height_px + 2 * font_size

    return total_height_px * 25.4 / dpi


def calculate_barcode_height_mm(state: dict, dpi: int) -> float:
    """Estimate the label height in mm required for the barcode."""
    bc_img: Image.Image | None = state.get('barcode_image')
    if bc_img is None:
        return 0.0

    size = max(1, state.get('barcode_size', 3))
    rotation = int(state.get('barcode_rotate', 0)) % 360
    padding = max(4, size * 4)

    if rotation in (90, 270):
        # After 90/270° rotation the barcode width becomes the height
        scaled_height_px = bc_img.width * size
    else:
        scaled_height_px = bc_img.height * size

    total_height_px = scaled_height_px + padding * 2
    return total_height_px * 25.4 / dpi


def draw_barcode_overlay(
    base_image: Image.Image,
    state: dict,
) -> Image.Image:
    """Composite the barcode overlay onto base_image per state."""
    bc_img: Image.Image | None = state.get('barcode_image')
    if bc_img is None:
        return base_image

    size = max(1, state.get('barcode_size', 3))
    scaled = bc_img.resize(
        (bc_img.width * size, bc_img.height * size), Image.NEAREST
    )

    # Rotate (expand so the full barcode stays visible)
    rotation = int(state.get('barcode_rotate', 0)) % 360
    if rotation:
        scaled = scaled.rotate(rotation, expand=True, fillcolor='white')

    # Add a white border (padding) around the barcode
    padding = max(4, size * 4)
    padded = Image.new('RGB', (scaled.width + padding * 2, scaled.height + padding * 2), 'white')
    padded.paste(scaled, (padding, padding))

    offset_x = int(state.get('barcode_offset_x', 0))
    offset_y = int(state.get('barcode_offset_y', 0))

    h_align = state.get('barcode_h_align', 'Center')
    v_align = state.get('barcode_v_align', 'Center')

    if h_align == 'Left':
        base_x = 10
    elif h_align == 'Right':
        base_x = base_image.width - padded.width - 10
    else:
        base_x = (base_image.width - padded.width) // 2

    if v_align == 'Top':
        base_y = 10
    elif v_align == 'Bottom':
        base_y = base_image.height - padded.height - 10
    else:
        base_y = (base_image.height - padded.height) // 2

    paste_x = base_x + offset_x
    paste_y = base_y + offset_y

    result = base_image.copy().convert('RGB')
    result.paste(padded, (paste_x, paste_y))
    return result


def render_preview(
    state: dict,
    fonts_by_name: dict[str, str],
    config: dict,
    target_px: tuple[int, int] | None = None,
) -> Image.Image:
    """Render a full label preview image from the current UI state.

    *target_px* overrides the canvas size with exact printer dot dimensions
    (width, height), bypassing the mm/DPI calculation.  Pass the value
    returned by :func:`stikka_print_it.get_ql_native_pixels` for Brother QL
    printers so that dithering always happens at the printer's exact pixel grid.
    """
    log.debug('Rendering preview image with current state...')
    printer = config['printers'][state['selected_printer']]
    label = printer['label']
    dpi = printer.get('dpi', 300)
    width_mm = label['width']
    length_mm = label.get('length', 0)

    native_width_px = target_px[0] if target_px is not None else None

    source_image = state['image'] if state['image'] is not None else clear_image()
    offset_mm = (
        state['img_offset_x'] * 25.4 / dpi,
        state['img_offset_y'] * 25.4 / dpi,
    )

    has_image = state['image'] is not None
    has_text = bool(state['text'].strip())
    has_barcode = state.get('barcode_image') is not None
    should_auto_scale = not has_image and length_mm == 0 and (has_text or has_barcode)
    if should_auto_scale:
        text_height = calculate_text_height_mm(
            state, width_mm, dpi, fonts_by_name, native_width_px=native_width_px
        )
        barcode_height = calculate_barcode_height_mm(state, dpi)
        length_mm = max(text_height, barcode_height)
        log.debug(
            f'Auto-scaling label height to {length_mm:.1f}mm '
            f'(text={text_height:.1f}mm, barcode={barcode_height:.1f}mm)'
        )

    resized = resize_image(source_image, width=width_mm, height=length_mm, dpi=dpi,
                           crop=state['crop_image'], offset=offset_mm,
                           target_px=target_px)
    with_text = draw_text_overlay(
        base_image=resized.convert('RGB'),
        state=state,
        font_path=fonts_by_name.get(state['font_name']),
    )
    with_barcode = draw_barcode_overlay(with_text, state)

    if state['dither_preview']:
        return dither_image(
            with_barcode,
            black_point=state['black_point'],
            white_point=state['white_point'],
            contrast=state['contrast'],
        ).convert('RGB')
    return with_barcode


# ---------------------------------------------------------------------------
# PIL conversion utilities
# ---------------------------------------------------------------------------

def pil_to_data_url(image: Image.Image, fmt: str = 'PNG') -> str:
    """Encode a PIL image as a base-64 data URL."""
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/{fmt.lower()};base64,{encoded}'


def pil_to_bytes(image: Image.Image, fmt: str = 'PNG') -> bytes:
    """Encode a PIL image as raw bytes."""
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------

async def _maybe_await(value):
    """Await value if it is a coroutine, otherwise return it directly."""
    if inspect.isawaitable(value):
        return await value
    return value


async def uploaded_file_to_image(upload_event) -> Image.Image:
    """Convert a NiceGUI upload event to a PIL RGB image (supports PDF via pypdfium2)."""
    content = getattr(upload_event, 'content', None)
    if content is None:
        content = getattr(upload_event, 'file', None)
    if content is None:
        args = getattr(upload_event, 'args', None)
        if isinstance(args, dict):
            content = args.get('content') or args.get('file')
    if content is None:
        raise ValueError('No upload content received from browser event.')

    if isinstance(content, (bytes, bytearray, memoryview)):
        file_bytes = bytes(content)
    elif isinstance(content, str):
        if os.path.isfile(content):
            with open(content, 'rb') as f:
                file_bytes = f.read()
        else:
            payload = content.split(',', 1)[1] if content.startswith('data:') and ',' in content else content
            file_bytes = base64.b64decode(payload)
    elif hasattr(content, 'file') and hasattr(content.file, 'read'):
        if hasattr(content.file, 'seek'):
            await _maybe_await(content.file.seek(0))
        file_bytes = await _maybe_await(content.file.read())
    elif hasattr(content, 'read'):
        if hasattr(content, 'seek'):
            await _maybe_await(content.seek(0))
        file_bytes = await _maybe_await(content.read())
    else:
        raise ValueError('Unsupported upload payload type.')

    if not file_bytes:
        raise ValueError('Uploaded file is empty.')

    file_name = str(getattr(upload_event, 'name', '') or '').lower()
    file_type = str(getattr(upload_event, 'type', '') or '').lower()
    is_pdf = (
        file_name.endswith('.pdf')
        or file_type.startswith('application/pdf')
        or file_bytes.startswith(b'%PDF')
    )

    if is_pdf:
        log.info(f'PDF file uploaded ({len(file_bytes)} bytes)')
        try:
            pdfium = importlib.import_module('pypdfium2')
        except ModuleNotFoundError as exc:
            raise RuntimeError('PDF support requires pypdfium2 to be installed.') from exc
        pdf_doc = pdfium.PdfDocument(file_bytes)
        if len(pdf_doc) == 0:
            raise ValueError('PDF has no pages.')
        return pdf_doc[0].render(scale=2).to_pil().convert('RGB')

    log.info(f'Image file uploaded ({len(file_bytes)} bytes)')
    with Image.open(BytesIO(file_bytes)) as image:
        return image.convert('RGB')
