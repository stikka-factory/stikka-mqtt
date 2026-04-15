"""
stikka_label_helper.py
======================
Image and label creation utilities for Stikka-NG.

Covers:
- Logging setup (shared across the app via the ``log`` singleton)
- Image fetching (cat/dog APIs)
- Image resizing, cropping, dithering, rotating
- Text overlay rendering
- Font discovery and font-preview generation
- Label render pipeline (``render_preview``)
- PIL ↔ bytes/data-URL conversion helpers
- File-upload parsing (images and PDFs)
"""

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
"""Shared Rich logger used throughout the application."""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FONT_EXTENSIONS: set[str] = {'.ttf', '.otf'}
"""Supported font file extensions for discovery."""


# ---------------------------------------------------------------------------
# Image acquisition
# ---------------------------------------------------------------------------

def get_cat() -> Image.Image:
    """Fetch a random cat image from The Cat API.

    Returns:
        A PIL RGBA/RGB image of a random cat.

    Raises:
        requests.RequestException: If the API call fails.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Stikka-NG/1.0)'}
    log.debug('Fetching a cat image...')
    data = requests.get('https://api.thecatapi.com/v1/images/search', headers=headers).json()
    image_url = data[0]['url']
    img = Image.open(BytesIO(requests.get(image_url, headers=headers).content))
    log.info(f'Cat image fetched: {image_url} ({img.width}x{img.height})')
    return img


def get_dog() -> Image.Image:
    """Fetch a random dog image from the Dog CEO API.

    Returns:
        A PIL RGBA/RGB image of a random dog.

    Raises:
        requests.RequestException: If the API call fails.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Stikka-NG/1.0)'}
    log.debug('Fetching a dog image...')
    data = requests.get('https://dog.ceo/api/breeds/image/random', headers=headers).json()
    image_url = data['message']
    img = Image.open(BytesIO(requests.get(image_url, headers=headers).content))
    log.info(f'Dog image fetched: {image_url} ({img.width}x{img.height})')
    return img


def clear_image() -> Image.Image:
    """Return a small blank white placeholder image.

    Returns:
        A 200×10 white RGB image used when no image is selected.
    """
    return Image.new('RGB', (200, 10), color='white')


# ---------------------------------------------------------------------------
# Image manipulation
# ---------------------------------------------------------------------------

def crop_to_content(image: Image.Image, threshold: int = 10) -> Image.Image:
    """Crop an image to the bounding box of non-white pixels.

    Args:
        image: Source PIL image.
        threshold: Pixel luminance threshold below which a pixel is
            considered non-white content.

    Returns:
        Cropped image, or the original if no content is found.
    """
    log.debug('Cropping image to content...')
    gray = image.convert('L')
    bbox = gray.point(lambda x: 0 if x < threshold else 255).getbbox()
    if bbox:
        cropped = image.crop(bbox)
        log.info(f'Image cropped to content: {cropped.width}x{cropped.height} pixels.')
        return cropped
    log.warning('No content found to crop; returning original image.')
    return image


def rotate_image(image: Image.Image, angle: int) -> Image.Image:
    """Rotate *image* by *angle* degrees counter-clockwise, expanding the canvas.

    Args:
        image: Source PIL image.
        angle: Rotation angle in degrees (0, 90, 180, 270).

    Returns:
        Rotated image with an expanded canvas.
    """
    return image.rotate(angle, expand=True)


def resize_image(
    image: Image.Image,
    width: int,
    height: int,
    dpi: int,
    crop: bool = False,
    offset: tuple[float, float] = (0.0, 0.0),
) -> Image.Image:
    """Resize *image* to fit a label defined in millimetres.

    When *height* is 0 the image is resized proportionally to *width*.
    When *height* > 0 the image is either letterboxed (``crop=False``) or
    cropped-to-fill (``crop=True``), optionally shifted by *offset*.

    Args:
        image: Source PIL image.
        width: Label width in millimetres.
        height: Label height in millimetres (0 = proportional).
        dpi: Printer resolution in dots per inch.
        crop: If ``True`` crop-to-fill; otherwise letterbox.
        offset: (x_mm, y_mm) shift applied after positioning.

    Returns:
        Resized PIL image in RGB mode.
    """
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

    paste_x = max(0, min((target_width - scaled_w) // 2 + offset_x_px, target_width - scaled_w))
    paste_y = max(0, min((target_height - scaled_h) // 2 + offset_y_px, target_height - scaled_h))

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
    """Convert *image* to a 1-bit dithered image ready for printing.

    Applies optional contrast adjustment and level mapping before performing
    Floyd-Steinberg dithering.

    Args:
        image: Source PIL image (any mode).
        black_point: Input luminance value mapped to pure black (0–255).
        white_point: Input luminance value mapped to pure white (0–255).
        contrast: Contrast enhancement factor (1.0 = no change).

    Returns:
        PIL image in mode ``'1'`` (1-bit dithered).
    """
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


def prepare_image(
    image: Image.Image,
    width: int,
    height: int,
    dpi: int,
    crop: bool = False,
    offset: tuple[float, float] = (0.0, 0.0),
) -> Image.Image:
    """Resize then dither *image* for print output.

    Convenience wrapper around :func:`resize_image` and :func:`dither_image`.

    Args:
        image: Source PIL image.
        width: Label width in millimetres.
        height: Label height in millimetres (0 = proportional).
        dpi: Printer resolution.
        crop: If ``True`` crop-to-fill; otherwise letterbox.
        offset: (x_mm, y_mm) image shift.

    Returns:
        1-bit dithered PIL image.
    """
    resized = resize_image(image, width, height, dpi, crop, offset)
    return dither_image(resized)


# ---------------------------------------------------------------------------
# Text overlay
# ---------------------------------------------------------------------------

def _estimate_wrap_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap *text* to fit within *max_width* pixels using *font*.

    Args:
        text: Raw text (may contain newlines).
        font: Pillow FreeType font used for measuring glyph widths.
        max_width: Maximum line width in pixels.

    Returns:
        List of wrapped line strings.
    """
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
    """Composite a text overlay onto *base_image* according to *state*.

    The text is rendered into a transparent RGBA overlay, then alpha-composited
    onto *base_image*.  Supports word-wrap, horizontal/vertical alignment,
    pixel offsets, rotation, outline, and black/white fill.

    Args:
        base_image: RGB background image.
        state: UI state dict containing keys ``text``, ``font_name``,
            ``text_size``, ``h_align``, ``v_align``, ``text_offset_x``,
            ``text_offset_y``, ``rotate_text``, ``black_text``, ``outline``.
        font_path: Absolute path to a TrueType/OpenType font file, or
            ``None`` to skip rendering.

    Returns:
        RGB image with the text composited in.
    """
    text = state['text'].strip()
    if not text or not font_path:
        return base_image

    font_size = max(5, int(state['text_size']))
    try:
        font = ImageFont.truetype(font_path, size=font_size)
    except OSError:
        log.warning(f'Could not load font from {font_path}; using default font.')
        font = ImageFont.load_default()

    overlay = Image.new('RGBA', base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    margin_x = 8
    max_width = max(20, base_image.width - 2 * margin_x)
    lines = _estimate_wrap_width(text, font, max_width)

    line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [(bbox[3] - bbox[1]) for bbox in line_sizes] if line_sizes else [font_size]
    line_spacing = max(2, font_size // 5)
    block_height = sum(line_heights) + line_spacing * (len(line_heights) - 1)

    v_align = state['v_align']
    if v_align == 'Top':
        y = 0
    elif v_align == 'Bottom':
        y = base_image.height - block_height
    else:
        y = (base_image.height - block_height) // 2

    y += int(state['text_offset_y'])
    y = max(0, min(y, base_image.height - max(1, block_height)))

    h_align = state['h_align']
    text_offset_x = int(state['text_offset_x'])
    fill = (0, 0, 0, 255) if state['black_text'] else (255, 255, 255, 255)
    stroke_width = max(1, font_size // 12) if state['outline'] else 0
    stroke_fill = ((255, 255, 255, 255) if state['black_text'] else (0, 0, 0, 255)) if state['outline'] else None

    current_y = y
    for idx, line in enumerate(lines):
        line_width = line_sizes[idx][2] - line_sizes[idx][0]
        if h_align == 'Left':
            line_x = 0
        elif h_align == 'Right':
            line_x = base_image.width - line_width
        else:
            line_x = (base_image.width - line_width) // 2
        line_x += text_offset_x
        line_x = max(0, min(line_x, base_image.width - max(1, line_width)))
        draw.text(
            (line_x, current_y), line, font=font, fill=fill,
            stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        current_y += line_heights[idx] + line_spacing

    rotation = int(state['rotate_text']) % 360
    if rotation:
        overlay = overlay.rotate(rotation, expand=False)

    return Image.alpha_composite(base_image.convert('RGBA'), overlay).convert('RGB')


# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

def list_fonts(
    font_dir: Path = Path('fonts'),
    use_system_fonts: bool = False,
) -> list[tuple[str, str]]:
    """Discover font files and return (name, path) pairs.

    Custom fonts in *font_dir* take precedence over system fonts when names
    collide.

    Args:
        font_dir: Directory to search for custom fonts.
        use_system_fonts: If ``True``, also search OS font directories.

    Returns:
        Sorted list of ``(stem_name, absolute_path)`` tuples.
    """
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
    """Render a JPEG sheet showing all available fonts and save it to ``docs/``.

    Args:
        font_dir: Directory containing custom font files.
        use_system_fonts: Whether to include system fonts in the preview.
    """
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
) -> float:
    """Estimate the height in millimetres required to display the current text.

    Used to auto-scale continuous-roll labels when no image is present.

    Args:
        state: UI state dict (reads ``text``, ``font_name``, ``text_size``).
        width_mm: Label width in millimetres.
        dpi: Printer resolution.
        fonts_by_name: Mapping of font display-name → file path.

    Returns:
        Required height in millimetres, or 0.0 if there is no text.
    """
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

    target_width_px = int(round(width_mm / 25.4 * dpi))
    max_width = max(20, target_width_px - 16)
    lines = _estimate_wrap_width(text, font, max_width)

    draw = ImageDraw.Draw(Image.new('RGB', (target_width_px, 100)))
    line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [(bbox[3] - bbox[1]) for bbox in line_sizes] if line_sizes else [font_size]
    line_spacing = max(2, font_size // 5)
    block_height_px = sum(line_heights) + line_spacing * (len(line_heights) - 1)
    total_height_px = block_height_px + 2 * font_size

    return total_height_px * 25.4 / dpi


def render_preview(
    state: dict,
    fonts_by_name: dict[str, str],
    config: dict,
) -> Image.Image:
    """Render a full label preview image from the current UI state.

    Applies image resizing, text overlay, and optional dithering.

    Args:
        state: UI state dict.
        fonts_by_name: Mapping of font display-name → file path.
        config: Application configuration dict (used to look up the active
            printer's label dimensions and DPI).

    Returns:
        RGB PIL image representing the current label preview.
    """
    log.debug('Rendering preview image with current state...')
    printer = config['printers'][state['selected_printer']]
    label = printer['label']
    dpi = printer.get('dpi', 300)
    width_mm = label['width']
    length_mm = label.get('length', 0)

    source_image = state['image'] if state['image'] is not None else clear_image()
    offset_mm = (
        state['img_offset_x'] * 25.4 / dpi,
        state['img_offset_y'] * 25.4 / dpi,
    )

    has_image = state['image'] is not None
    should_auto_scale = not has_image and length_mm == 0 and state['text'].strip()
    if should_auto_scale:
        length_mm = calculate_text_height_mm(state, width_mm, dpi, fonts_by_name)
        log.debug(f'Auto-scaling label height to {length_mm:.1f}mm based on text')

    resized = resize_image(source_image, width=width_mm, height=length_mm, dpi=dpi,
                           crop=state['crop_image'], offset=offset_mm)
    with_text = draw_text_overlay(
        base_image=resized.convert('RGB'),
        state=state,
        font_path=fonts_by_name.get(state['font_name']),
    )

    if state['dither_preview']:
        return dither_image(
            with_text,
            black_point=state['black_point'],
            white_point=state['white_point'],
            contrast=state['contrast'],
        ).convert('RGB')
    return with_text


# ---------------------------------------------------------------------------
# PIL conversion utilities
# ---------------------------------------------------------------------------

def pil_to_data_url(image: Image.Image, fmt: str = 'PNG') -> str:
    """Encode a PIL image as a base-64 data URL suitable for HTML ``<img>`` tags.

    Args:
        image: PIL image to encode.
        fmt: Image format string (e.g. ``'PNG'``, ``'JPEG'``).

    Returns:
        ``data:<mime>;base64,<data>`` string.
    """
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/{fmt.lower()};base64,{encoded}'


def pil_to_bytes(image: Image.Image, fmt: str = 'PNG') -> bytes:
    """Encode a PIL image as raw bytes in the given format.

    Args:
        image: PIL image to encode.
        fmt: Image format string (e.g. ``'PNG'``, ``'JPEG'``).

    Returns:
        Encoded image bytes.
    """
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------

async def _maybe_await(value):
    """Await *value* if it is a coroutine, otherwise return it directly."""
    if inspect.isawaitable(value):
        return await value
    return value


async def uploaded_file_to_image(upload_event) -> Image.Image:
    """Convert a NiceGUI upload event payload to a PIL RGB image.

    Supports JPEG, PNG, GIF, WebP, BMP, and single-page PDF (via pypdfium2).

    Args:
        upload_event: NiceGUI ``UploadEventArguments`` object.

    Returns:
        RGB PIL image.

    Raises:
        ValueError: If no content is found in the event or the file is empty.
        RuntimeError: If a PDF is uploaded but pypdfium2 is not installed.
    """
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
