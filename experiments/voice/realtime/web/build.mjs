import { build } from "../../../../web/avatar/node_modules/esbuild/lib/main.js";
import { fileURLToPath } from "node:url";
import { copyFile, mkdir } from "node:fs/promises";
const root = fileURLToPath(new URL(".", import.meta.url));
await mkdir(root + "vad", { recursive: true });
for (const name of ["vad.worklet.bundle.min.js", "silero_vad_v5.onnx"])
    await copyFile(
        root + "node_modules/@ricky0123/vad-web/dist/" + name,
        root + "vad/" + name,
    );
for (const name of [
    "ort-wasm-simd-threaded.mjs",
    "ort-wasm-simd-threaded.wasm",
])
    await copyFile(
        root + "node_modules/onnxruntime-web/dist/" + name,
        root + "vad/" + name,
    );
await build({
    entryPoints: [root + "app.js"],
    outfile: root + "bundle.js",
    bundle: true,
    format: "esm",
    minify: true,
    legalComments: "linked",
    nodePaths: [
        fileURLToPath(
            new URL("../../../../web/avatar/node_modules", import.meta.url),
        ),
    ],
});
