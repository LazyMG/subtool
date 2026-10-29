"""운영체제별로 다른 부분: 설정 폴더, 파일 선택 창, 알림, 명령어 표기."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


def config_dir() -> Path:
    d = Path.home() / ".subtool"
    d.mkdir(exist_ok=True)
    return d


def _osascript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


_TK_PICKER = r"""
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True)
path = filedialog.askopenfilename(title=sys.argv[1])
sys.stdout.write(path or '')
"""


def pick_file(prompt: str = "파일 선택"):
    """네이티브 파일 선택 창을 띄워 경로를 돌려준다. 취소하면 None."""
    if IS_MAC:
        p = subprocess.run(["osascript", "-e", f"POSIX path of (choose file with prompt {_osascript_str(prompt)})"],
                           capture_output=True, text=True)
        return p.stdout.strip() or None
    if not IS_WINDOWS and shutil.which("zenity"):
        p = subprocess.run(["zenity", "--file-selection", f"--title={prompt}"], capture_output=True, text=True)
        return p.stdout.strip() or None
    p = subprocess.run([sys.executable, "-c", _TK_PICKER, prompt], capture_output=True, text=True, encoding="utf-8")
    path = p.stdout.strip()
    return str(Path(path)) if path else None


def notify(title: str, message: str):
    """작업 완료 알림. macOS 알림 센터, Linux notify-send. Windows는 화면 표시로 대신한다."""
    try:
        if IS_MAC:
            subprocess.run(["osascript", "-e", f"display notification {_osascript_str(message)} with title {_osascript_str(title)}"],
                           capture_output=True, timeout=10)
        elif not IS_WINDOWS and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def display_command(argv) -> str:
    """사용자에게 보여 줄 명령어 문자열 (현재 OS 셸 기준 따옴표)"""
    if IS_WINDOWS:
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)
