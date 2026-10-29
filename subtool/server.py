"""웹 화면용 API 서버 (FastAPI). 127.0.0.1에서만 접속을 받는다."""

import json
import mimetypes
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import cli, document, engines, glossary
from .jobs import JobQueue, python_argv
from .osutil import IS_MAC, config_dir, display_command, pick_file

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATE_FILE = config_dir() / "state.json"

app = FastAPI(title="subtool")
queue = JobQueue()
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("video/webm", ".webm")


# ---------------------------------------------------------------- 상태 (영상 목록)

def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"videos": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def registered(path: str) -> Path:
    """등록된 영상만 다룬다 (임의 파일 접근 방지)."""
    p = str(Path(path).resolve())
    if p not in load_state()["videos"]:
        raise HTTPException(404, "등록되지 않은 영상입니다.")
    return Path(p)


def video_status(p: Path):
    job = queue.active_for(str(p))
    if job:
        return {"status": "running" if job.status == "running" else "queued", "progress": job.progress, "message": job.message}
    if not p.exists():
        return {"status": "missing"}
    doc_file = document.doc_path(p)
    if not doc_file.exists() and not document.srt_path(p).exists():
        return {"status": "new"}
    status = "generated"
    try:
        status = json.loads(doc_file.read_text(encoding="utf-8")).get("status", "generated")
    except (OSError, json.JSONDecodeError):
        pass
    if status == "synced" and p.with_suffix(".txt").exists():
        status = "exported"
    return {"status": status}


# ---------------------------------------------------------------- 기본

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/api/info")
def info():
    eng = engines.auto_engine()
    return {
        "platform": "mac" if IS_MAC else "other",
        "engine": eng,
        "default_models": engines.DEFAULT_MODELS,
        "ffsubsync": shutil.which("ffsubsync") is not None,
        "base_glossary": str(config_dir() / "glossary_en.csv"),
    }


@app.post("/api/pick")
def pick(body: dict):
    path = pick_file(body.get("prompt") or "파일 선택")
    return {"path": path}


# ---------------------------------------------------------------- 영상 목록

@app.get("/api/videos")
def videos():
    out = []
    for v in load_state()["videos"]:
        p = Path(v)
        out.append({"path": v, "name": p.name, **video_status(p)})
    return out


@app.post("/api/videos")
def add_video(body: dict):
    p = Path(body.get("path", "")).expanduser()
    if not p.is_file():
        raise HTTPException(400, f"파일이 없습니다: {p}")
    p = str(p.resolve())
    state = load_state()
    if p not in state["videos"]:
        state["videos"].insert(0, p)
        save_state(state)
    return {"path": p}


@app.delete("/api/videos")
def remove_video(path: str):
    state = load_state()
    p = str(Path(path).resolve())
    state["videos"] = [v for v in state["videos"] if v != p]
    save_state(state)
    return {"ok": True}


@app.get("/api/series-glossary")
def series_glossary(path: str):
    p = registered(path)
    files = glossary.default_files(p)
    return {"files": [{"path": str(f), "exists": f.exists()} for f in files]}


# ---------------------------------------------------------------- 영상 스트리밍 (Range 지원)

@app.get("/api/media")
def media_file(path: str, request: Request):
    p = registered(path)
    size = p.stat().st_size
    ctype = mimetypes.guess_type(p.name)[0] or "video/mp4"
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(p, media_type=ctype, headers={"Accept-Ranges": "bytes"})
    try:
        units, spec = rng.split("=", 1)
        start_s, end_s = spec.split(",")[0].split("-")
        start = int(start_s) if start_s else max(0, size - int(end_s))
        end = int(end_s) if end_s and start_s else size - 1
    except ValueError:
        raise HTTPException(416, "잘못된 Range")
    end = min(end, size - 1)
    if start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    def body(chunk=1024 * 1024):
        with open(p, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = f.read(min(chunk, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(body(), status_code=206, media_type=ctype, headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(end - start + 1),
    })


# ---------------------------------------------------------------- 명령어 생성·실행

def _opts(body):
    opts = dict(body)
    opts["video"] = str(registered(body.get("video", "")))
    opts["glossary"] = [g for g in (body.get("glossary") or []) if g]
    return opts


@app.post("/api/command")
def command(body: dict):
    argv = cli.transcribe_argv(_opts(body))
    return {"argv": argv, "display": display_command(argv)}


@app.post("/api/run")
def run(body: dict):
    opts = _opts(body)
    if queue.active_for(opts["video"]):
        raise HTTPException(409, "이 영상은 이미 작업 중입니다.")
    argv = cli.transcribe_argv(opts)
    job = queue.submit(opts["video"], "받아쓰기", python_argv(argv))
    return job.to_dict()


@app.post("/api/sync-auto")
def sync_auto(body: dict):
    p = str(registered(body.get("path", "")))
    if queue.active_for(p):
        raise HTTPException(409, "이 영상은 이미 작업 중입니다.")
    job = queue.submit(p, "자동 맞춤", python_argv(["python", "-m", "subtool", "sync", p, "--auto"]))
    return job.to_dict()


@app.get("/api/jobs")
def jobs():
    return queue.list()


# ---------------------------------------------------------------- 자막 문서

@app.get("/api/doc")
def get_doc(path: str):
    p = registered(path)
    doc = document.load(p)
    a = document.autosave_path(p)
    autosave = None
    if a.exists():
        d = document.doc_path(p)
        if not d.exists() or a.stat().st_mtime > d.stat().st_mtime:
            autosave = json.loads(a.read_text(encoding="utf-8"))
    return {"doc": doc, "autosave": autosave}


@app.put("/api/doc")
def put_doc(path: str, doc: dict):
    p = registered(path)
    if queue.active_for(str(p)):
        raise HTTPException(409, "작업 중에는 저장할 수 없습니다.")
    document.save(p, doc)
    return {"ok": True, "srt": str(document.srt_path(p))}


@app.put("/api/autosave")
def put_autosave(path: str, doc: dict):
    p = registered(path)
    document.autosave_path(p).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@app.delete("/api/autosave")
def delete_autosave(path: str):
    a = document.autosave_path(registered(path))
    if a.exists():
        a.unlink()
    return {"ok": True}


@app.post("/api/export")
def export(body: dict):
    p = registered(body.get("path", ""))
    doc = document.load(p)
    if doc is None:
        raise HTTPException(400, "자막 문서가 없습니다.")
    try:
        files = cli.export(p, doc, body.get("formats") or ["txt"], force=bool(body.get("force")))
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"files": [str(f) for f in files]}
