"""
백그라운드 작업 대기열. 웹에서 실행하는 작업도 CLI와 똑같은 명령(python -m subtool ...)을
하위 프로세스로 하나씩 순서대로 실행한다. 브라우저를 닫아도 서버가 살아 있으면 계속 진행된다.
"""

import itertools
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from .osutil import display_command, notify

ROOT = Path(__file__).resolve().parent.parent
_ids = itertools.count(1)


class Job:
    def __init__(self, video, kind, argv):
        self.id = next(_ids)
        self.video = video
        self.kind = kind
        self.argv = argv
        self.status = "queued"   # queued / running / done / failed
        self.progress = 0.0
        self.message = "대기 중"
        self.log = deque(maxlen=200)
        self.created = time.time()
        self.finished = None

    def to_dict(self):
        shown = ["python"] + self.argv[1:]
        return {
            "id": self.id, "video": self.video, "kind": self.kind, "status": self.status,
            "progress": self.progress, "message": self.message, "command": display_command(shown),
            "log": list(self.log)[-30:], "created": self.created, "finished": self.finished,
        }


class JobQueue:
    def __init__(self):
        self.jobs = []
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, video, kind, argv):
        job = Job(video, kind, argv)
        with self.cv:
            self.jobs.append(job)
            self.cv.notify()
        return job

    def list(self):
        with self.lock:
            return [j.to_dict() for j in self.jobs[-50:]]

    def active_for(self, video):
        with self.lock:
            for j in reversed(self.jobs):
                if j.video == video and j.status in ("queued", "running"):
                    return j
        return None

    def _next(self):
        with self.cv:
            while True:
                for j in self.jobs:
                    if j.status == "queued":
                        j.status = "running"
                        return j
                self.cv.wait()

    def _worker(self):
        while True:
            job = self._next()
            self._run(job)

    def _run(self, job):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            p = subprocess.Popen(job.argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 env=env, text=True, encoding="utf-8", errors="replace")
            for line in p.stdout:
                line = line.rstrip()
                if line.startswith("PROGRESS "):
                    parts = line.split(" ", 2)
                    try:
                        job.progress = float(parts[1])
                    except ValueError:
                        pass
                    if len(parts) > 2:
                        job.message = parts[2]
                elif line:
                    job.log.append(line)
            code = p.wait()
        except OSError as e:
            job.log.append(str(e))
            code = -1
        job.finished = time.time()
        name = Path(job.video).name
        if code == 0:
            job.status, job.progress, job.message = "done", 1.0, "완료"
            notify("subtool", f"{name}: {job.kind} 완료")
        else:
            job.status = "failed"
            job.message = job.log[-1] if job.log else f"실패 (종료 코드 {code})"
            notify("subtool", f"{name}: {job.kind} 실패")


def python_argv(argv):
    """표시용 argv(python -m subtool ...)를 실제 실행용(현재 인터프리터)으로 바꾼다."""
    return [sys.executable] + argv[1:]
