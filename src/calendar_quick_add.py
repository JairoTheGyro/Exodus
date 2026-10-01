"""Bounded, offline English calendar parsing. No provider or network imports.

Recognized date/time spans are removed from the title; remaining words are kept.
The caller supplies the user's local clock. Output is a draft for confirmation,
not an instruction to silently save an ambiguous date.
"""
import re
from datetime import datetime, timedelta

WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july',
          'august', 'september', 'october', 'november', 'december')
CLOCK = r'(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\d{1,2}:\d{2}|noon|midnight)'


def _clock(value, inherited=''):
    value = re.sub(r'[\s.]', '', value.lower())
    if value in ('noon', 'midnight'):
        return (12 if value == 'noon' else 0), 0
    m = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?(am|pm)?', value)
    if not m:
        raise ValueError('Use a time such as 2pm or 14:30.')
    hour, minute, meridiem = int(m[1]), int(m[2] or 0), m[3] or inherited
    if minute > 59 or (meridiem and not 1 <= hour <= 12) or (not meridiem and hour > 23):
        raise ValueError('That time is not valid. Use a time such as 2pm or 14:30.')
    if meridiem:
        hour = hour % 12 + (12 if meridiem == 'pm' else 0)
    return hour, minute


def parse_quick_add(text, now):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Describe your event first.')
    if len(text) > 2000:
        raise ValueError('Keep Quick add under 2,000 characters.')
    remaining = text.strip()
    day = now.date()
    explicit_date = False
    relative_start = None
    duration = timedelta(hours=1)
    notices = []

    def take(pattern):
        nonlocal remaining
        match = re.search(pattern, remaining, re.I)
        if match:
            remaining = remaining[:match.start()] + ' ' + remaining[match.end():]
        return match

    unit = r'(minutes?|mins?|hours?|hrs?|days?|weeks?)'
    m = take(r'\bfor\s+(\d+)\s*' + unit + r'\b')
    if m:
        count = int(m[1])
        if not 1 <= count <= 10080:
            raise ValueError('Choose a duration between 1 and 10,080 units.')
        duration = timedelta(**{('minutes' if m[2].lower().startswith(('m',)) else
                                'hours' if m[2].lower().startswith(('h',)) else
                                'weeks' if m[2].lower().startswith('w') else 'days'): count})

    m = take(r'\bin\s+(\d+)\s*' + unit + r'\b')
    if m:
        count = int(m[1])
        if count > 10080:
            raise ValueError('That relative date is too far away; use a calendar date.')
        u = m[2].lower()
        delta = timedelta(**{('minutes' if u.startswith('m') else 'hours' if u.startswith('h')
                             else 'weeks' if u.startswith('w') else 'days'): count})
        target = now + delta
        day, explicit_date = target.date(), True
        if u.startswith(('m', 'h')):
            relative_start = target.replace(second=0, microsecond=0)
    else:
        m = take(r'\b(?:on\s+)?(day after tomorrow|tomorrow|tmrw|today|tonight)\b')
        if m:
            day += timedelta(days={'day after tomorrow': 2, 'tomorrow': 1, 'tmrw': 1}.get(m[1].lower(), 0))
            explicit_date = True
            if m[1].lower() == 'tonight':
                relative_start = now.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            names = '|'.join(d + '|' + d[:3] for d in WEEKDAYS)
            m = take(r'\b(?:on\s+)?(?:(next|this)\s+)?(' + names + r')\b')
            if m:
                weekday = next(i for i, name in enumerate(WEEKDAYS) if name.startswith(m[2].lower()))
                distance = (weekday - day.weekday()) % 7
                if m[1] and m[1].lower() == 'next' and distance == 0:
                    distance = 7
                day += timedelta(days=distance)
                explicit_date = True
            else:
                m = take(r'\b(?:on\s+)?(\d{4}-\d{2}-\d{2})\b')
                if m:
                    day = datetime.strptime(m[1], '%Y-%m-%d').date()
                    explicit_date = True
                else:
                    months = '|'.join(name + '|' + name[:3] for name in MONTHS)
                    m = take(r'\b(?:on\s+)?(' + months + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b')
                    if m:
                        month = next(i + 1 for i, name in enumerate(MONTHS) if name.startswith(m[1].lower()))
                        day = day.replace(year=int(m[3] or day.year), month=month, day=int(m[2]))
                        if not m[3] and day < now.date():
                            day = day.replace(year=day.year + 1)
                        explicit_date = True

    start_clock = end_clock = None
    m = take(r'\b(?:from\s+|at\s+)?(' + CLOCK + r'|\d{1,2})\s*(?:-|–|to|until)\s*(' + CLOCK + r')(?=\s|$|[,;])')
    if m:
        suffix = re.search(r'([ap])\.?m\.?$', m[2], re.I)
        start_clock = _clock(m[1], suffix[1].lower() + 'm' if suffix else '')
        end_clock = _clock(m[2])
    else:
        m = take(r'(?<!\w)(?:at\s+|@\s*)?(' + CLOCK + r')(?=\s|$|[,;])')
        if m:
            start_clock = _clock(m[1])

    # Reject recognizable but unsupported scheduling syntax rather than turn
    # e.g. an ambiguous numeric date into a silently misdated event.
    if re.search(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b(?:at\s+\d|next\s+(?:week|month|year)|every\s+)', remaining, re.I):
        raise ValueError('Please use a date such as Friday or 2026-10-02 and a time such as 2pm. Set repeating events in the event form.')
    title = re.sub(r'\s+', ' ', remaining).strip(' ,;@–-')
    if not title:
        raise ValueError('Add an event title, for example: Meeting tomorrow at 3pm.')
    all_day = start_clock is None and relative_start is None
    start = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo)
    if start_clock:
        start = start.replace(hour=start_clock[0], minute=start_clock[1])
    elif relative_start:
        start = relative_start
    if not explicit_date and not relative_start:
        notices.append('No date supplied; using today. Review before saving.')
    end = start + (timedelta(days=1) if all_day else duration)
    if end_clock:
        end = start.replace(hour=end_clock[0], minute=end_clock[1])
        if end <= start:
            end += timedelta(days=1)
    # Local wall-clock output matches the existing form; the form adds the
    # correct offset for the selected date when saving to the UTC store.
    fmt = '%Y-%m-%d' if all_day else '%Y-%m-%dT%H:%M:%S'
    return {'ok': True, 'parser': 'local', 'notice': ' '.join(notices), 'event': {
        'summary': title[:200], 'dtstart': start.strftime(fmt), 'dtend': end.strftime(fmt),
        'all_day': all_day, 'location': '', 'description': '',
    }}
