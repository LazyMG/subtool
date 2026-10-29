"""시각 표기 변환."""

import re


def parse_time(text: str) -> float:
    """'90', '1:30', '1:30.5', '01:02:03,250' → 초"""
    text = text.strip().replace(",", ".")
    if not text:
        raise ValueError("빈 시각")
    parts = text.split(":")
    if len(parts) > 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise ValueError(f"시각 형식이 잘못됨: {text!r}")
    value = 0.0
    for p in parts:
        value = value * 60 + float(p)
    return value


def srt_time(sec: float) -> str:
    ms = max(0, round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def vtt_time(sec: float) -> str:
    return srt_time(sec).replace(",", ".")


def short_time(sec: float) -> str:
    """mm:ss 또는 h:mm:ss"""
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
