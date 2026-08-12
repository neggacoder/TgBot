"""Локальная расшифровка аудио и видео через faster-whisper.

Модуль не импортирует faster-whisper при запуске бота: модель тяжёлая и
нужна только когда в служебный чат действительно прислали медиа.  Благодаря
этому отсутствующая зависимость даёт понятную ошибку в ответ на файл, а не
ломает старт всего бота.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional


MODEL_NAME = os.getenv("FASTER_WHISPER_MODEL", "small")
DEVICE = os.getenv("FASTER_WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv(
    "FASTER_WHISPER_COMPUTE_TYPE",
    "int8" if DEVICE == "cpu" else "float16",
)


@dataclass(frozen=True)
class Transcription:
    text: str
    language: Optional[str]


_model = None
_model_lock = threading.Lock()


def _get_model():
    """Создаёт и кэширует модель ровно один раз на процесс."""
    global _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Не установлена библиотека faster-whisper. "
                "Установите зависимости из requirements.txt."
            ) from exc
        _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
        return _model


def transcribe_file(path: str) -> Transcription:
    """Распознаёт дорожку из аудио- или видеофайла.

    faster-whisper декодирует контейнер через PyAV, поэтому для видео не нужен
    отдельный вызов системного ffmpeg.
    """
    model = _get_model()
    # language=None — автоопределение, поэтому одна модель принимает русскую,
    # английскую, украинскую и белорусскую речь (и другие поддерживаемые
    # Whisper языки). task="transcribe" важен: английский текст остаётся
    # английским, а не переводится.
    segments, info = model.transcribe(
        path,
        language=None,
        task="transcribe",
        beam_size=5,
        vad_filter=True,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return Transcription(text=text, language=getattr(info, "language", None))
