"""
받아쓰기 엔진.
- mlx: Apple Silicon Mac 전용 (mlx-whisper)
- faster: Windows / Linux / Intel Mac (faster-whisper, NVIDIA GPU 있으면 사용, 없으면 CPU)

둘 다 같은 형식의 단어 목록을 돌려준다: [{'w': ' Hello', 's': 1.2, 'e': 1.5, 'p': 0.98}]
"""

import inspect
import os
import platform
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows 모델 캐시 경고 숨김 (동작에는 영향 없음)

DEFAULT_MODELS = {
    "mlx": "mlx-community/whisper-large-v3-turbo",
    "faster": "large-v3-turbo",
}


class EngineError(RuntimeError):
    pass


def auto_engine():
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mlx"
    return "faster"


def transcribe(audio_path, *, engine, model, language, initial_prompt, progress):
    """progress(0~1 비율)를 호출하며 단어 목록을 돌려준다."""
    if engine == "mlx":
        return _mlx(audio_path, model, language, initial_prompt, progress)
    if engine == "faster":
        return _faster(audio_path, model, language, initial_prompt, progress)
    raise EngineError(f"알 수 없는 엔진: {engine}")


def _word(text, start, end, prob):
    return {"w": text, "s": round(float(start), 3), "e": round(float(end), 3), "p": round(float(prob), 3)}


def _mlx(audio_path, model, language, prompt, progress):
    try:
        import mlx_whisper
    except ImportError:
        raise EngineError("mlx-whisper가 설치되어 있지 않습니다: pip install -r requirements-mac.txt")
    kwargs = {
        "path_or_hf_repo": model,
        "language": language,
        "initial_prompt": prompt,
        "word_timestamps": True,
        "condition_on_previous_text": False,  # 같은 문장이 반복되는 환각 줄이기
        "verbose": None,
    }
    params = inspect.signature(mlx_whisper.transcribe).parameters
    if "hallucination_silence_threshold" in params:
        kwargs["hallucination_silence_threshold"] = 2.0  # 긴 무음 구간의 환각 건너뛰기
    result = mlx_whisper.transcribe(str(audio_path), **kwargs)
    progress(1.0)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append(_word(w["word"], w["start"], w["end"], w.get("probability", 0)))
    return words


def _faster(audio_path, model, language, prompt, progress):
    try:
        from faster_whisper import WhisperModel
        import ctranslate2
    except ImportError:
        raise EngineError("faster-whisper가 설치되어 있지 않습니다: pip install -r requirements.txt")

    def run(device, compute_type):
        m = WhisperModel(model, device=device, compute_type=compute_type)
        segments, info = m.transcribe(
            str(audio_path), language=language, initial_prompt=prompt, word_timestamps=True,
            vad_filter=True, condition_on_previous_text=False,
        )
        words = []
        total = info.duration or 1.0
        for seg in segments:
            for w in seg.words or []:
                words.append(_word(w.word, w.start, w.end, w.probability))
            progress(min(1.0, seg.end / total))
        return words

    if ctranslate2.get_cuda_device_count() > 0:
        try:
            return run("cuda", "float16")
        except Exception as e:  # CUDA 라이브러리(cuBLAS/cuDNN)가 없으면 CPU로
            print(f"GPU 사용 실패, CPU로 진행: {str(e)[:200]}", flush=True)
    return run("cpu", "int8")
