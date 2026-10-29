"""받아쓰기 구간 지정: "0:00-1:30, 3:00-19:00", 끝을 비우면 영상 끝까지 ("3:00-")."""

from .timefmt import parse_time, short_time

PAD = 0.5  # 경계에서 첫/끝 단어가 잘리지 않도록 앞뒤로 더 뽑는 길이(초)


def parse_ranges(text: str, duration: float):
    ranges = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            raise ValueError(f"구간은 '시작-끝' 형식이어야 합니다: {part!r}")
        a, b = part.split("-", 1)
        start = parse_time(a)
        end = parse_time(b) if b.strip() else duration
        end = min(end, duration) if duration else end
        if end <= start:
            raise ValueError(f"끝이 시작보다 빠릅니다: {part!r}")
        ranges.append((start, end))
    ranges.sort()
    for (s1, e1), (s2, e2) in zip(ranges, ranges[1:]):
        if s2 < e1:
            raise ValueError(f"구간이 겹칩니다: {short_time(s1)}-{short_time(e1)}, {short_time(s2)}-{short_time(e2)}")
    if not ranges:
        raise ValueError("구간이 비어 있습니다.")
    return ranges


def format_ranges(ranges):
    return ", ".join(f"{short_time(s)}-{short_time(e)}" for s, e in ranges)


def padded(start, end, duration):
    return max(0.0, start - PAD), min(duration, end + PAD) if duration else end + PAD


def keep_inside(words, start, end):
    """패딩 때문에 구간 밖에서 잡힌 단어는 버린다 (단어 중앙 기준)."""
    return [w for w in words if start <= (w["s"] + w["e"]) / 2 <= end]
