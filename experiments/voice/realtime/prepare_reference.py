"""Create a local isolated-reference cache from an authorized WAV; no training."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output cache; existing references are never overwritten.")
    if not args.model_path.is_dir() or not args.wav.is_file():
        parser.error("A local model snapshot and reference WAV are required.")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from voxcpm import VoxCPM

    if importlib.metadata.version("voxcpm") != "2.0.3":
        raise RuntimeError("Use the pinned voxcpm==2.0.3 worker environment.")
    model = VoxCPM.from_pretrained(
        str(args.model_path.resolve()),
        load_denoiser=False,
        optimize=False,
        device="cuda",
        local_files_only=True,
    )
    with torch.inference_mode():
        cache = model.tts_model.build_prompt_cache(
            reference_wav_path=str(args.wav.resolve()),
            trim_silence_vad=False,
        )
    if cache["mode"] != "reference":
        raise RuntimeError("Refusing an audio-continuation cache.")
    cache = {
        key: value.detach().cpu() if torch.is_tensor(value) else value
        for key, value in cache.items()
    }
    digest = hashlib.sha256(cache["ref_audio_feat"].contiguous().numpy().tobytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        torch.save(cache, stream)
    print(
        json.dumps(
            {
                "reference_path": str(args.output.resolve()),
                "reference_sha256": digest,
                "scope": "new reference cache; voice quality requires listening",
            }
        )
    )


if __name__ == "__main__":
    main()
