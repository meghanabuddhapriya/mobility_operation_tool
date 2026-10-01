"""Small, dependency-free helpers shared by models, services and views."""
from datetime import datetime
from typing import Optional

from .constants import ID_PATTERN, TIME_SLOTS

_FALLBACK_FORMATS = ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M")


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division that never raises; returns `default` when the denominator is zero."""
    return numerator / denominator if denominator else default


def pct(numerator: float, denominator: float) -> float:
    """Percentage rounded to 2 dp; 0.0 when the denominator is zero."""
    return round(safe_div(numerator, denominator) * 100, 2)


def parse_timestamp(text: Optional[str]) -> Optional[datetime]:
    """Parse a timestamp string into a naive datetime; None if blank; ValueError if unreadable."""
    if text is None or not str(text).strip():
        return None
    text = str(text).strip()
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _FALLBACK_FORMATS:
            try:
                value = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unreadable timestamp: {text!r}")
    return value.replace(tzinfo=None)   # keep every datetime naive so they are always comparable


def parse_float(text: Optional[str]) -> Optional[float]:
    """Parse a number; None if blank; ValueError if not a finite number."""
    if text is None or not str(text).strip():
        return None
    value = float(str(text).strip().replace(",", ""))
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("not finite")
    return value


def is_valid_id(value: Optional[str]) -> bool:
    return bool(value) and bool(ID_PATTERN.match(value))


def make_zone_id(city: str, zone_name: str) -> str:
    """Stable, URL-safe zone key, e.g. ('Bangalore', 'HSR Layout') -> 'BANGALORE-HSR-LAYOUT'."""
    raw = f"{city}-{zone_name}".upper()
    return "-".join(raw.replace("_", " ").split())


# Hour -> slot label lookup table, built once, so slot assignment is O(1).
_HOUR_TO_SLOT = [""] * 24
for _label, _start, _end in TIME_SLOTS:
    for _h in range(_start, _end):
        _HOUR_TO_SLOT[_h] = _label


def slot_for(moment: datetime) -> str:
    return _HOUR_TO_SLOT[moment.hour]


def inr(amount: float, decimals: int = 0) -> str:
    """Format a number with the rupee sign and Indian digit grouping (12,34,567)."""
    negative = amount < 0
    whole, _, frac = f"{abs(amount):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    text = f"₹{whole}" + (f".{frac}" if decimals else "")
    return f"-{text}" if negative else text


def parse_number_arg(raw, name: str, default: float, minimum: float, maximum: float) -> float:
    """Validate a numeric query-string/form argument; raises ValueError with a user-facing message."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number.")
    if value != value or not (minimum <= value <= maximum):
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return value
