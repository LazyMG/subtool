"""단어 단위 타임스탬프로 자막 단위를 다시 나눈다."""

SENTENCE_END = (".", "?", "!")
SOFT_BREAK = (",", ";", ":")
MAX_DURATION = 7.0   # 한 자막 최대 표시 시간(초)
GAP_BREAK = 0.8      # 단어 사이 공백이 이보다 길면 자막을 나눔
MIN_DURATION = 0.7   # 너무 빨리 사라지지 않도록 최소 표시 시간


def _text(words):
    return "".join(w["w"] for w in words).strip()


def _wrap(text, max_chars, max_lines):
    if len(text) <= max_chars or max_lines < 2:
        return text
    mid = len(text) // 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    cut = min(spaces, key=lambda i: abs(i - mid))
    return text[:cut].rstrip() + "\n" + text[cut + 1:].lstrip()


CONJUNCTIONS = {"and", "but", "or", "so", "because", "which", "that", "when", "while", "if", "then", "where", "who"}


def _split_point(cur):
    """현재 자막을 끊을 위치(이 인덱스 단어 뒤에서 끊음). 앞 1/3은 피한다.
    우선순위: 문장부호 → 쉼표류 → 접속사 앞 → 단어 사이 간격이 가장 큰 곳"""
    lo = max(0, len(cur) // 3 - 1)
    candidates = range(len(cur) - 2, lo - 1, -1)
    for marks in (SENTENCE_END, SOFT_BREAK):
        for j in candidates:
            if cur[j]["w"].strip().endswith(marks):
                return j
    conj = [j for j in candidates if cur[j + 1]["w"].strip().lower() in CONJUNCTIONS]
    if conj:  # 여러 개면 가운데에 가까운 것 (양쪽 길이 균형)
        return min(conj, key=lambda j: abs(j - len(cur) / 2))
    if len(cur) >= 2:
        return max(range(lo, len(cur) - 1), key=lambda j: cur[j + 1]["s"] - cur[j]["e"])
    return None


def build_cues(words, max_chars=42, max_lines=2):
    """words: [{'w', 's', 'e', 'p'}] (시간순) → cue 딕셔너리 목록 (text는 'en')"""
    limit = max_chars * max_lines
    groups = []
    cur = []

    for w in words:
        while cur:
            gap = w["s"] - cur[-1]["e"]
            too_long = len(_text(cur + [w])) > limit or (w["e"] - cur[0]["s"]) > MAX_DURATION
            if gap > GAP_BREAK:
                groups.append(cur)
                cur = []
            elif too_long:
                k = _split_point(cur)
                if k is not None:
                    groups.append(cur[:k + 1])
                    cur = cur[k + 1:]
                else:
                    groups.append(cur)
                    cur = []
            else:
                break
        cur.append(w)
        if w["w"].strip().endswith(SENTENCE_END) and len(_text(cur)) >= limit * 0.5:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    cues = [{"start": g[0]["s"], "end": g[-1]["e"], "text": {"en": _wrap(_text(g), max_chars, max_lines)}, "words": g}
            for g in groups if _text(g)]
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        if c["end"] - c["start"] < MIN_DURATION:
            c["end"] = c["start"] + MIN_DURATION
        if nxt is not None and c["end"] > nxt - 0.001:
            c["end"] = max(c["start"] + 0.05, nxt - 0.001)
    return cues
