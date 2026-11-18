"""INN (Russian taxpayer id) checksum validation."""

from __future__ import annotations

_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(value: str) -> bool:
    """10 digits (organisation) or 12 digits (individual entrepreneur) with valid control digits."""
    if not value.isdigit() or not value.isascii():
        return False
    if len(value) == 10:
        return _check_digit(value, _W10) == int(value[9])
    if len(value) == 12:
        return _check_digit(value, _W11) == int(value[10]) and _check_digit(value, _W12) == int(value[11])
    return False
