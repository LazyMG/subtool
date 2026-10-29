"""SRT / VTT 읽기·쓰기. 자막 데이터는 document 모듈의 cue 딕셔너리 형식을 쓴다."""

import re

from .timefmt import parse_time, srt_time, vtt_time

_TIMING = re.compile(r"(\d+:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{1,3})")


def parse_srt(text: str):
    """SRT 문자열 → [{'start', 'end', 'text'}] (번호는 무시하고 순서대로)"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    items = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines[:2]):
            m = _TIMING.search(line)
            if m:
                items.append({
                    "start": parse_time(m.group(1)),
                    "end": parse_time(m.group(2)),
                    "text": "\n".join(lines[i + 1:]).strip(),
                })
                break
    return items


def write_srt(cues, lang: str) -> str:
    out = []
    for n, c in enumerate(cues, 1):
        out.append(f"{n}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text'].get(lang, '')}\n")
    return "\n".join(out)


def write_vtt(cues, lang: str) -> str:
    out = ["WEBVTT\n"]
    for c in cues:
        out.append(f"{vtt_time(c['start'])} --> {vtt_time(c['end'])}\n{c['text'].get(lang, '')}\n")
    return "\n".join(out)
