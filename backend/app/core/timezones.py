"""Resolve and validate IANA timezone names."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEZONE_NAME_MAX_LENGTH = 64


def resolve_timezone(name: str) -> ZoneInfo:
    """Return the `ZoneInfo` for an IANA timezone name such as 'Asia/Karachi'.

    Raises `ValueError` for an unknown, malformed, or path-like name, so callers never fall back to a default zone
    that would silently place work on the wrong day.
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"{name!r} is not a recognised IANA timezone name") from error
