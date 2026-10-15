"""Small helpers for cleaning up names and numbers coming from the spreadsheet."""

import math
import re

_SPACES = re.compile(r"\s+")


def clean_name(value) -> str:
    """Trim whitespace, collapse double spaces and unify apostrophes."""
    if value is None:
        return ""
    text = str(value).replace("’", "'").replace("‘", "'")
    return _SPACES.sub(" ", text).strip()


def key(name: str) -> str:
    """Lookup key for a name: case-insensitive and whitespace-insensitive."""
    return clean_name(name).lower()


def fmt_num(value: float) -> str:
    """Format a number without a pointless '.0' (3.0 -> '3', 2.5 -> '2.5')."""
    if value is None:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".0%", "%")


def ceil_hits(health: float, damage: float):
    """How many hits of `damage` are needed to remove `health`. None if damage is 0."""
    if damage <= 0:
        return None
    # Round first so 100 / 33.333333 does not become 4 hits because of float noise.
    return max(1, math.ceil(round(health / damage, 6)))
