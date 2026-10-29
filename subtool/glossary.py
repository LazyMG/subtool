"""
영문 용어집 (glossary_en.csv).

열: term(올바른 표기), variants(잘못 인식되는 형태, | 로 구분), type, hint(Y/N), note
- hint=Y 인 term은 받아쓰기 힌트(initial_prompt)로 넣는다.
- variants는 받아쓰기 직후 term으로 자동 치환한다 (대소문자 무시, 단어 경계 기준).

불러오는 순서 (뒤가 앞을 덮어씀):
    1. 기본 용어집: ~/.subtool/glossary_en.csv
    2. 시리즈 용어집: 영상과 같은 폴더의 glossary_en.csv
    3. --glossary 로 지정한 파일들
"""

import csv
import re
from pathlib import Path

from .osutil import config_dir

PROMPT_LIMIT = 600  # initial_prompt 길이 제한(문자). Whisper는 약 224토큰까지만 본다.


def default_files(video: Path):
    return [config_dir() / "glossary_en.csv", video.parent / "glossary_en.csv"]


def load(files):
    entries = {}
    used = []
    for f in files:
        f = Path(f)
        if not f.exists():
            continue
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                term = (row.get("term") or "").strip()
                if not term:
                    continue
                entries[term.lower()] = {
                    "term": term,
                    "variants": [v.strip() for v in (row.get("variants") or "").split("|") if v.strip()],
                    "hint": (row.get("hint") or "").strip().upper() == "Y",
                }
        used.append(str(f))
    return list(entries.values()), used


def initial_prompt(entries):
    terms = []
    length = 0
    for e in entries:
        if e["hint"]:
            if length + len(e["term"]) + 2 > PROMPT_LIMIT:
                break
            terms.append(e["term"])
            length += len(e["term"]) + 2
    return ("Glossary: " + ", ".join(terms) + ".") if terms else None


def _pattern(variant: str):
    words = [re.escape(w) for w in variant.split()]
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", re.IGNORECASE)


def compile_replacements(entries):
    reps = []
    for e in entries:
        for v in e["variants"]:
            reps.append((_pattern(v), e["term"]))
    reps.sort(key=lambda x: -len(x[0].pattern))  # 긴 표현 먼저
    return reps


def apply(text: str, reps):
    """반환: (바뀐 텍스트, 치환 횟수)"""
    total = 0
    for pat, term in reps:
        text, n = pat.subn(term, text)
        total += n
    return text, total
