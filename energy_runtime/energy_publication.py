"""Shared Korean report publication label and observation cutoff policy."""
from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
DAILY_HOUR = 7
SHOW_PROVISIONAL_LABEL = False

def publication_label(at):
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    if at.tzinfo is None:
        raise ValueError('Publication time must include a timezone')
    at = at.astimezone(KST)
    weekday = '월화수목금토일'[at.weekday()]
    return f'발표시점: {at:%Y. %m. %d.}({weekday}) {at:%H}시 기준'

def observation_cutoff(day):
    return datetime.combine(day, time(DAILY_HOUR), KST)
