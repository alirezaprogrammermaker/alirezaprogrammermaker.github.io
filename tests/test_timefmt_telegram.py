from __future__ import annotations

from datetime import datetime, timezone

from v2agg.telegram.client import TelegramClient
from v2agg.util.timefmt import format_activity_label, format_tehran_shamsi, gregorian_to_jalali


def test_gregorian_to_jalali_known():
    # 2026-09-18 → 1405/06/27 (Jalali)
    assert gregorian_to_jalali(2026, 9, 18) == (1405, 6, 27)


def test_format_tehran_shamsi_contains_date():
    dt = datetime(2026, 9, 18, 12, 30, tzinfo=timezone.utc)  # 16:00 Tehran (UTC+3:30 DST? Iran is +3:30 year-round)
    s = format_tehran_shamsi(dt)
    assert s.startswith("1405/06/27")
    assert ":" in s


def test_format_activity_label_tehran():
    label = format_activity_label(datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc))
    assert "به وقت تهران" in label
    assert "1405/06/27" in label


def test_channel_description_has_shamsi_and_links():
    client = TelegramClient(
        {
            "app": {
                "channel_description": "کانفیگ‌های فعال V2Ray/Xray · تست خودکار",
                "pages_base_url": "https://alirezaprogrammermaker.github.io",
            },
            "telegram": {"dry_run": True},
        }
    )
    desc = client.build_channel_description(
        last_activity="1405/06/27 16:00 به وقت تهران",
        alive_count=12,
    )
    assert len(desc) <= 255
    assert "1405/06/27" in desc
    assert "به وقت تهران" in desc
    assert "subs/best.base64" in desc
    assert "subs/all.base64" in desc
    assert "UTC" not in desc
