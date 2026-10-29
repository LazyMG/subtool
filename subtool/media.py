"""ffmpeg / ffprobe 호출."""

import json
import shutil
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


def require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise MediaError(f"{tool}를 찾을 수 없습니다. ffmpeg를 설치하고 PATH에 추가하세요.")
    return path


def duration(video: Path) -> float:
    p = subprocess.run(
        [require("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
        capture_output=True,
    )
    if p.returncode != 0:
        raise MediaError(f"영상을 읽을 수 없습니다: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
    try:
        return float(json.loads(p.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        raise MediaError("영상 길이를 알 수 없습니다.")


def subtitle_stream_count(video: Path) -> int:
    p = subprocess.run(
        [require("ffprobe"), "-v", "error", "-select_streams", "s", "-show_entries", "stream=index", "-of", "json", str(video)],
        capture_output=True,
    )
    try:
        return len(json.loads(p.stdout).get("streams", []))
    except json.JSONDecodeError:
        return 0


def extract_audio(video: Path, out_wav: Path, start: float, end: float):
    """[start, end] 구간 음성을 16kHz 모노 WAV로 뽑는다."""
    cmd = [require("ffmpeg"), "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(video),
           "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out_wav)]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise MediaError(f"음성 추출 실패: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
