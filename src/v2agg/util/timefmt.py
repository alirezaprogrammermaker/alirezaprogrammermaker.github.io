from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert Gregorian date to Jalali (Shamsi). Returns (jy, jm, jd)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def format_tehran_shamsi(when: datetime | None = None) -> str:
    """Tehran local time as Shamsi, e.g. '۱۴۰۴/۰۶/۲۷ ۲۱:۴۵' (Western digits)."""
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(TEHRAN)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {local.hour:02d}:{local.minute:02d}"


def format_activity_label(when: datetime | None = None) -> str:
    """Human label for channel description / messages (Shamsi Tehran + short TZ)."""
    shamsi = format_tehran_shamsi(when)
    return f"{shamsi} به وقت تهران"
