"""Build actual ARDY text embeddings once; serve only that cache on CPU.

Run with the existing WSL encoder-env. Build exits and releases Llama before
serve starts. Unknown strings fail; there is no live model or encoding fallback.
"""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prompts():
    source = (ROOT / "src/promethee/kinematic.py").read_text(encoding="utf-8")
    assignments = [
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "POSTURE_TEXT" for t in n.targets)
    ]
    postures = ast.literal_eval(assignments[0].value)
    walk = "A person walks to the target and stops."
    if walk not in source or set(postures) != {"standing", "arms_raised"}:
        raise ValueError("The body prompt catalogue changed; review before encoding.")
    return {
        **postures,
        "move": walk,
        "speaking": "A person stands in place and speaks with natural expressive hand gestures.",
    }


def build(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import numpy as np
    import torch
    from llm2vec import LLM2Vec

    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    torch.cuda.reset_peak_memory_stats()
    started = perf_counter()
    encoder = LLM2Vec.from_pretrained(
        str(args.adapters / "LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"),
        peft_model_name_or_path=str(
            args.adapters / "LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised"
        ),
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        low_cpu_mem_usage=True,
    )
    if encoder.model.config._name_or_path != "meta-llama/Meta-Llama-3-8B-Instruct":
        raise RuntimeError("Encoder identity would change the expected prompt formatting.")
    encoder.eval()
    for parameter in encoder.parameters():
        parameter.requires_grad = False
    torch.cuda.synchronize()
    report = {
        "purpose": "fixed current controller text embeddings; no motion replay",
        "created_unix_seconds": __import__("time").time(),
        "load_seconds": perf_counter() - started,
        "source_sha256": sha(Path(__file__).read_bytes()),
        "kinematic_source_sha256": sha((ROOT / "src/promethee/kinematic.py").read_bytes()),
        "adapters": str(args.adapters),
        "upstream_provenance": json.loads((args.adapters / "provenance.json").read_text()),
        "versions": {
            p: importlib.metadata.version(p)
            for p in ["torch", "llm2vec", "transformers", "peft", "numpy"]
        },
        "entries": [],
    }
    for name, text in prompts().items():
        started = perf_counter()
        with torch.inference_mode():
            values = encoder.encode([text], batch_size=1, show_progress_bar=False, device="cuda")
        torch.cuda.synchronize()
        seconds = perf_counter() - started
        if tuple(values.shape) != (1, 4096) or not torch.isfinite(values).all():
            raise RuntimeError("Invalid text embedding.")
        path = args.output / (name + ".npy")
        with path.open("xb") as stream:
            np.save(stream, values.float().cpu().numpy(), allow_pickle=False)
        entry = {
            "name": name,
            "text": text,
            "text_sha256": sha(text.encode()),
            "file": path.name,
            "sha256": sha(path.read_bytes()),
            "shape": [1, 4096],
            "dtype": "float32",
            "seconds": seconds,
        }
        report["entries"].append(entry)
        print(json.dumps(entry), flush=True)
    report["peak_gpu_allocated_gib"] = torch.cuda.max_memory_allocated() / 2**30
    (args.output / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({"status": "complete", "manifest": str(args.output / "manifest.json")}),
        flush=True,
    )


def serve(args):
    # This process never imports LLM2Vec or loads model weights, even on a miss.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    import gradio as gr
    import numpy as np

    manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
    cache = {}
    for entry in manifest["entries"]:
        if Path(entry["file"]).name != entry["file"]:
            raise ValueError("Cache filename must be a basename.")
        path = (args.output / entry["file"]).resolve()
        if (
            sha(path.read_bytes()) != entry["sha256"]
            or sha(entry["text"].encode()) != entry["text_sha256"]
        ):
            raise ValueError("Embedding cache hash mismatch.")
        values = np.load(path, allow_pickle=False)
        if values.shape != (1, 4096) or values.dtype != np.float32 or not np.isfinite(values).all():
            raise ValueError("Invalid cached embedding.")
        cache[entry["text"]] = path
    if set(cache) != set(prompts().values()):
        raise ValueError("Cache does not match the exact current body prompt catalogue.")

    def encode(text, filename):
        if text not in cache:
            raise gr.Error("Text is outside this qualification's cached controller catalogue.")
        if not isinstance(filename, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}\.npy", filename):
            raise gr.Error("Invalid requested embedding filename.")
        return gr.DownloadButton(value=str(cache[text]), visible=True), "", ""

    with gr.Blocks(title="Promethee cached motion encoder") as demo:
        text = gr.Textbox()
        filename = gr.Textbox()
        button = gr.Button("Read cached embedding")
        result = gr.DownloadButton()
        status, detail = gr.Markdown(), gr.Markdown()
        button.click(
            encode,
            [text, filename],
            [result, status, detail],
            api_name="DemoWrapper",
            concurrency_limit=1,
        )
    print(json.dumps({"pid": os.getpid(), "cache_only": True, "port": args.port}), flush=True)
    demo.launch(
        server_name="127.0.0.1",
        server_port=args.port,
        allowed_paths=[str(args.output.resolve())],
        show_error=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["build", "serve"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9551)
    parser.add_argument("--adapters", type=Path)
    args = parser.parse_args()
    if args.mode == "build" and args.adapters is None:
        parser.error("--adapters is required when building embeddings.")
    (build if args.mode == "build" else serve)(args)
