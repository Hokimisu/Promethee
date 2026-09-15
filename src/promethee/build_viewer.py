"""Build the pinned Viser client, including its Windows npm-launch workaround."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    from viser import _client_autobuild as build

    if sys.platform != "win32":
        build.ensure_client_is_built()
        return
    client = Path(build.client_dir).resolve()
    node_dir = client / ".nodeenv" / "Scripts"
    if not node_dir.exists():
        subprocess.run(
            [sys.executable, "-m", "nodeenv", "--node=20.19.0", str(client / ".nodeenv")],
            check=True,
        )
    node = node_dir / "node.exe"
    npm = node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js"
    env = os.environ | {"PATH": str(node_dir) + os.pathsep + os.environ["PATH"]}
    # Upstream launches the extensionless npm shell script on Windows (WinError 193).
    # Invoke its actual JavaScript entry point with Node, without patching site-packages.
    subprocess.run(
        [str(node), str(npm), "install", "--legacy-peer-deps"], cwd=client, env=env, check=True
    )
    subprocess.run(
        [
            str(node),
            str(client / "node_modules/vite/bin/vite.js"),
            "build",
            "--base",
            "./",
            "--outDir",
            str(build.build_dir),
        ],
        cwd=client,
        env=env,
        check=True,
    )
    build._write_last_built_src_hash(build._compute_src_hash(client / "src"))


if __name__ == "__main__":
    main()
