"""Explicit personal-world configuration without runtime, model or network work."""

import pytest
from test_configuration import configured as configured
from test_configuration import save


def pet(configured):
    configured[1].update(mode="pet", world_dir="personal/world", vault="personal/vault")
    return configured


def test_qualification_remains_default(configured):
    value = save(configured)
    assert value["mode"] == "qualification"
    assert "world_dir" not in value and "vault" not in value


def test_pet_paths_are_explicit_relative_and_loading_creates_nothing(configured, tmp_path):
    value = save(pet(configured))
    assert value["mode"] == "pet" and value["brain"] == "hermes"
    assert value["world_dir"] == tmp_path / "personal/world"
    assert value["vault"] == tmp_path / "personal/vault"
    assert value["initiative"] is None
    assert not (tmp_path / "personal").exists()


@pytest.mark.parametrize("field", ["world_dir", "vault"])
def test_pet_requires_both_personal_paths(configured, field):
    pet(configured)[1].pop(field)
    with pytest.raises(ValueError):
        save(configured)


@pytest.mark.parametrize("mode", [None, True, 1, [], {}, "demo"])
def test_invalid_mode_is_rejected(configured, mode):
    configured[1]["mode"] = mode
    with pytest.raises(ValueError):
        save(configured)


@pytest.mark.parametrize("field", ["world_dir", "vault", "initiative"])
def test_personal_configuration_is_not_accepted_in_qualification(configured, field):
    configured[1][field] = "personal"
    with pytest.raises(ValueError):
        save(configured)


def test_pet_refuses_direct_backend(configured):
    pet(configured)[1]["brain"] = "direct"
    with pytest.raises(ValueError, match="Hermes"):
        save(configured)


def test_pet_refuses_resume_world_alias(configured, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "world.sqlite3").write_bytes(b"not opened")
    pet(configured)[1]["resume_world"] = "old"
    with pytest.raises(ValueError, match="world_dir"):
        save(configured)


@pytest.mark.parametrize("vault", ["personal/world", "personal/world/vault", "personal"])
def test_world_and_vault_cannot_overlap(configured, vault):
    pet(configured)[1]["vault"] = vault
    with pytest.raises(ValueError, match="separate"):
        save(configured)


@pytest.mark.parametrize("field", ["world_dir", "vault"])
@pytest.mark.parametrize("value", [None, True, 1, [], " ", "bad\x00path", "avatar.vrm"])
def test_personal_path_validation(configured, field, value):
    pet(configured)[1][field] = value
    with pytest.raises(ValueError):
        save(configured)


@pytest.mark.parametrize("interval", [None, 1, 15.5])
def test_optional_initial_initiative_is_explicit(configured, interval):
    pet(configured)[1]["initiative"] = {"budget": 8, "interval": interval}
    assert save(configured)["initiative"] == {"budget": 8, "interval": interval}


@pytest.mark.parametrize(
    "value",
    [
        [],
        True,
        {},
        {"budget": 2},
        {"budget": 2, "interval": 5, "paused": False},
        {"budget": True, "interval": 5},
        {"budget": 0, "interval": 5},
        {"budget": 1001, "interval": 5},
        {"budget": 2, "interval": True},
        {"budget": 2, "interval": 0},
        {"budget": 2, "interval": float("nan")},
        {"budget": 2, "interval": float("inf")},
    ],
)
def test_invalid_initial_initiative_is_rejected_without_creation(configured, value, tmp_path):
    pet(configured)[1]["initiative"] = value
    with pytest.raises(ValueError):
        save(configured)
    assert not (tmp_path / "personal").exists()
