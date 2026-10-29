"""
영상별 자막 문서 (<영상>.subtool.json).

타이밍(start, end)은 자막마다 하나, 텍스트는 언어별로 따로 둔다.
    {
      "version": 1,
      "video": "강의1.mp4",
      "duration": 1213.4,
      "status": "generated" | "synced",
      "cues": [{"start": 1.2, "end": 3.4, "text": {"en": "..."}, "words": [{"w": " Hello", "s": 1.2, "e": 1.5, "p": 0.98}]}],
      "history": [{"time": "...", "command": "..."}]
    }
words는 받아쓰기 원본(단어별 시각·확신도)이며 텍스트를 고쳐도 그대로 둔다.
SRT(<영상>.srt)는 이 문서에서 만들어 내는 결과물이다.
"""

import datetime
import json
import os
import shutil
from pathlib import Path

from . import srt

VERSION = 1


def doc_path(video: Path) -> Path:
    return video.with_name(video.name + ".subtool.json")


def autosave_path(video: Path) -> Path:
    return video.with_name(video.name + ".subtool.autosave.json")


def srt_path(video: Path, lang: str = "en") -> Path:
    return video.with_suffix(".srt" if lang == "en" else f".{lang}.srt")


def orig_srt_path(video: Path) -> Path:
    return video.with_suffix(".orig.srt")


def new_doc(video: Path, duration: float) -> dict:
    return {"version": VERSION, "video": video.name, "duration": duration, "status": "generated", "cues": [], "history": []}


def load(video: Path):
    p = doc_path(video)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    s = srt_path(video)
    if s.exists():  # 다른 도구로 만든 SRT만 있는 경우
        doc = new_doc(video, 0.0)
        doc["cues"] = [{"start": c["start"], "end": c["end"], "text": {"en": c["text"]}, "words": []}
                       for c in srt.parse_srt(s.read_text(encoding="utf-8", errors="replace"))]
        return doc
    return None


def _atomic_write(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save(video: Path, doc: dict, langs=("en",)):
    """문서와 SRT를 저장한다. 기존 SRT는 처음 한 번 .orig.srt로 백업한다."""
    doc["cues"].sort(key=lambda c: c["start"])
    s = srt_path(video)
    o = orig_srt_path(video)
    if s.exists() and not o.exists():
        shutil.copy2(s, o)
    _atomic_write(doc_path(video), json.dumps(doc, ensure_ascii=False, indent=1))
    for lang in langs:
        if any(c["text"].get(lang) for c in doc["cues"]):
            _atomic_write(srt_path(video, lang), srt.write_srt(doc["cues"], lang))
    a = autosave_path(video)
    if a.exists():
        a.unlink()


def add_history(doc: dict, command: str):
    doc.setdefault("history", []).append({"time": datetime.datetime.now().isoformat(timespec="seconds"), "command": command})


def overlaps(cues):
    """겹치는 자막 쌍의 앞쪽 인덱스 목록"""
    return [i for i in range(len(cues) - 1) if cues[i]["end"] > cues[i + 1]["start"] + 0.001]
