"""Local French ASR: bounded PCM16 requests, one CPU transcription at a time.

This worker does not capture a microphone, interrupt playback, or call Hermes.
The owner must fence stale IDs and terminate the worker for active cancellation.
"""

import argparse
import base64
import binascii
import contextlib
import json
import logging
import math
import os
import sys
import time
from pathlib import Path

SAMPLE_RATE = 16000
MAX_AUDIO_BYTES = SAMPLE_RATE * 2 * 12
MAX_ENCODED_BYTES = 4 * ((MAX_AUDIO_BYTES + 2) // 3)
MAX_LINE_BYTES = MAX_ENCODED_BYTES + 2048
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def request_id(value):
    if (
        isinstance(value, str)
        and value.strip()
        and len(value) <= 80
        and not any(ord(char) < 32 for char in value)
    ):
        return value
    return None


def decode_request(request):
    if not isinstance(request, dict) or set(request) != {"op", "id", "pcm16", "sample_rate"}:
        raise ValueError("invalid_request")
    identifier = request_id(request["id"])
    if request["op"] != "transcribe" or identifier is None:
        raise ValueError("invalid_request")
    if type(request["sample_rate"]) is not int or request["sample_rate"] != SAMPLE_RATE:
        raise ValueError("invalid_sample_rate")
    encoded = request["pcm16"]
    if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_ENCODED_BYTES:
        raise ValueError("invalid_audio")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid_audio") from exc
    if not pcm or len(pcm) % 2 or len(pcm) > MAX_AUDIO_BYTES:
        raise ValueError("invalid_audio")
    return identifier, pcm


def transcribe(model, request, *, clock=time.perf_counter):
    identifier, pcm = decode_request(request)
    import numpy as np

    # The wire format is signed little-endian PCM16, never float PCM or WAV bytes.
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    started = clock()
    segments, _info = model.transcribe(
        audio,
        language="fr",
        task="transcribe",
        beam_size=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=True,
    )
    segments = list(segments)  # Faster Whisper performs inference during iteration.
    elapsed = clock() - started
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("invalid_timing")
    if any(not isinstance(segment.text, str) for segment in segments):
        raise ValueError("invalid_transcript")
    text = "".join(segment.text for segment in segments).strip()
    if len(text) > 16000:
        raise ValueError("invalid_transcript")
    seconds = len(pcm) / (SAMPLE_RATE * 2)
    return {
        "event": "transcript",
        "id": identifier,
        "text": text,
        "metrics": {
            "audio_seconds": seconds,
            "transcription_seconds": elapsed,
            "real_time_factor": elapsed / seconds,
            "segment_count": len(segments),
        },
    }


def load_engine(model_path, *, clock=time.perf_counter):
    model_path = Path(model_path).resolve(strict=True)
    if not model_path.is_dir() or any(
        not (model_path / name).is_file() or not (model_path / name).stat().st_size
        for name in MODEL_FILES
    ):
        raise ValueError("incomplete_local_model")
    # No implicit Hub fallback, tokenizer retrieval, telemetry or GPU selection.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    started = clock()
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(model_path),
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
        local_files_only=True,
    )
    elapsed = clock() - started
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("invalid_timing")
    return model, {
        "model_path": str(model_path),
        "sample_rate": SAMPLE_RATE,
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 4,
        "language": "fr",
        "max_audio_seconds": 12,
        "model_load_seconds": elapsed,
    }


def emit(output, event):
    # ASCII JSON survives Windows pipe encodings without changing decoded text.
    output.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n")
    output.flush()


def reject_constant(_value):
    raise ValueError("non_finite_json")


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate_json_key")
        result[name] = value
    return result


def serve(model, source, output, metadata, *, clock=time.perf_counter):
    emit(output, {"event": "ready", "id": None, "metrics": metadata})
    while raw := source.readline(MAX_LINE_BYTES + 1):
        if len(raw) > MAX_LINE_BYTES:
            emit(output, {"event": "error", "id": None, "code": "frame_too_large"})
            return 2  # Do not interpret a trailing fragment as another command.
        identifier = None
        try:
            if not raw.endswith(b"\n"):
                raise ValueError("incomplete_frame")
            request = json.loads(
                raw.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_object
            )
            if isinstance(request, dict):
                identifier = request_id(request.get("id"))
            if request == {"op": "shutdown"}:
                return 0
            # Reject malformed PCM before any model invocation.
            decode_request(request)
        except (ValueError, UnicodeError, RecursionError):
            emit(output, {"event": "error", "id": identifier, "code": "invalid_request"})
            continue
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = transcribe(model, request, clock=clock)
        except Exception:
            # Provider exceptions may contain audio/text; never print their payload.
            emit(output, {"event": "error", "id": identifier, "code": "transcription_failed"})
        else:
            emit(output, result)
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    output = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            model, metadata = load_engine(args.model_path)
    except Exception:
        emit(output, {"event": "error", "id": None, "code": "asr_startup_failed"})
        return 2
    return serve(model, sys.stdin.buffer, output, metadata)


if __name__ == "__main__":
    raise SystemExit(main())
