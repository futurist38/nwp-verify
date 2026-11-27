"""KMA medium-range issue times in Korean local time."""
import datetime as dt

FIRST_EVENING = dt.datetime(2026, 11, 26, 18)
FIRST_ISSUE = FIRST_EVENING.strftime('%Y%m%d%H')


def scheduled_issue(stamp):
    return stamp.endswith('18') or (stamp < FIRST_ISSUE and stamp.endswith('06'))


def latest_issue(local_time):
    day = local_time.date()
    for hour in (18, 6):
        candidate = dt.datetime.combine(day, dt.time(hour), local_time.tzinfo)
        if candidate <= local_time and scheduled_issue(candidate.strftime('%Y%m%d%H')):
            return candidate
    return dt.datetime.combine(day - dt.timedelta(days=1), dt.time(18), local_time.tzinfo)
