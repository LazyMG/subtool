"""자막 → 읽기용 텍스트."""

from .timefmt import short_time

PARAGRAPH_GAP = 2.0     # 자막 사이 공백이 이보다 길면 문단을 나눔
PARAGRAPH_SENTENCES = 5  # 문장이 이만큼 쌓이면 문장 끝에서 문단을 나눔


def paragraphs(cues, lang="en"):
    """[(시작 시각, 문단 텍스트)]"""
    result = []
    cur, cur_start, sentences = [], None, 0
    prev_end = None
    for c in cues:
        text = " ".join(c["text"].get(lang, "").split())
        if not text:
            continue
        if cur and prev_end is not None and c["start"] - prev_end > PARAGRAPH_GAP:
            result.append((cur_start, " ".join(cur)))
            cur, sentences = [], 0
        if not cur:
            cur_start = c["start"]
        cur.append(text)
        prev_end = c["end"]
        if text.endswith((".", "?", "!")):
            sentences += 1
            if sentences >= PARAGRAPH_SENTENCES:
                result.append((cur_start, " ".join(cur)))
                cur, sentences = [], 0
    if cur:
        result.append((cur_start, " ".join(cur)))
    return result


def plain(cues, lang="en"):
    return "\n\n".join(p for _, p in paragraphs(cues, lang)) + "\n"


def timestamped(cues, lang="en"):
    return "\n\n".join(f"[{short_time(t)}] {p}" for t, p in paragraphs(cues, lang)) + "\n"
