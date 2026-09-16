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
    assert config["asr_command"] is None
    assert config["resume_world"] is None


def test_resume_world_is_resolved_from_config_without_opening_or_migrating(configured, tmp_path):
    world = tmp_path / "previous" / "world"
    world.mkdir(parents=True)
    database = world / "world.sqlite3"
    # Configuration validates paths only; BodyAdapter validates the database itself.
    database.write_bytes(b"schema validation belongs to Runtime")
    configured[1]["resume_world"] = "previous/world"
    assert save(configured)["resume_world"] == world
    assert database.read_bytes() == b"schema validation belongs to Runtime"
    assert not (tmp_path / "runs").exists()


def test_explicit_null_resume_keeps_new_world_default(configured):
    configured[1]["resume_world"] = None
    assert save(configured)["resume_world"] is None


@pytest.mark.parametrize("kind", ["missing", "directory_without_database", "database_directory"])
def test_resume_world_requires_an_existing_database_file(configured, tmp_path, kind):
    world = tmp_path / "old-world"
    if kind != "missing":
        world.mkdir()
    if kind == "database_directory":
        (world / "world.sqlite3").mkdir()
    configured[1]["resume_world"] = str(world)
    with pytest.raises(ValueError, match="world.sqlite3"):
        save(configured)


def test_optional_asr_command_is_an_unmodified_argument_list(configured):
    configured[1]["asr_command"] = ["C:/some path/python.exe", "worker.py", "--model-path", "model"]
    assert save(configured)["asr_command"] == configured[1]["asr_command"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("voice_command", "python worker.py"),
        ("voice_command", []),
        ("voice_command", ["python", None]),
        ("voice_command", ["python", "bad\x00arg"]),
        ("asr_command", "python worker.py"),
        ("asr_command", []),
        ("asr_command", ["python", None]),
        ("asr_command", ["python", " "]),
        ("asr_command", ["python", "bad\x00arg"]),
        ("port", True),
        ("port", 80),
        ("port", 65536),
        ("body", {}),
        ("body", {"ardy_python": "python", "checkpoint_root": "c", "seed": -1}),
        ("body", {"ardy_python": "python", "checkpoint_root": "c", "wsl": 4}),
        ("model", "silent-fallback"),
        ("resident", "true"),
        ("resume_world", True),
        ("resume_world", 123),
        ("resume_world", " "),
        ("resume_world", []),
        ("resume_world", "bad\x00path"),
        ("avatar", "missing.vrm"),
        ("secret", "not-supported"),
    ],
)
def test_invalid_configuration_fails_before_launch(configured, key, value):
    configured[1][key] = value
    with pytest.raises(ValueError):
        save(configured)


def test_direct_harness_needs_no_hermes_installation(configured, tmp_path):
    value = configured[1]
    for name in ("hermes_python", "hermes_root", "hermes_auth_root"):
        value.pop(name)
    (tmp_path / "auth.json").write_text("{}", encoding="utf-8")
    value.update(brain="direct", auth_file="auth.json")
    config = save(configured)
    assert config["brain"] == "direct"
    assert config["auth_file"] == tmp_path / "auth.json"
    assert config["resident"] is True
    assert not any(name.startswith("hermes_") for name in config)
