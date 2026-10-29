"""
subtool 명령줄 도구. 웹 화면도 같은 명령을 실행한다.

    python -m subtool transcribe 영상.mp4 [--ranges "0:00-1:30,3:00-19:00"] [--glossary 용어집.csv]
    python -m subtool export 영상.mp4 --format txt,timestamped,srt,vtt,mkv
    python -m subtool sync 영상.mp4 --offset -0.5
    python -m subtool sync 영상.mp4 --auto          # ffsubsync 설치 시
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import document, engines, glossary, media, ranges as rng, segment, srt, textout
from .osutil import display_command


def progress(frac, msg=""):
    print(f"PROGRESS {frac:.3f} {msg}", flush=True)


# ---------------------------------------------------------------- 명령어 조립 (웹 명령어 생성기와 공용)

def transcribe_argv(opts: dict, python="python"):
    argv = [python, "-m", "subtool", "transcribe", opts["video"]]
    if opts.get("ranges"):
        argv += ["--ranges", opts["ranges"]]
    for g in opts.get("glossary") or []:
        argv += ["--glossary", g]
    if opts.get("no_default_glossary"):
        argv.append("--no-default-glossary")
    if opts.get("engine") and opts["engine"] != "auto":
        argv += ["--engine", opts["engine"]]
    if opts.get("model"):
        argv += ["--model", opts["model"]]
    if opts.get("language") and opts["language"] != "en":
        argv += ["--language", opts["language"]]
    if opts.get("max_chars") and int(opts["max_chars"]) != 42:
        argv += ["--max-chars", str(int(opts["max_chars"]))]
    if opts.get("force"):
        argv.append("--force")
    if opts.get("replace"):
        argv.append("--replace")
    return argv


# ---------------------------------------------------------------- transcribe

def cmd_transcribe(args):
    video = Path(args.video).resolve()
    if not video.is_file():
        sys.exit(f"영상 파일이 없습니다: {video}")
    duration = media.duration(video)

    doc_exists = document.doc_path(video).exists()
    doc = document.load(video) if args.ranges else None
    if doc is None:
        if doc_exists and not args.force:
            sys.exit("이미 자막 문서가 있습니다. 처음부터 다시 받아쓰려면 --force (편집한 내용은 사라집니다).\n"
                     "일부 구간만 추가하려면 --ranges 를 지정하세요.")
        doc = document.new_doc(video, duration)
    doc["duration"] = duration

    spans = rng.parse_ranges(args.ranges, duration) if args.ranges else [(0.0, duration)]
    if args.ranges and doc["cues"]:
        hit = [c for c in doc["cues"] if any(c["start"] < e and c["end"] > s for s, e in spans)]
        if hit and not args.replace:
            sys.exit(f"지정한 구간에 이미 자막 {len(hit)}개가 있습니다. 바꾸려면 --replace 를 붙이세요.")
        doc["cues"] = [c for c in doc["cues"] if c not in hit]

    files = ([] if args.no_default_glossary else glossary.default_files(video)) + (args.glossary or [])
    entries, used = glossary.load(files)
    prompt = glossary.initial_prompt(entries)
    reps = glossary.compile_replacements(entries)
    if used:
        print(f"용어집: {', '.join(used)} (용어 {len(entries)}개, 힌트 {'있음' if prompt else '없음'})", flush=True)

    engine = args.engine if args.engine != "auto" else engines.auto_engine()
    model = args.model or engines.DEFAULT_MODELS[engine]
    print(f"엔진: {engine}, 모델: {model}, 구간: {rng.format_ranges(spans)}", flush=True)

    total_len = sum(e - s for s, e in spans) or 1.0
    done_len = 0.0
    new_cues = []
    replaced = 0
    with tempfile.TemporaryDirectory(prefix="subtool-") as tmp:
        for i, (s, e) in enumerate(spans, 1):
            ps, pe = rng.padded(s, e, duration)
            wav = Path(tmp) / f"range{i}.wav"
            label = f"구간 {i}/{len(spans)}"
            progress(done_len / total_len, f"{label} 음성 추출")
            media.extract_audio(video, wav, ps, pe)

            def on_progress(frac, base=done_len, length=e - s, label=label):
                progress((base + frac * length) / total_len, f"{label} 받아쓰기")

            # 구간만 잘라 받아쓰면 앞 문맥이 없어 정확도가 떨어지므로, 구간 직전 자막을 힌트에 붙인다
            context = previous_text(doc["cues"] + new_cues, s) if args.ranges else ""
            range_prompt = " ".join(p for p in (prompt, context) if p) or None
            try:
                words = engines.transcribe(wav, engine=engine, model=model, language=args.language,
                                           initial_prompt=range_prompt, progress=on_progress)
            except engines.EngineError as ex:
                sys.exit(str(ex))
            for w in words:
                w["s"] = round(w["s"] + ps, 3)
                w["e"] = round(w["e"] + ps, 3)
            words = rng.keep_inside(words, s, e)
            cues = segment.build_cues(words, max_chars=args.max_chars, max_lines=args.max_lines)
            for c in cues:
                c["text"]["en"], n = glossary.apply(c["text"]["en"], reps)
                replaced += n
            new_cues += cues
            done_len += e - s

    doc["cues"] = sorted(doc["cues"] + new_cues, key=lambda c: c["start"])
    doc["status"] = "generated"
    document.add_history(doc, display_command(transcribe_argv(vars_to_opts(args))))
    document.save(video, doc)
    progress(1.0, "완료")
    print(f"자막 {len(new_cues)}개 생성 (전체 {len(doc['cues'])}개), 용어집 치환 {replaced}건")
    print(f"저장: {document.srt_path(video)}")


def previous_text(cues, before, limit=200):
    """before 시각 이전 자막의 끝부분 텍스트 (최대 limit자)"""
    text = " ".join(" ".join(c["text"].get("en", "").split()) for c in sorted(cues, key=lambda c: c["start"])
                    if c["end"] <= before + 0.5)
    return text[-limit:].lstrip()


def vars_to_opts(args):
    return {
        "video": str(Path(args.video).resolve()), "ranges": args.ranges, "glossary": args.glossary,
        "no_default_glossary": args.no_default_glossary, "engine": args.engine, "model": args.model,
        "language": args.language, "max_chars": args.max_chars, "force": args.force, "replace": args.replace,
    }


# ---------------------------------------------------------------- export

EXPORT_FORMATS = ("srt", "vtt", "txt", "timestamped", "mkv")


def export(video: Path, doc: dict, formats, lang="en", force=False):
    """반환: 만든 파일 경로 목록"""
    out = []
    cues = doc["cues"]
    for fmt in formats:
        if fmt == "srt":
            p = document.srt_path(video, lang)
            p.write_text(srt.write_srt(cues, lang), encoding="utf-8")
        elif fmt == "vtt":
            p = video.with_suffix(".vtt" if lang == "en" else f".{lang}.vtt")
            p.write_text(srt.write_vtt(cues, lang), encoding="utf-8")
        elif fmt == "txt":
            p = video.with_suffix(".txt" if lang == "en" else f".{lang}.txt")
            p.write_text(textout.plain(cues, lang), encoding="utf-8")
        elif fmt == "timestamped":
            p = video.with_suffix(".timestamped.txt" if lang == "en" else f".{lang}.timestamped.txt")
            p.write_text(textout.timestamped(cues, lang), encoding="utf-8")
        elif fmt == "mkv":
            p = video.with_name(video.stem + ".subtitled.mkv")
            if p.exists() and not force:
                raise FileExistsError(f"이미 있습니다: {p} (덮어쓰려면 --force)")
            n = media.subtitle_stream_count(video)
            with tempfile.TemporaryDirectory(prefix="subtool-") as tmp:
                s = Path(tmp) / "sub.srt"
                s.write_text(srt.write_srt(cues, lang), encoding="utf-8")
                code = {"en": "eng", "ko": "kor"}.get(lang, lang)
                cmd = [media.require("ffmpeg"), "-v", "error", "-y", "-i", str(video), "-i", str(s),
                       "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt",
                       f"-metadata:s:s:{n}", f"language={code}", str(p)]
                r = subprocess.run(cmd, capture_output=True)
                if r.returncode != 0:
                    raise media.MediaError(f"mkv 만들기 실패: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
        else:
            raise ValueError(f"알 수 없는 형식: {fmt}")
        out.append(p)
    return out


def load_or_exit(video: Path):
    doc = document.load(video)
    if doc is None:
        sys.exit("자막 문서가 없습니다. 먼저 transcribe 를 실행하세요.")
    return doc


def cmd_export(args):
    video = Path(args.video).resolve()
    doc = load_or_exit(video)
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    for p in export(video, doc, formats, args.lang, args.force):
        print(f"저장: {p}")


# ---------------------------------------------------------------- sync

def shift(doc, offset):
    for c in doc["cues"]:
        c["start"] = round(max(0.0, c["start"] + offset), 3)
        c["end"] = round(max(c["start"] + 0.05, c["end"] + offset), 3)


def cmd_sync(args):
    video = Path(args.video).resolve()
    doc = load_or_exit(video)
    if args.auto:
        exe = shutil.which("ffsubsync")
        if not exe:
            sys.exit("ffsubsync가 설치되어 있지 않습니다: pip install ffsubsync")
        progress(0.1, "자동 맞춤 중")
        with tempfile.TemporaryDirectory(prefix="subtool-") as tmp:
            src = Path(tmp) / "in.srt"
            dst = Path(tmp) / "out.srt"
            src.write_text(srt.write_srt(doc["cues"], "en"), encoding="utf-8")
            r = subprocess.run([exe, str(video), "-i", str(src), "-o", str(dst)], capture_output=True)
            if r.returncode != 0 or not dst.exists():
                sys.exit(f"ffsubsync 실패: {r.stderr.decode('utf-8', 'replace').strip()[-300:]}")
            synced = srt.parse_srt(dst.read_text(encoding="utf-8", errors="replace"))
        if len(synced) != len(doc["cues"]):
            sys.exit(f"자막 개수가 달라져 반영하지 않습니다 ({len(doc['cues'])} → {len(synced)})")
        for c, s in zip(doc["cues"], synced):
            c["start"], c["end"] = s["start"], s["end"]
        document.add_history(doc, f"sync --auto (ffsubsync)")
    elif args.offset is not None:
        shift(doc, args.offset)
        document.add_history(doc, f"sync --offset {args.offset}")
    else:
        sys.exit("--offset 또는 --auto 를 지정하세요.")
    document.save(video, doc)
    progress(1.0, "완료")
    print(f"저장: {document.srt_path(video)}")


# ---------------------------------------------------------------- main

def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="subtool", description="로컬 영상 자막 도구")
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="영상 → 자막 받아쓰기")
    t.add_argument("video")
    t.add_argument("--ranges", help='받아쓸 구간, 예: "0:00-1:30, 3:00-19:00" (끝 생략 시 영상 끝까지)')
    t.add_argument("--glossary", action="append", help="추가 영문 용어집 CSV (여러 번 지정 가능)")
    t.add_argument("--no-default-glossary", action="store_true", help="기본·시리즈 용어집을 쓰지 않음")
    t.add_argument("--engine", default="auto", choices=["auto", "mlx", "faster"])
    t.add_argument("--model", help="모델 이름 (기본: mlx=whisper-large-v3-turbo, faster=large-v3-turbo)")
    t.add_argument("--language", default="en")
    t.add_argument("--max-chars", type=int, default=42, help="자막 한 줄 최대 글자 수")
    t.add_argument("--max-lines", type=int, default=2)
    t.add_argument("--force", action="store_true", help="기존 자막 문서를 버리고 처음부터")
    t.add_argument("--replace", action="store_true", help="--ranges 구간에 이미 있는 자막을 교체")
    t.set_defaults(func=cmd_transcribe)

    x = sub.add_parser("export", help="자막 내보내기")
    x.add_argument("video")
    x.add_argument("--format", default="txt", help=f"쉼표로 여러 개: {', '.join(EXPORT_FORMATS)}")
    x.add_argument("--lang", default="en")
    x.add_argument("--force", action="store_true", help="mkv가 이미 있으면 덮어쓰기")
    x.set_defaults(func=cmd_export)

    s = sub.add_parser("sync", help="싱크 조정")
    s.add_argument("video")
    s.add_argument("--offset", type=float, help="전체 자막을 초 단위로 이동 (음수 = 앞으로)")
    s.add_argument("--auto", action="store_true", help="ffsubsync로 자동 맞춤")
    s.set_defaults(func=cmd_sync)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except (media.MediaError, ValueError, FileExistsError) as e:
        sys.exit(str(e))
