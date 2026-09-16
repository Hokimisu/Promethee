"""CPU protocol checks; no Faster Whisper installation, model or GPU required."""

import base64
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest


@pytest.fixture
def worker():
    spec = importlib.util.spec_from_file_location(
        "asr_worker_test", Path(__file__).with_name("asr_worker.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(pcm=b"\x00\x80\xff\x7f\x00\x00", **changes):
    return {
        "op": "transcribe",
        "id": "utterance-1",
        "pcm16": base64.b64encode(pcm).decode("ascii"),
        "sample_rate": 16000,
        **changes,
    }


def run(worker, model, frames, **kwargs):
    source = io.BytesIO(
        b"".join(
            frame if isinstance(frame, bytes) else (json.dumps(frame) + "\n").encode()
            for frame in frames
        )
    )
    output = io.StringIO()
    code = worker.serve(model, source, output, {"fake_model": True}, **kwargs)
    return code, [json.loads(line) for line in output.getvalue().splitlines()]


def test_pcm_conversion_french_options_and_generator_timing(worker):
    now = [10.0]

    def segments():
        now[0] = 12.0
        yield SimpleNamespace(text=" Bonjour")
        now[0] = 13.0
        yield SimpleNamespace(text=" Ariane !")

    model = SimpleNamespace(transcribe=Mock(return_value=(segments(), object())))
    result = worker.transcribe(model, request(), clock=lambda: now[0])
    assert result["text"] == "Bonjour Ariane !"
    assert result["id"] == "utterance-1"
    assert result["metrics"]["transcription_seconds"] == 3
    assert result["metrics"]["audio_seconds"] == 3 / 16000
    assert result["metrics"]["segment_count"] == 2
    audio = model.transcribe.call_args.args[0]
    assert audio.dtype == np.float32
    np.testing.assert_array_equal(audio, np.array([-1.0, 32767 / 32768, 0], dtype=np.float32))
    assert model.transcribe.call_args.kwargs == {
        "language": "fr",
        "task": "transcribe",
        "beam_size": 1,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "vad_filter": True,
    }


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {},
        request(op="speak"),
        request(id=""),
        request(id="   "),
        request(id="x" * 81),
        request(id="bad\nid"),
        request(id=1),
        request(sample_rate=24000),
        request(sample_rate=16000.0),
        request(sample_rate=True),
        request(sample_rate=float("nan")),
        request(pcm16=""),
        request(pcm16=None),
        request(pcm16="!!!!"),
        request(pcm16="éééé"),
        request(pcm=b"\x00"),
        request(pcm=b"\x00" * 384002),
        request(extra="unexpected"),
    ],
)
def test_invalid_requests_never_call_model(worker, invalid):
    model = SimpleNamespace(transcribe=Mock())
    with pytest.raises(ValueError):
        worker.transcribe(model, invalid)
    model.transcribe.assert_not_called()


def test_twelve_second_boundary_and_empty_vad_result(worker):
    model = SimpleNamespace(transcribe=Mock(return_value=(iter(()), object())))
    result = worker.transcribe(model, request(pcm=b"\x00" * 384000))
    assert result["text"] == ""  # Silence is not invented speech or a Hermes input.
    assert result["metrics"]["audio_seconds"] == 12
    assert result["metrics"]["segment_count"] == 0


def test_ready_multiple_requests_shutdown_and_eof(worker):
    model = SimpleNamespace(
        transcribe=Mock(side_effect=lambda *_a, **_k: (iter([SimpleNamespace(text=" Oui.")]), None))
    )
    code, events = run(
        worker,
        model,
        [request(id="one"), request(id="two"), {"op": "shutdown"}, request(id="ignored")],
    )
    assert code == 0
    assert [(event["event"], event["id"]) for event in events] == [
        ("ready", None),
        ("transcript", "one"),
        ("transcript", "two"),
    ]
    assert model.transcribe.call_count == 2
    assert run(worker, model, [])[0] == 0


@pytest.mark.parametrize(
    "frame",
    [
        b'{"op":"transcribe","sample_rate":NaN}\n',
        b'{"op":"transcribe","sample_rate":Infinity}\n',
        b'{"op":"shutdown","op":"shutdown"}\n',
        b'{"op":"shutdown","extra":1}\n',
        b'{"op":"shutdown"}',
        b"\xff\n",
        b"not json\n",
    ],
)
def test_strict_framing_errors_do_not_reach_model(worker, frame):
    model = SimpleNamespace(transcribe=Mock())
    code, events = run(worker, model, [frame])
    assert code == 0
    assert events[-1] == {"event": "error", "id": None, "code": "invalid_request"}
    model.transcribe.assert_not_called()


def test_oversized_line_stops_without_parsing_its_tail(worker):
    model = SimpleNamespace(transcribe=Mock())
    code, events = run(worker, model, [b"x" * (worker.MAX_LINE_BYTES + 1), request()])
    assert code == 2
    assert events[-1]["code"] == "frame_too_large"
    model.transcribe.assert_not_called()


def test_generator_failure_returns_correlated_error_without_leaking_audio_or_text(worker, capsys):
    def broken():
        yield SimpleNamespace(text="private transcript")
        raise RuntimeError("private transcript and PCM")

    model = SimpleNamespace(transcribe=Mock(return_value=(broken(), None)))
    _, events = run(worker, model, [request(id="failed"), {"op": "shutdown"}])
    assert events[-1] == {"event": "error", "id": "failed", "code": "transcription_failed"}
    assert "private" not in json.dumps(events)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("text", [None, float("nan"), "x" * 16001])
def test_invalid_provider_text_is_not_emitted(worker, text):
    model = SimpleNamespace(
        transcribe=Mock(return_value=(iter([SimpleNamespace(text=text)]), None))
    )
    _, events = run(worker, model, [request()])
    assert events[-1]["code"] == "transcription_failed"


def test_non_finite_metrics_are_not_emitted(worker):
    model = SimpleNamespace(transcribe=Mock(return_value=(iter(()), None)))
    ticks = iter([0.0, float("nan")])
    _, events = run(worker, model, [request()], clock=lambda: next(ticks))
    assert events[-1]["code"] == "transcription_failed"


@pytest.fixture
def local_model(tmp_path, worker):
    folder = tmp_path / "pinned-snapshot"
    folder.mkdir()
    for name in worker.MODEL_FILES:
        (folder / name).write_bytes(b"fake model file")
    return folder


def test_loading_is_cpu_only_local_only_four_threads(worker, local_model, monkeypatch):
    factory = Mock(return_value=object())
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
    for key in ("HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "TRANSFORMERS_OFFLINE"):
        monkeypatch.setenv(key, "0")
    ticks = iter([2.0, 3.5])
    model, metadata = worker.load_engine(local_model, clock=lambda: next(ticks))
    assert model is factory.return_value
    factory.assert_called_once_with(
        str(local_model.resolve()),
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        num_workers=1,
        local_files_only=True,
    )
    assert metadata["model_load_seconds"] == 1.5
    assert metadata["model_path"] == str(local_model.resolve())
    assert all(
        worker.os.environ[key] == "1"
        for key in ("HF_HUB_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "TRANSFORMERS_OFFLINE")
    )


@pytest.mark.parametrize(
    "missing", [None, "config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
)
def test_incomplete_or_missing_model_cannot_invoke_loader(
    worker, local_model, missing, monkeypatch
):
    factory = Mock()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
    if missing is None:
        path = local_model / "missing"
    else:
        (local_model / missing).unlink()
        path = local_model
    with pytest.raises((ValueError, FileNotFoundError)):
        worker.load_engine(path)
    factory.assert_not_called()


def test_cli_requires_model_path(worker):
    with pytest.raises(SystemExit) as error:
        worker.parse_args([])
    assert error.value.code == 2


def test_cli_startup_failure_is_machine_readable(worker, monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_engine", Mock(side_effect=RuntimeError("private details")))
    assert worker.main(["--model-path", "missing"]) == 2
    output = capsys.readouterr()
    assert json.loads(output.out) == {"event": "error", "id": None, "code": "asr_startup_failed"}
    assert output.err == ""
