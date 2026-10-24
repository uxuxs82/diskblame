import re
from datetime import datetime

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgtp]?i?b?)\s*$", re.IGNORECASE)
_DURATION_RE = re.compile(r"^\s*((?:\d+[smhdw])+)\s*$", re.IGNORECASE)
_DURATION_PART_RE = re.compile(r"(\d+)([smhdw])", re.IGNORECASE)

_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
    "p": 1024**5,
    "pb": 1024**5,
    "pib": 1024**5,
}

_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}

_DISPLAY_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]


def format_size(value):
    sign = "-" if value < 0 else ""
    value = abs(int(value))
    if value < 1024:
        return f"{sign}{value} B"
    amount = float(value)
    for unit in _DISPLAY_UNITS[1:]:
        amount /= 1024
        if amount < 1024 or unit == _DISPLAY_UNITS[-1]:
            return f"{sign}{amount:.1f} {unit}"
    return f"{sign}{amount:.1f} PiB"


def format_delta(value):
    if value > 0:
        return f"+{format_size(value)}"
    return format_size(value)


def parse_size(text):
    match = _SIZE_RE.match(text)
    if not match:
        raise ValueError(f"invalid size: {text}")
    number = float(match.group(1))
    unit = match.group(2).lower()
    if unit not in _SIZE_UNITS:
        raise ValueError(f"invalid size unit: {unit}")
    return int(number * _SIZE_UNITS[unit])


def parse_duration(text):
    match = _DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid duration: {text}")
    total = 0
    for number, unit in _DURATION_PART_RE.findall(match.group(1)):
        total += int(number) * _DURATION_UNITS[unit.lower()]
    return total


def human_age(timestamp, now=None):
    if timestamp is None:
        return "unknown"
    if now is None:
        now = datetime.now().timestamp()
    seconds = int(max(0, now - timestamp))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{months // 12}y ago"


def format_time(timestamp):
    if timestamp is None:
        return "unknown"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
