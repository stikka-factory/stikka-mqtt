"""Configuration, statistics, and printer helpers for Stikka-NG."""
from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

import stikka_label_helper as lh

log = lh.log

config: dict = {}

STATS_FILE = Path('print_stats.csv')
STATS_FIELDS = [
    'printed_total', 'printed_cats', 'printed_dogs', 'printed_dinos',
    'printed_uploaded_images', 'printed_webcam_images', 'printed_without_image',
]
_STATS_LOCK = threading.Lock()

_STAT_KEY = {
    'cat': 'printed_cats',
    'dog': 'printed_dogs',
    'dino': 'printed_dinos',
    'upload': 'printed_uploaded_images',
    'webcam': 'printed_webcam_images',
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

import re as _re


def parse_label_format(label: dict) -> None:
    """Resolve the optional 'format' shorthand in a label dict in-place.

    Accepted formats:
      'NxM'  – width N mm × length M mm  (M=0 means endless)
      'Nx0'  – width N mm, endless
      'dN'   – round label, diameter N mm (sets width=N, length=N, is_round=True)

    Fields already present (width / length) are preserved as a fallback if
    'format' is absent.  'is_round' is always set.
    """
    fmt = label.get('format', '')
    if fmt:
        m_round = _re.fullmatch(r'd(\d+(?:\.\d+)?)', fmt, _re.IGNORECASE)
        m_rect  = _re.fullmatch(r'(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)', fmt, _re.IGNORECASE)
        if m_round:
            d = float(m_round.group(1))
            label['width']   = d
            label['length']  = d
            label['is_round'] = True
        elif m_rect:
            label['width']  = float(m_rect.group(1))
            label['length'] = float(m_rect.group(2))
            label.setdefault('is_round', False)
        else:
            log.warning(f'Unrecognised label format string "{fmt}" – ignoring.')
            label.setdefault('is_round', False)
    else:
        label.setdefault('is_round', False)


_LABEL_RUNTIME_KEYS = ('width', 'length', 'is_round')


def clean_config() -> dict:
    """Return a deep copy of config with runtime-injected label keys stripped."""
    import copy
    clean = copy.deepcopy(config)
    for p in clean.get('printers', []):
        for k in _LABEL_RUNTIME_KEYS:
            p['label'].pop(k, None)
    return clean


def write_config() -> None:
    """Serialise config to disk, stripping runtime-injected label keys."""
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(clean_config(), f, indent=4)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _read_stats() -> dict[str, int]:
    if not STATS_FILE.exists():
        return {f: 0 for f in STATS_FIELDS}
    with STATS_FILE.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    row = rows[0] if rows else {}
    return {field: int(row.get(field, 0) or 0) for field in STATS_FIELDS}


def _write_stats(stats: dict[str, int]) -> None:
    with STATS_FILE.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=STATS_FIELDS)
        writer.writeheader()
        writer.writerow(stats)


def init_stats_csv() -> None:
    if not STATS_FILE.exists():
        _write_stats({f: 0 for f in STATS_FIELDS})


def read_stats() -> dict[str, int]:
    return _read_stats()


def record_print(source_kind: str) -> None:
    with _STATS_LOCK:
        stats = _read_stats()
        stats['printed_total'] += 1
        stats[_STAT_KEY.get(source_kind, 'printed_without_image')] += 1
        _write_stats(stats)


def reset_stats() -> None:
    with _STATS_LOCK:
        _write_stats({f: 0 for f in STATS_FIELDS})



