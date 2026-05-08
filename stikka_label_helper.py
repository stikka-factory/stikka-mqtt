"""Image and label creation utilities for Stikka-NG."""
from __future__ import annotations

import logging
import os
import platform
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
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


