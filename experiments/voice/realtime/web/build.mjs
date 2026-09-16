import { build } from "../../../../web/avatar/node_modules/esbuild/lib/main.js";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL(".", import.meta.url));
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
