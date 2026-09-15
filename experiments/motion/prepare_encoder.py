"""Download pinned public weights and prepare isolated LLM2Vec adapter copies."""

import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

BASE = "NousResearch/Meta-Llama-3-8B-Instruct"
BASE_REVISION = "53346005fb0ef11d3b6a83b12c895cca40156b6c"
ADAPTERS = {
    "LLM2Vec-Meta-Llama-3-8B-Instruct-mntp": "31474e395ada192e8ed1586db6be79fb3b70c9c0",
    "LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised": "baa8ebf04a1c2500e61288e7dad65e8ae42601a7",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.directory.exists():
        parser.error("Choose a new directory; existing adapters are never overwritten.")
    api = HfApi(token=False)
    source = api.model_info("meta-llama/Meta-Llama-3-8B-Instruct", files_metadata=True)
    mirror = api.model_info(BASE, revision=BASE_REVISION, files_metadata=True)
    originals = {f.rfilename: f for f in source.siblings}
    weights = [f for f in mirror.siblings if f.rfilename.endswith(".safetensors")]
    if len(weights) != 4 or any(f.lfs.sha256 != originals[f.rfilename].lfs.sha256 for f in weights):
        raise RuntimeError("The public weight metadata differs from Meta; inspect before using.")
    snapshot_download(
        BASE,
        revision=BASE_REVISION,
        token=False,
        allow_patterns=["*.safetensors", "*.json", "LICENSE", "USE_POLICY.md", "README.md"],
    )
    args.directory.mkdir(parents=True, exist_ok=False)
    provenance = {
        "base": BASE,
        "revision": BASE_REVISION,
        "adapters": ADAPTERS,
        "weight_sha256": {f.rfilename: f.lfs.sha256 for f in weights},
    }
    for name, revision in ADAPTERS.items():
        cached = snapshot_download(f"McGill-NLP/{name}", revision=revision, token=False)
        destination = args.directory / name
        shutil.copytree(cached, destination)
        path = destination / "adapter_config.json"
        config = json.loads(path.read_text())
        config.update(base_model_name_or_path=BASE, revision=BASE_REVISION)
        path.write_text(json.dumps(config, indent=2))
    (args.directory / "provenance.json").write_text(json.dumps(provenance, indent=2))
    print(args.directory.resolve())


if __name__ == "__main__":
    main()
