"""Local Gradio endpoint compatible with ARDY's TextEncoderAPI; isolated Python 3.11."""

import argparse
import json
import re
import time
from pathlib import Path

import gradio as gr
import numpy as np
import torch
from llm2vec import LLM2Vec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapters", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9550)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
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
        raise RuntimeError("Encoder identity changed: the prompt formatting would differ.")
    encoder.eval()
    for parameter in encoder.parameters():
        parameter.requires_grad = False
    print(json.dumps({"model_load_seconds": time.perf_counter() - started}), flush=True)

    def encode(text, filename):
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError("Provide between 1 and 1000 characters of motion text.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}\.npy", filename):
            raise ValueError("Invalid embedding filename.")
        target = args.output / filename
        # Reserve the file before expensive inference; do not overwrite another request.
        with target.open("xb") as stream:
            started = time.perf_counter()
            values = encoder.encode([text], batch_size=1, show_progress_bar=False, device="cuda")
            if values.shape != (1, 4096) or not torch.isfinite(values).all():
                raise RuntimeError("Invalid text embedding.")
            np.save(stream, values.float().cpu().numpy())
        print(
            json.dumps(
                {
                    "encode_seconds": time.perf_counter() - started,
                    "text_characters": len(text),
                    "shape": list(values.shape),
                    "gpu_peak_bytes": torch.cuda.max_memory_allocated(),
                }
            ),
            flush=True,
        )
        return gr.DownloadButton(value=str(target.resolve()), visible=True), "", ""

    with gr.Blocks(title="Promethee motion encoder") as demo:
        text = gr.Textbox(label="Motion text")
        filename = gr.Textbox(label="Output filename")
        button = gr.Button("Encode")
        output = gr.DownloadButton()
        status, detail = gr.Markdown(), gr.Markdown()
        button.click(
            encode,
            [text, filename],
            [output, status, detail],
            api_name="DemoWrapper",
            concurrency_limit=1,
        )
    demo.launch(
        server_name="127.0.0.1", server_port=args.port, allowed_paths=[str(args.output.resolve())]
    )


if __name__ == "__main__":
    main()
