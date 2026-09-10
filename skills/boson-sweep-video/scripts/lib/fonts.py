"""Locate DejaVu fonts across common Linux/macOS layouts; fall back to PIL's
built-in font (with a warning) so rendering never hard-fails on a font path."""
import os
import sys
from PIL import ImageFont

_CANDIDATE_DIRS = [
    os.environ.get("BOSON_VIZ_FONT_DIR", ""),
    "/usr/share/fonts/dejavu-sans-mono-fonts", "/usr/share/fonts/dejavu-sans-fonts",  # Fedora/RHEL
    "/usr/share/fonts/truetype/dejavu",                                              # Debian/Ubuntu
    "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",                               # Arch & friends
    "/opt/homebrew/share/fonts", "/usr/local/share/fonts", "/Library/Fonts",         # macOS
    os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
]
_FILES = {
    ("mono", False): "DejaVuSansMono.ttf",
    ("mono", True): "DejaVuSansMono-Bold.ttf",
    ("sans", False): "DejaVuSans.ttf",
    ("sans", True): "DejaVuSans-Bold.ttf",
}
_warned = set()


def _find(name):
    for d in _CANDIDATE_DIRS:
        if d and os.path.exists(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


def load(kind, size, bold=False):
    path = _find(_FILES[(kind, bold)])
    if path:
        return ImageFont.truetype(path, int(size))
    key = (kind, bold)
    if key not in _warned:
        _warned.add(key)
        print(f"[viz] warning: {_FILES[key]} not found; using PIL default font "
              f"(set BOSON_VIZ_FONT_DIR to a directory holding the DejaVu .ttf files)", file=sys.stderr)
    try:
        return ImageFont.load_default(size=int(size))
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()
