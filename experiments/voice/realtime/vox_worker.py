"""Local resident VoxCPM2 worker. Stdout is exclusively the JSONL protocol."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import math
import os
import re
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from speech_text import MAX_STYLE_CHARS, MAX_TEXT_CHARS, prepare_speech_text

PROTOCOL_OUT = sys.stdout.buffer
sys.stdout = sys.stderr  # Includes import, loader and compiler diagnostics.
MODEL_REVISION = "32279effe8c19989596f05d353d1447f51d9e915"
MAX_AUDIO_SECONDS = 45.0
MAX_PENDING = 2
MAX_INPUT_BYTES = 16384
MAX_RECENT_IDS = 256
SAMPLE_RATE = 48000

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

out_lock = threading.Lock()
condition = threading.Condition()
pending: deque[Job] = deque()
jobs: dict[str, Job] = {}
recent_ids: deque[str] = deque(maxlen=MAX_RECENT_IDS)
stopping = threading.Event()


@dataclass
class Job:
    id: str
    text: str
    style: str
    submitted: float = field(default_factory=time.perf_counter)
    cancel: threading.Event = field(default_factory=threading.Event)
    state: str = "queued"


def emit(event: str, **fields) -> None:
    payload = json.dumps({"event": event, **fields}, ensure_ascii=False, allow_nan=False)
    with out_lock:
        PROTOCOL_OUT.write(payload.encode("utf-8") + b"\n")
        PROTOCOL_OUT.flush()


def reject(job_id, code: str, message: str) -> None:
    emit("error", id=job_id, code=code, message=message, request_rejected=True)


def finish(job: Job, event: str, **fields) -> None:
    with condition:
        if job.state == "terminal":
            return
        job.state = "terminal"
        jobs.pop(job.id, None)
        recent_ids.append(job.id)
        # Linearize terminal output before a new command can reuse this id.
        emit(event, id=job.id, **fields)


def cancel_queued(job: Job, reason: str) -> None:
    pending.remove(job)
    job.cancel.set()
    finish(
        job,
        "cancelled",
        metrics={"samples": 0, "audio_seconds": 0.0, "before_started": True, "reason": reason},
    )


def request_shutdown() -> None:
    with condition:
        stopping.set()
        for job in tuple(pending):
            cancel_queued(job, "shutdown")
        for job in tuple(jobs.values()):
            job.cancel.set()
        condition.notify_all()


def valid_id(value) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value.isprintable()
        and bool(value.strip())
    )


def handle_command(command) -> None:
    if not isinstance(command, dict):
        reject(None, "invalid_request", "A JSON object is required.")
        return
    op = command.get("op")
    if op == "shutdown":
        request_shutdown()
        return
    job_id = command.get("id")
    if not valid_id(job_id):
        reject(
            None, "invalid_id", "id must be a nonempty printable string of at most 128 characters."
        )
        return
    if op == "cancel":
        with condition:
            job = jobs.get(job_id)
            if job is None:
                reject(job_id, "unknown_id", "No active or queued request has this id.")
            elif job.state == "queued":
                cancel_queued(job, "cancel")
            else:
                job.cancel.set()
        return
    if op != "speak":
        reject(job_id, "invalid_op", "Expected speak, cancel or shutdown.")
        return
    text = command.get("text")
    style = command.get("style", "")
    if style is None:
        style = ""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        reject(job_id, "invalid_text", "text must contain 1 to 1000 characters.")
        return
    if not isinstance(style, str) or len(style) > MAX_STYLE_CHARS:
        reject(job_id, "invalid_style", "style must be a string of at most 1000 characters.")
        return
    try:
        prepared = prepare_speech_text(text, style)
    except ValueError as exc:
        reject(job_id, "invalid_speech_text", str(exc))
        return
    with condition:
        if stopping.is_set():
            reject(job_id, "shutting_down", "The worker is shutting down.")
        elif job_id in jobs or job_id in recent_ids:
            reject(
                job_id,
                "duplicate_id",
                "Use a new id for each request; the original request is unchanged.",
            )
        elif len(pending) >= MAX_PENDING:
            reject(job_id, "queue_full", "At most two requests may wait behind the active request.")
        else:
            job = Job(job_id, prepared["spoken_text"], prepared["style"])
            jobs[job_id] = job
            pending.append(job)
            condition.notify()


def read_commands() -> None:
    try:
        while not stopping.is_set():
            raw = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
            if not raw:
                request_shutdown()
                return
            if len(raw) > MAX_INPUT_BYTES:
                while raw and not raw.endswith(b"\n"):
                    raw = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
                reject(None, "request_too_large", "JSONL commands must not exceed 16384 bytes.")
                continue
            try:
                command = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                reject(None, "invalid_json", str(exc))
                continue
            handle_command(command)
    except (BrokenPipeError, OSError):
        request_shutdown()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        request_shutdown()


def reference_sha256(value: str) -> str:
    """The digest is of the reference feature tensor bytes, not the .pt file."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise argparse.ArgumentTypeError(
            "Expected the 64 hexadecimal characters of the reference tensor SHA-256."
        )
    return value.lower()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-path",
        type=Path,
        required=True,
        help=f"Local VoxCPM2 snapshot; qualified revision: {MODEL_REVISION}.",
    )
    parser.add_argument(
        "--reference-path",
        type=Path,
        required=True,
        help="Local .pt isolated-reference cache, never a reference WAV.",
    )
    parser.add_argument(
        "--reference-sha256",
        type=reference_sha256,
        required=True,
        help="Expected SHA-256 of ref_audio_feat tensor bytes, not of the .pt file.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional compiler cache root; otherwise retain PyTorch/Triton defaults.",
    )
    return parser.parse_args(argv)


def load_engine(model_path, reference_path, expected_hash, *, cache_dir=None):
    model_path, reference_path = Path(model_path).resolve(), Path(reference_path).resolve()
    expected_hash = reference_sha256(expected_hash)
    if not model_path.is_dir():
        raise FileNotFoundError("The local VoxCPM2 model directory does not exist.")
    if not reference_path.is_file():
        raise FileNotFoundError("The local isolated-reference cache does not exist.")
    if cache_dir is not None:
        cache_dir = Path(cache_dir).resolve()
        os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(cache_dir / "inductor")
        os.environ["TRITON_CACHE_DIR"] = str(cache_dir / "triton")

    import torch
    from voxcpm import VoxCPM

    if importlib.metadata.version("voxcpm") != "2.0.3":
        raise RuntimeError("This worker requires the qualified voxcpm==2.0.3 environment.")
    profile = torch.load(reference_path, map_location="cpu", weights_only=True)
    if profile.get("mode") != "reference":
        raise RuntimeError("Only an isolated-reference profile is accepted.")
    feature = profile["ref_audio_feat"]
    tensor_hash = hashlib.sha256(feature.contiguous().numpy().tobytes()).hexdigest()
    if tensor_hash != expected_hash:
        raise RuntimeError("The voice profile differs from the supplied reference SHA-256.")
    torch.set_num_threads(8)
    start = time.perf_counter()
    model = VoxCPM.from_pretrained(
        str(model_path), load_denoiser=False, optimize=False, device="cuda", local_files_only=True
    )
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - start
    if int(model.tts_model.sample_rate) != SAMPLE_RATE:
        raise RuntimeError("Unexpected output sample rate.")
    model.tts_model.optimize()
    compiled = [
        hasattr(model.tts_model.base_lm.forward_step, "_torchdynamo_orig_callable"),
        hasattr(model.tts_model.residual_lm.forward_step, "_torchdynamo_orig_callable"),
        hasattr(model.tts_model.feat_encoder, "_orig_mod"),
        hasattr(model.tts_model.feat_decoder.estimator, "_orig_mod"),
    ]
    if not all(compiled):
        raise RuntimeError("Official optimization did not activate all four components.")
    # Technical initialization only. It is never sent as PCM or persisted as dialogue.
    warm_started = time.perf_counter()
    generator = model.tts_model.generate_with_prompt_cache_streaming(
        target_text="Vérification technique du flux audio.",
        prompt_cache=profile,
        cfg_value=2.0,
        inference_timesteps=10,
        min_len=2,
        max_len=96,
        retry_badcase=False,
    )
    try:
        with torch.inference_mode():
            for _ in generator:
                pass
    finally:
        generator.close()
    torch.cuda.synchronize()
    return (
        model,
        profile,
        {
            "pid": os.getpid(),
            "voice_profile": "provided-reference",
            "load_seconds": load_seconds,
            "qualified_model_revision": MODEL_REVISION,
            "warmup_seconds": time.perf_counter() - warm_started,
            "profile_tensor_sha256": tensor_hash,
            "max_text_characters": MAX_TEXT_CHARS,
            "max_audio_seconds": MAX_AUDIO_SECONDS,
            "max_pending": MAX_PENDING,
        },
    )


def speak(model, profile, job: Job) -> None:
    import numpy as np
    import torch

    started = time.perf_counter()
    samples = 0
    seq = 0
    first_pcm = None
    generator = None
    outcome = "done"
    error = {}
    limit_samples = int(MAX_AUDIO_SECONDS * SAMPLE_RATE)
    torch.cuda.reset_peak_memory_stats()
    emit("started", id=job.id)
    try:
        # Also validate direct owner-thread calls used by local qualifications.
        prepared = prepare_speech_text(job.text, job.style)
        generator = model.tts_model.generate_with_prompt_cache_streaming(
            target_text=prepared["target_text"],
            prompt_cache=profile,
            cfg_value=2.0,
            inference_timesteps=10,
            min_len=2,
            max_len=math.ceil(MAX_AUDIO_SECONDS / 0.16),
            retry_badcase=False,
        )
        with torch.inference_mode():
            while True:
                if job.cancel.is_set():
                    outcome = "cancelled"
                    break
                try:
                    wav, _, _ = next(generator)
                except StopIteration:
                    if samples == 0:
                        raise RuntimeError("The model ended without producing audio.") from None
                    break
                if job.cancel.is_set():
                    outcome = "cancelled"
                    break
                pcm = wav.squeeze(0).detach().float().cpu().numpy().reshape(-1)
                if not len(pcm):
                    continue
                if not np.isfinite(pcm).all():
                    raise RuntimeError("The model returned non-finite PCM.")
                pcm = pcm[: limit_samples - samples].astype("<f4", copy=False)
                # A command linearized before this lock can suppress this chunk.
                with condition:
                    if job.cancel.is_set():
                        outcome = "cancelled"
                        break
                    elapsed = time.perf_counter() - started
                    if first_pcm is None:
                        first_pcm = elapsed
                    emit(
                        "pcm",
                        id=job.id,
                        seq=seq,
                        sample_rate=SAMPLE_RATE,
                        pcm_f32_b64=base64.b64encode(pcm.tobytes()).decode("ascii"),
                        samples=len(pcm),
                        elapsed_seconds=elapsed,
                    )
                    samples += len(pcm)
                    seq += 1
                if samples >= limit_samples:
                    outcome = "error"
                    error = {
                        "code": "audio_limit",
                        "message": "The 45-second audio limit was reached; "
                        "the utterance is partial.",
                    }
                    break
    except Exception as exc:
        outcome = "error"
        error = {"code": "generation_failed", "message": f"{type(exc).__name__}: {exc}"}
        traceback.print_exc(file=sys.stderr)
    finally:
        try:
            if generator is not None:
                generator.close()  # Same owner thread, after next() has returned.
            torch.cuda.synchronize()
        except Exception as exc:
            outcome = "error"
            error = {"code": "cleanup_failed", "message": f"{type(exc).__name__}: {exc}"}
            stopping.set()  # Never reuse a model whose decoder cleanup failed.
            traceback.print_exc(file=sys.stderr)
        if job.cancel.is_set() and outcome != "error":
            outcome = "cancelled"
        elapsed = time.perf_counter() - started
        finish(
            job,
            outcome,
            **error,
            metrics={
                "samples": samples,
                "chunks": seq,
                "audio_seconds": samples / SAMPLE_RATE,
                "generation_seconds": elapsed,
                "first_pcm_seconds": first_pcm,
                "rtf": elapsed / (samples / SAMPLE_RATE) if samples else None,
                "queued_seconds": started - job.submitted,
                "peak_gpu_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
                "style_requested": bool(job.style),
            },
        )


def main() -> int:
    args = parse_args()
    try:
        model, profile, initialization = load_engine(
            args.model_path,
            args.reference_path,
            args.reference_sha256,
            cache_dir=args.cache_dir,
        )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit("error", id=None, code="startup_failed", message=f"{type(exc).__name__}: {exc}")
        return 1
    emit("ready", sample_rate=SAMPLE_RATE, metrics=initialization)
    threading.Thread(target=read_commands, name="vox-stdin", daemon=True).start()
    try:
        while True:
            with condition:
                condition.wait_for(lambda: bool(pending) or stopping.is_set())
                if stopping.is_set():
                    break
                job = pending.popleft()
                job.state = "active"
            speak(model, profile, job)
    finally:
        request_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
