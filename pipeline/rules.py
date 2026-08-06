"""Parse NYC DOT alternate-side-parking sign_description text into structured schedules."""
import re

DAY_TOKENS = {
    "MONDAY": "MON", "MODAY": "MON", "MON": "MON",
    "TUESDAY": "TUE", "TUES": "TUE", "TUE": "TUE",
    "WEDNESDAY": "WED", "WED": "WED",
    "THURSDAY": "THU", "THURDAY": "THU", "THURS": "THU", "THUR": "THU",
    "FRIDAY": "FRI", "FRI": "FRI",
    "SATURDAY": "SAT", "SAT": "SAT",
    "SUNDAY": "SUN", "SUN": "SUN",
}
DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

DAY_RE = re.compile(r"\b(" + "|".join(DAY_TOKENS.keys()) + r")\b")
RANGE_RE = re.compile(
    r"\b(" + "|".join(DAY_TOKENS.keys()) + r")-(" + "|".join(DAY_TOKENS.keys()) + r")\b"
)
EXCEPT_RE = re.compile(r"EXCEPT\s+(" + "|".join(DAY_TOKENS.keys()) + r")")
TIME_RE = re.compile(
    r"\b(MIDNIGHT|NOON|\d{1,2}(?::\d{2})?\s*(?:[AP]M)?)\s*(?:-|TO)-?\s*"
    r"(MIDNIGHT|NOON|\d{1,2}(?::\d{2})?\s*[AP]M)\b"
)


def _time_to_minutes(tok, fallback_meridiem=None):
    tok = tok.strip()
    if tok == "MIDNIGHT":
        return 0
    if tok == "NOON":
        return 12 * 60
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)?", tok)
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3) or fallback_meridiem
    if ap == "AM":
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return h * 60 + mins


def parse_sign_description(text):
    """Returns {"days": ["MON", ...], "start_min": int, "end_min": int} or None
    if this sign has no day/time info (e.g. a supplementary arrow-only sign)."""
    text = text.upper()
    if "SANITATION" not in text and "BROOM" not in text:
        return None

    days = set()
    range_match = RANGE_RE.search(text)
    if range_match:
        start_idx = DAY_ORDER.index(DAY_TOKENS[range_match.group(1)])
        end_idx = DAY_ORDER.index(DAY_TOKENS[range_match.group(2)])
        days.update(DAY_ORDER[start_idx : end_idx + 1])
        text_for_days = RANGE_RE.sub("", text)
    else:
        text_for_days = text

    for tok in DAY_RE.findall(text_for_days):
        days.add(DAY_TOKENS[tok])

    except_match = EXCEPT_RE.search(text)
    if except_match:
        excluded = DAY_TOKENS[except_match.group(1)]
        days = set(DAY_ORDER) - {excluded}

    time_match = TIME_RE.search(text)
    if not days or not time_match:
        return None

    end_meridiem_match = re.search(r"([AP]M)\s*$", time_match.group(2))
    end_meridiem = end_meridiem_match.group(1) if end_meridiem_match else None
    start_min = _time_to_minutes(time_match.group(1), fallback_meridiem=end_meridiem)
    end_min = _time_to_minutes(time_match.group(2))

    ordered_days = [d for d in DAY_ORDER if d in days]
    return {"days": ordered_days, "start_min": start_min, "end_min": end_min}


def format_time(mins):
    h, m = divmod(mins, 60)
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12
    h12 = 12 if h12 == 0 else h12
    return f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"


def schedule_label(schedule):
    days = "/".join(schedule["days"])
    return f"{days} {format_time(schedule['start_min'])}-{format_time(schedule['end_min'])}"
