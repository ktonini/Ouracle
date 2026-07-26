from datetime import datetime, timedelta


def compute_next_daily_run(now: datetime, schedule_time: str) -> datetime:
    try:
        hour, minute = map(int, schedule_time.split(":"))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError
    except Exception:
        hour, minute = 11, 0

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
