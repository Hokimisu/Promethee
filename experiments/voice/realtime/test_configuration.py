"""No subprocess, GPU or provider is required to validate a launch configuration."""

import json

import pytest
from configuration import load_configuration


@pytest.fixture
def configured(tmp_path):
    for name in ("avatar.vrm", "python.exe"):
        (tmp_path / name).write_text("fixture", encoding="utf-8")
    for name in ("hermes", "auth"):
        (tmp_path / name).mkdir()
    value = {
        "data_dir": "runs",
        "avatar": "avatar.vrm",
        "hermes_python": "python.exe",
        "hermes_root": "hermes",
        "hermes_auth_root": "auth",
        "body": {"ardy_python": "/some/ardy-python", "checkpoint_root": "/some/checkpoint"},
        "voice_command": ["a-python-with-spaces", "worker.py", "--model-path", "/some/model"],
    }
    return tmp_path / "config.json", value


def save(configured):
    path, value = configured
    path.write_text(json.dumps(value), encoding="utf-8")
    return load_configuration(path)


def test_paths_resolve_from_config_and_loading_creates_no_runtime(
    configured, monkeypatch, tmp_path
):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    config = save(configured)
    assert config["avatar"] == tmp_path / "avatar.vrm"
    assert config["data_dir"] == tmp_path / "runs"
    assert not config["data_dir"].exists()
    assert config["model"] == "gpt-5.6-luna"
    assert config["voice_command"] == configured[1]["voice_command"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("voice_command", "python worker.py"),
        ("voice_command", []),
        ("voice_command", ["python", None]),
        ("voice_command", ["python", "bad\x00arg"]),
        ("port", True),
        ("port", 80),
        ("port", 65536),
        ("body", {}),
        ("body", {"ardy_python": "python", "checkpoint_root": "c", "seed": -1}),
        ("body", {"ardy_python": "python", "checkpoint_root": "c", "wsl": 4}),
        ("model", "silent-fallback"),
        ("resident", "true"),
        ("avatar", "missing.vrm"),
        ("secret", "not-supported"),
    ],
)
def test_invalid_configuration_fails_before_launch(configured, key, value):
    configured[1][key] = value
    with pytest.raises(ValueError):
        save(configured)
