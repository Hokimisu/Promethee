"""Explicit machine paths for the experimental launcher; no models start here."""

import json
from pathlib import Path


def load_configuration(path):
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "data_dir",
        "avatar",
        "hermes_python",
        "hermes_root",
        "hermes_auth_root",
        "body",
        "voice_command",
    }
    if not isinstance(value, dict) or not required <= value.keys():
        raise ValueError("Configuration requires explicit body, voice and Hermes paths.")
    if value.keys() - required - {"port", "model", "resident", "asr_command"}:
        raise ValueError("Unknown configuration field.")
    result = dict(value)
    for key in required - {"body", "voice_command"}:
        entry = value[key]
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"Expected a path for {key}.")
        result[key] = (path.parent / entry).resolve()
    for key in ("avatar", "hermes_python"):
        if not result[key].is_file():
            raise ValueError(f"Missing file: {key}.")
    for key in ("hermes_root", "hermes_auth_root"):
        if not result[key].is_dir():
            raise ValueError(f"Missing directory: {key}.")
    command = value["voice_command"]
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) or not item.strip() for item in command)
    ):
        raise ValueError("voice_command must be an argument list, never a shell string.")
    if any("\x00" in item for item in command):
        raise ValueError("Invalid voice command argument.")
    asr = value.get("asr_command")
    if asr is not None and (
        not isinstance(asr, list)
        or not asr
        or any(not isinstance(item, str) or not item.strip() or "\x00" in item for item in asr)
    ):
        raise ValueError("asr_command must be a local argument list, never a shell string.")
    result["asr_command"] = asr
    body = value["body"]
    if (
        not isinstance(body, dict)
        or not {"ardy_python", "checkpoint_root"} <= body.keys()
        or body.keys() - {"ardy_python", "checkpoint_root", "wsl", "encoder_url", "seed", "node"}
    ):
        raise ValueError("Specify the ARDY interpreter and checkpoint directory.")
    for key in ("ardy_python", "checkpoint_root", "encoder_url", "node"):
        if key in body and (not isinstance(body[key], str) or not body[key].strip()):
            raise ValueError(f"Invalid body.{key}.")
    if body.get("wsl") is not None and (
        not isinstance(body["wsl"], str) or not body["wsl"].strip()
    ):
        raise ValueError("body.wsl must be a distribution name or null.")
    if "seed" in body and (type(body["seed"]) is not int or not 0 <= body["seed"] < 2**31):
        raise ValueError("body.seed must be an integer between 0 and 2**31 - 1.")
    result["port"] = value.get("port", 2392)
    if type(result["port"]) is not int or not 1024 <= result["port"] <= 65535:
        raise ValueError("port must be an integer between 1024 and 65535.")
    result["model"] = value.get("model", "gpt-5.6-luna")
    if result["model"] not in {"gpt-5.6-luna", "gpt-6-astra"}:
        raise ValueError("This experiment qualifies Luna or Astra explicitly.")
    result["resident"] = value.get("resident", False)
    if type(result["resident"]) is not bool:
        raise ValueError("resident must be explicitly true or false.")
    return result
