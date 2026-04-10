from PIL import Image
import requests
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


def send_to_zpl_printer(zpl: str, printer_config: dict):
    log.debug(f"Sending ZPL to printer {printer_config['name']}...")
    if printer_config['backend'] == 'file':
        with open('debug_output.zpl', 'w') as f:
            f.write(zpl)
        log.info(f"ZPL written to debug_output.zpl for printer {printer_config['name']}.")
    else:
        log.error(f"Unsupported printer backend: {printer_config['backend']} for printer {printer_config['name']}.")

def send_to_ql_printer(image: Image, printer_config: dict):
    log.debug(f"Sending image to printer {printer_config['name']}...")
    if printer_config['backend'] == 'file':
        image.save('debug_output.png')
        log.info(f"Image saved as debug_output.png for printer {printer_config['name']}.")
    else:
        log.error(f"Unsupported printer backend: {printer_config['backend']} for printer {printer_config['name']}.")

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
    log.debug(f"Cat image fetched: {image_url} ({img.width}x{img.height})")
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
    log.debug(f"Dog image fetched: {image_url} ({img.width}x{img.height})")
    return img

def clear_image() -> Image:
    return Image.new('RGB', (200, 200), color = 'white')


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
