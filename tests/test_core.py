"""
받아쓰기 모델 없이 도는 핵심 로직 테스트: 시각 변환, 구간, 자막 분할, 용어집, SRT, 텍스트 추출.

    python tests/test_core.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subtool import glossary, ranges, segment, srt, textout  # noqa: E402
from subtool.timefmt import parse_time, srt_time  # noqa: E402

failed = 0


def check(name, cond, detail=""):
    global failed
    print(f"{'OK  ' if cond else 'FAIL'} {name}{'' if cond else ' — ' + str(detail)}")
    failed += not cond


def words_from(text, start=0.0, step=0.3, gap_after=None):
    out, t = [], start
    for i, w in enumerate(text.split()):
        out.append({"w": " " + w, "s": round(t, 3), "e": round(t + step - 0.05, 3), "p": 0.9})
        t += step + (gap_after.get(i, 0) if gap_after else 0)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    check("parse_time m:ss", parse_time("1:30") == 90)
    check("parse_time h:mm:ss,ms", abs(parse_time("01:02:03,250") - 3723.25) < 1e-9)
    check("srt_time", srt_time(3723.25) == "01:02:03,250")

    r = ranges.parse_ranges("0:00-1:30, 3:00-", 600)
    check("구간 파싱 (끝 생략)", r == [(0.0, 90.0), (180.0, 600.0)], r)
    try:
        ranges.parse_ranges("0:00-2:00, 1:00-3:00", 600)
        check("겹치는 구간 거부", False)
    except ValueError:
        check("겹치는 구간 거부", True)
    kept = ranges.keep_inside([{"s": 9.0, "e": 9.4}, {"s": 10.2, "e": 10.6}], 10.0, 20.0)
    check("패딩 구간 밖 단어 제거", len(kept) == 1 and kept[0]["s"] == 10.2)

    long_text = ("This is a fairly long sentence that keeps going without any punctuation "
                 "and it should be split into readable subtitles by the segmenter for us")
    cues = segment.build_cues(words_from(long_text), max_chars=42, max_lines=2)
    check("긴 문장 분할", len(cues) >= 2, len(cues))
    check("자막 길이 제한", all(len(c["text"]["en"].replace("\n", " ")) <= 84 for c in cues),
          [c["text"]["en"] for c in cues])
    check("두 줄 이하", all(c["text"]["en"].count("\n") <= 1 for c in cues))
    check("겹침 없음", all(a["end"] <= b["start"] for a, b in zip(cues, cues[1:])))

    gap_cues = segment.build_cues(words_from("Hello there. General idea", gap_after={1: 2.0}))
    check("긴 공백에서 분할", len(gap_cues) == 2 and gap_cues[0]["text"]["en"] == "Hello there.", [c["text"]["en"] for c in gap_cues])

    with tempfile.TemporaryDirectory() as tmp:
        g = Path(tmp) / "glossary_en.csv"
        g.write_text("term,variants,type,hint,note\nKubernetes,cooper netties|kuber nettis,tool,Y,\nAna,Anna,person,N,\n",
                     encoding="utf-8")
        entries, used = glossary.load([g, Path(tmp) / "missing.csv"])
        check("용어집 로드", len(entries) == 2 and used == [str(g)])
        check("힌트 프롬프트", glossary.initial_prompt(entries) == "Glossary: Kubernetes.")
        reps = glossary.compile_replacements(entries)
        text, n = glossary.apply("We use Cooper  Netties daily. Anna said hi. Annabel too.", reps)
        check("오인식 치환 (대소문자·공백 무시, 단어 경계)", text == "We use Kubernetes daily. Ana said hi. Annabel too." and n == 2, text)

    sample = [{"start": 1.0, "end": 2.5, "text": {"en": "Hello\nworld"}},
              {"start": 3.0, "end": 4.0, "text": {"en": "Second."}}]
    parsed = srt.parse_srt(srt.write_srt(sample, "en"))
    check("SRT 왕복", [(p["start"], p["end"], p["text"]) for p in parsed] == [(1.0, 2.5, "Hello\nworld"), (3.0, 4.0, "Second.")], parsed)
    check("VTT 헤더", srt.write_vtt(sample, "en").startswith("WEBVTT"))

    para_cues = [{"start": 0, "end": 1, "text": {"en": "One."}}, {"start": 1.2, "end": 2, "text": {"en": "Two."}},
                 {"start": 10, "end": 11, "text": {"en": "Three."}}]
    check("문단 나누기 (긴 공백)", textout.plain(para_cues) == "One. Two.\n\nThree.\n", repr(textout.plain(para_cues)))
    check("시각 붙인 텍스트", textout.timestamped(para_cues).startswith("[00:00] One. Two.\n\n[00:10] Three."))

    print()
    print("전체 통과" if not failed else f"실패 {failed}건")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
