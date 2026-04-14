from PIL import Image, ImageDraw, ImageFont
import requests
import base64
import inspect
import importlib
import os
from io import BytesIO

import logging
from rich import json
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler

import json
config = json.load(open('config.json'))

FORMAT = "%(message)s"
logging.basicConfig(
    level=getattr(logging, config.get('debug_level', 'INFO').upper(), logging.INFO),
    format=FORMAT, 
    datefmt="[%X]",
    handlers=[
        RichHandler(
            markup=True,
            highlighter=NullHighlighter()
        )    
    ]
)

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("PIL").setLevel(logging.WARNING)
log = logging.getLogger("rich")


def crop_to_content(image: Image, threshold: int = 10) -> Image:
    # Crop the image to the bounding box of non-white pixels
    log.debug("Cropping image to content...")
    gray = image.convert('L')
    bbox = gray.point(lambda x: 0 if x < threshold else 255).getbbox()
    if bbox:
        cropped_image = image.crop(bbox)
        log.info(f"Image cropped to content: {cropped_image.width}x{cropped_image.height} pixels.")
        return cropped_image
    else:
        log.warning("No content found to crop; returning original image.")
        return image

def get_cat() -> Image:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Stikka-NG/1.0)"
    }
    log.debug("Fetching a cat image...")
    response = requests.get("https://api.thecatapi.com/v1/images/search", headers=headers)
    data = response.json()
    image_url = data[0]['url']
    response = requests.get(image_url, headers=headers)
    img = Image.open(BytesIO(response.content))
    log.info(f"Cat image fetched: {image_url} ({img.width}x{img.height})")
    return img
    
def get_dog() -> Image:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Stikka-NG/1.0)"
    }
    log.debug("Fetching a dog image...")
    response = requests.get("https://dog.ceo/api/breeds/image/random", headers=headers)
    data = response.json()
    image_url = data['message']
    response = requests.get(image_url, headers=headers)
    img = Image.open(BytesIO(response.content))
    log.info(f"Dog image fetched: {image_url} ({img.width}x{img.height})")
    return img

def clear_image() -> Image:
    return Image.new('RGB', (200, 10), color = 'white')


def rotate_image(image: Image, angle: int) -> Image:
    return image.rotate(angle, expand=True)

def prepare_image(image: Image, width: int, height: int, dpi: int, crop: bool = False, offset: tuple = (0, 0)) -> Image:
    image = resize_image(image, width, height, dpi, crop, offset)
    dithered_image = dither_image(image)
    return dithered_image

def resize_image(image: Image, width: int, height: int, dpi: int, crop: bool = False, offset: tuple = (0, 0)) -> Image:
    # Resize while preserving ratio. If a fixed label height is given, either
    # letterbox (white borders) or crop-to-fill depending on `crop`.
    target_width = int(round(width / 25.4 * dpi))
    if height > 0:
        target_height = int(round(height / 25.4 * dpi))
    else:
        target_height = int(round(image.height / image.width * target_width))

    offset_x_px = int(round(offset[0] / 25.4 * dpi))
    offset_y_px = int(round(offset[1] / 25.4 * dpi))

    log.debug(
        f"Resizing image to {target_width}x{target_height} for label size "
        f"{width}mm x {height}mm at {dpi} DPI (crop={crop}, offset_px=({offset_x_px}, {offset_y_px}))"
    )

    # If no fixed height is requested, keep simple proportional resize by width.
    if height <= 0:
        return image.resize((target_width, target_height), Image.LANCZOS)

    source_ratio = image.width / image.height
    target_ratio = target_width / target_height

    if crop:
        # Scale to cover target area, then center-crop (with optional offset).
        if source_ratio > target_ratio:
            scaled_height = target_height
            scaled_width = int(round(target_height * source_ratio))
        else:
            scaled_width = target_width
            scaled_height = int(round(target_width / source_ratio))

        resized = image.resize((scaled_width, scaled_height), Image.LANCZOS)

        left = (scaled_width - target_width) // 2 + offset_x_px
        top = (scaled_height - target_height) // 2 + offset_y_px
        left = max(0, min(left, scaled_width - target_width))
        top = max(0, min(top, scaled_height - target_height))

        return resized.crop((left, top, left + target_width, top + target_height))

    # crop=False: scale to fit and center on white background (with offset).
    if source_ratio > target_ratio:
        scaled_width = target_width
        scaled_height = int(round(target_width / source_ratio))
    else:
        scaled_height = target_height
        scaled_width = int(round(target_height * source_ratio))

    resized = image.resize((scaled_width, scaled_height), Image.LANCZOS)
    result = Image.new('RGB', (target_width, target_height), 'white')

    paste_x = (target_width - scaled_width) // 2 + offset_x_px
    paste_y = (target_height - scaled_height) // 2 + offset_y_px
    paste_x = max(0, min(paste_x, target_width - scaled_width))
    paste_y = max(0, min(paste_y, target_height - scaled_height))

    # Keep transparency handling safe when the input has an alpha channel.
    if resized.mode in ('RGBA', 'LA'):
        result.paste(resized.convert('RGB'), (paste_x, paste_y), resized.split()[-1])
    else:
        result.paste(resized, (paste_x, paste_y))

    return result


def dither_image(image: Image, black_point: int = 0, white_point: int = 255, contrast: float = 1.0) -> Image:
    # Convert the image to black and white using dithering
    log.debug(f"Converting image to black and white with dithering (black_point={black_point}, white_point={white_point}, contrast={contrast})...")
    
    # Convert to grayscale
    gray = image.convert('L')
    
    # Apply contrast adjustment
    if contrast != 1.0:
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(contrast)
    
    # Normalize to black_point and white_point range
    gray_array = gray.getdata(band=0)
    pixels = []
    for pixel in gray_array:
        # Normalize: map [black_point, white_point] -> [0, 255]
        if pixel <= black_point:
            normalized = 0
        elif pixel >= white_point:
            normalized = 255
        else:
            normalized = int((pixel - black_point) / (white_point - black_point) * 255)
        pixels.append(normalized)
    
    gray.putdata(pixels)
    
    # Dither to black and white
    dithered_image = gray.convert('1')  # Convert to black and white with dithering
    log.info(f"Image dithered to {dithered_image.width}x{dithered_image.height} pixels for printing.")
    return dithered_image


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def pil_to_data_url(image: Image.Image, fmt: str = 'PNG') -> str:
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/{fmt.lower()};base64,{encoded}'


def pil_to_bytes(image: Image.Image, fmt: str = 'PNG') -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


async def uploaded_file_to_image(upload_event) -> Image.Image:
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

    is_pdf = (file_name.endswith('.pdf') or file_type.startswith('application/pdf') or file_bytes.startswith(b'%PDF'))

    if is_pdf:
        log.info(f"PDF file uploaded, size: {len(file_bytes)} bytes)")
        try:
            pdfium = importlib.import_module('pypdfium2')
        except ModuleNotFoundError as exc:
            raise RuntimeError('PDF support requires pypdfium2 to be installed.') from exc

        pdf_doc = pdfium.PdfDocument(file_bytes)
        if len(pdf_doc) == 0:
            raise ValueError('PDF has no pages.')

        page = pdf_doc[0]
        rendered = page.render(scale=2)
        return rendered.to_pil().convert('RGB')
    
    else:
        log.info(f"Image file uploaded, size: {len(file_bytes)} bytes)")

    with Image.open(BytesIO(file_bytes)) as image:
        return image.convert('RGB')


def _estimate_wrap_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
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


def draw_text_overlay(base_image: Image.Image, state: dict, font_path: str | None) -> Image.Image:
    text = state['text'].strip()
    if not text or not font_path:
        return base_image

    text_content = text
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
    lines = _estimate_wrap_width(text_content, font, max_width)

    line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    block_width = max((bbox[2] - bbox[0]) for bbox in line_sizes) if line_sizes else 0
    line_heights = [(bbox[3] - bbox[1]) for bbox in line_sizes] if line_sizes else [font_size]
    line_spacing = max(2, font_size // 5)
    block_height = sum(line_heights) + line_spacing * (len(line_heights) - 1)

    if state['h_align'] == 'Left':
        x = 0
    elif state['h_align'] == 'Right':
        x = base_image.width - block_width
    else:
        x = (base_image.width - block_width) // 2

    if state['v_align'] == 'Top':
        y = 0
    elif state['v_align'] == 'Bottom':
        y = base_image.height - block_height
    else:
        y = (base_image.height - block_height) // 2

    x += int(state['text_offset_x'])
    y += int(state['text_offset_y'])

    x = max(0, min(x, base_image.width - max(1, block_width)))
    y = max(0, min(y, base_image.height - max(1, block_height)))

    fill = (0, 0, 0, 255) if state['black_text'] else (255, 255, 255, 255)
    if state['outline']:
        stroke_width = max(1, font_size // 12)
        stroke_fill = (255, 255, 255, 255) if state['black_text'] else (0, 0, 0, 255)
    else:
        stroke_width = 0
        stroke_fill = None
    current_y = y
    for idx, line in enumerate(lines):
        draw.text((x, current_y), line, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        current_y += line_heights[idx] + line_spacing

    rotation = int(state['rotate_text']) % 360
    if rotation:
        overlay = overlay.rotate(rotation, expand=False)

    combined = Image.alpha_composite(base_image.convert('RGBA'), overlay)
    return combined.convert('RGB')
