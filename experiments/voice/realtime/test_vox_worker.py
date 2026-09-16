"""CPU protocol checks with mocked Torch/VoxCPM; no model import or GPU work."""

import base64
import hashlib
import importlib.util
import io
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest


@pytest.fixture
def worker(monkeypatch):
    # The executable redirects stdout for model logs; isolate that import here.
    spec = importlib.util.spec_from_file_location(
        "vox_worker_test", Path(__file__).with_name("vox_worker.py")
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    with patch.dict("os.environ"), patch.object(sys, "stdout", io.TextIOWrapper(io.BytesIO())):
        spec.loader.exec_module(module)
    events = []
    module.emit = lambda event, **fields: events.append({"event": event, **fields})
    module.test_events = events
    return module


def test_validation_precedes_queue_and_allows_same_id_after_rejection(worker):
    worker.handle_command({"op": "speak", "id": "one", "text": "[pause:1s] Bonjour"})
    assert worker.test_events[-1]["code"] == "invalid_speech_text"
    assert not worker.pending and not worker.jobs and not worker.recent_ids
    worker.handle_command(
        {"op": "speak", "id": "one", "text": "[sigh] Bonjour !", "style": "((Warm))"}
    )
    job = worker.pending[0]
    assert (job.id, job.text, job.style) == ("one", "[sigh] Bonjour !", "Warm")


def test_bounded_queue_and_cancellation_are_unchanged(worker):
    for identifier in ("one", "two", "three"):
        worker.handle_command({"op": "speak", "id": identifier, "text": "Bonjour."})
    assert [job.id for job in worker.pending] == ["one", "two"]
    assert worker.test_events[-1]["code"] == "queue_full"
    worker.handle_command({"op": "cancel", "id": "one"})
    assert worker.test_events[-1]["event"] == "cancelled"
    assert [job.id for job in worker.pending] == ["two"]
    worker.handle_command({"op": "speak", "id": "one", "text": "Bonjour."})
    assert worker.test_events[-1]["code"] == "duplicate_id"


class FakeWave:
    def __init__(self):
        self.values = np.array([0.125, -0.25, 0.0], dtype=np.float32)

    def squeeze(self, _axis):
        return self

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.values


@pytest.fixture
def fake_torch(monkeypatch):
    cuda = SimpleNamespace(
        reset_peak_memory_stats=Mock(),
        synchronize=Mock(),
        max_memory_allocated=Mock(return_value=0),
    )
    module = SimpleNamespace(cuda=cuda, inference_mode=nullcontext)
    monkeypatch.setitem(sys.modules, "torch", module)
    return module


def test_exact_generator_contract_and_pcm_survive_preparation(worker, fake_torch):
    closed = []

    def chunks():
        try:
            yield FakeWave(), None, None
        finally:
            closed.append(True)

    generate = Mock(return_value=chunks())
    model = SimpleNamespace(
        tts_model=SimpleNamespace(generate_with_prompt_cache_streaming=generate)
    )
    profile = {"mode": "reference", "ref_audio_feat": object()}
    job = worker.Job("one", "[sigh] C’est déjà fini ?", "(Warm (soft))")
    worker.speak(model, profile, job)
    generate.assert_called_once_with(
        target_text="(Warm soft)[sigh] C’est déjà fini ?",
        prompt_cache=profile,
        cfg_value=2.0,
        inference_timesteps=10,
        min_len=2,
        max_len=282,
        retry_badcase=False,
    )
    assert generate.call_args.kwargs["prompt_cache"] is profile
    assert [event["event"] for event in worker.test_events] == ["started", "pcm", "done"]
    chunk = worker.test_events[1]
    assert chunk["sample_rate"] == 48000 and chunk["samples"] == 3
    np.testing.assert_array_equal(
        np.frombuffer(base64.b64decode(chunk["pcm_f32_b64"]), dtype="<f4"), FakeWave().values
    )
    assert closed == [True]
    fake_torch.cuda.synchronize.assert_called_once()


def test_direct_invalid_job_cannot_reach_generator(worker, fake_torch):
    generate = Mock()
    model = SimpleNamespace(
        tts_model=SimpleNamespace(generate_with_prompt_cache_streaming=generate)
    )
    worker.speak(model, {}, worker.Job("bad", "<break/> Bonjour", ""))
    generate.assert_not_called()
    assert worker.test_events[-1]["event"] == "error"
    assert worker.test_events[-1]["code"] == "generation_failed"
    assert not any(event["event"] == "pcm" for event in worker.test_events)


def test_cancelled_job_emits_no_pcm_and_closes_generator(worker, fake_torch):
    generator = Mock()
    generate = Mock(return_value=generator)
    model = SimpleNamespace(
        tts_model=SimpleNamespace(generate_with_prompt_cache_streaming=generate)
    )
    job = worker.Job("cancelled", "[sigh] Bonjour.", "Warm")
    job.cancel.set()
    worker.speak(model, {}, job)
    generator.close.assert_called_once()
    assert [event["event"] for event in worker.test_events] == ["started", "cancelled"]


def test_cancel_during_generation_discards_returned_chunk_on_owner_thread(worker, fake_torch):
    owner = threading.get_ident()
    closed = []
    job = worker.Job("interrupted", "Bonjour.", "Warm")
    job.state = "active"
    worker.jobs[job.id] = job

    def chunks():
        try:
            assert threading.get_ident() == owner
            # Simulate the stdin reader cancelling while the model is in next().
            command_thread = threading.Thread(
                target=worker.handle_command, args=({"op": "cancel", "id": job.id},)
            )
            command_thread.start()
            command_thread.join(timeout=2)
            assert not command_thread.is_alive()
            yield FakeWave(), None, None
        finally:
            closed.append(threading.get_ident())

    model = SimpleNamespace(
        tts_model=SimpleNamespace(generate_with_prompt_cache_streaming=Mock(return_value=chunks()))
    )
    worker.speak(model, {}, job)
    assert [event["event"] for event in worker.test_events] == ["started", "cancelled"]
    assert closed == [owner]


@pytest.mark.parametrize("missing", ["--model-path", "--reference-path", "--reference-sha256"])
def test_cli_requires_explicit_paths_and_reference_digest(worker, missing):
    fields = {
        "--model-path": "model",
        "--reference-path": "reference.pt",
        "--reference-sha256": "ab" * 32,
    }
    args = [part for flag, value in fields.items() if flag != missing for part in (flag, value)]
    with pytest.raises(SystemExit) as error:
        worker.parse_args(args)
    assert error.value.code == 2


def test_cli_preserves_paths_and_normalizes_only_digest_case(worker, tmp_path):
    model, reference, cache = tmp_path / "model", tmp_path / "reference.pt", tmp_path / "cache"
    args = worker.parse_args(
        [
            "--model-path",
            str(model),
            "--reference-path",
            str(reference),
            "--reference-sha256",
            "AB" * 32,
            "--cache-dir",
            str(cache),
        ]
    )
    assert (args.model_path, args.reference_path, args.cache_dir) == (model, reference, cache)
    assert args.reference_sha256 == "ab" * 32


@pytest.mark.parametrize("digest", ["", "a" * 63, "g" * 64, "a" * 65])
def test_cli_rejects_invalid_reference_digest(worker, digest):
    with pytest.raises(SystemExit) as error:
        worker.parse_args(
            [
                "--model-path",
                "model",
                "--reference-path",
                "reference.pt",
                "--reference-sha256",
                digest,
            ]
        )
    assert error.value.code == 2


@pytest.fixture
def fake_engine(worker, fake_torch, monkeypatch, tmp_path):
    """A synthetic feature cache and fake engine, never the user's voice."""
    model_path = tmp_path / "model"
    model_path.mkdir()
    reference_path = tmp_path / "reference.pt"
    reference_path.write_bytes(b"synthetic placeholder; torch.load is mocked")
    features = np.array([[0.125, -0.25, 0.5]], dtype=np.float32)
    feature = SimpleNamespace(contiguous=lambda: SimpleNamespace(numpy=lambda: features))
    profile = {"mode": "reference", "ref_audio_feat": feature}
    digest = hashlib.sha256(features.tobytes()).hexdigest()
    fake_torch.load = Mock(return_value=profile)
    fake_torch.set_num_threads = Mock()
    compiler = SimpleNamespace(_torchdynamo_orig_callable=object())
    tts = SimpleNamespace(
        sample_rate=48000,
        base_lm=SimpleNamespace(forward_step=compiler),
        residual_lm=SimpleNamespace(forward_step=compiler),
        feat_encoder=SimpleNamespace(_orig_mod=object()),
        feat_decoder=SimpleNamespace(estimator=SimpleNamespace(_orig_mod=object())),
        optimize=Mock(),
        generate_with_prompt_cache_streaming=Mock(
            return_value=Mock(__iter__=lambda self: iter(()))
        ),
    )
    model = SimpleNamespace(tts_model=tts)
    loader = Mock(return_value=model)
    monkeypatch.setitem(
        sys.modules, "voxcpm", SimpleNamespace(VoxCPM=SimpleNamespace(from_pretrained=loader))
    )
    monkeypatch.setattr(worker.importlib.metadata, "version", lambda _name: "2.0.3")
    return SimpleNamespace(
        model_path=model_path,
        reference_path=reference_path,
        digest=digest,
        profile=profile,
        model=model,
        loader=loader,
    )


def test_reference_hash_mismatch_rejects_before_model_loading(worker, fake_engine):
    with pytest.raises(RuntimeError, match="supplied reference SHA-256"):
        worker.load_engine(fake_engine.model_path, fake_engine.reference_path, "0" * 64)
    fake_engine.loader.assert_not_called()


def test_non_reference_profile_rejects_before_model_loading(worker, fake_engine):
    fake_engine.profile["mode"] = "clone"
    with pytest.raises(RuntimeError, match="isolated-reference"):
        worker.load_engine(fake_engine.model_path, fake_engine.reference_path, fake_engine.digest)
    fake_engine.loader.assert_not_called()


def test_loading_uses_supplied_paths_and_keeps_official_optimization(
    worker, fake_engine, fake_torch, monkeypatch, tmp_path
):
    cache = tmp_path / "compilation"
    # Environment changes from explicit startup stay isolated to this test.
    monkeypatch.setenv("TORCHINDUCTOR_CACHE_DIR", "old-inductor")
    monkeypatch.setenv("TRITON_CACHE_DIR", "old-triton")
    model, profile, metrics = worker.load_engine(
        fake_engine.model_path, fake_engine.reference_path, fake_engine.digest, cache_dir=cache
    )
    assert model is fake_engine.model and profile is fake_engine.profile
    fake_torch.load.assert_called_once_with(
        fake_engine.reference_path, map_location="cpu", weights_only=True
    )
    fake_engine.loader.assert_called_once_with(
        str(fake_engine.model_path),
        load_denoiser=False,
        optimize=False,
        device="cuda",
        local_files_only=True,
    )
    model.tts_model.optimize.assert_called_once()
    model.tts_model.generate_with_prompt_cache_streaming.assert_called_once_with(
        target_text="Vérification technique du flux audio.",
        prompt_cache=profile,
        cfg_value=2.0,
        inference_timesteps=10,
        min_len=2,
        max_len=96,
        retry_badcase=False,
    )
    assert worker.os.environ["TORCHINDUCTOR_CACHE_DIR"] == str(cache / "inductor")
    assert worker.os.environ["TRITON_CACHE_DIR"] == str(cache / "triton")
    assert metrics["profile_tensor_sha256"] == fake_engine.digest
    assert worker.test_events == []  # Warm-up is never emitted as PCM.


def test_no_cache_option_keeps_existing_library_cache_configuration(
    worker, fake_engine, monkeypatch
):
    monkeypatch.setenv("TORCHINDUCTOR_CACHE_DIR", "existing-inductor")
    monkeypatch.setenv("TRITON_CACHE_DIR", "existing-triton")
    worker.load_engine(fake_engine.model_path, fake_engine.reference_path, fake_engine.digest)
    assert worker.os.environ["TORCHINDUCTOR_CACHE_DIR"] == "existing-inductor"
    assert worker.os.environ["TRITON_CACHE_DIR"] == "existing-triton"
