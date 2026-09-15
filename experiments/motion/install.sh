#!/usr/bin/env bash
# Ubuntu 22.04 x86_64; install into a NEW directory without changing the CPU package.
set -euo pipefail
root=${1:?Provide a new absolute installation directory}
case "$root" in /*) ;; *) echo 'An absolute directory is required' >&2; exit 2 ;; esac
if test -e "$root"; then echo 'Directory already exists' >&2; exit 2; fi
scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p -- "$root"
git clone https://github.com/nv-tlabs/ardy.git "$root/ardy"
git -C "$root/ardy" checkout --detach 693f74d13b3d04a0a22ce127ee79c929dd89756b
for name in ardy encoder; do
    uv venv "$root/$name-env" --python 3.11.16
    uv pip install --python "$root/$name-env/bin/python" torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cu126
    uv pip install --python "$root/$name-env/bin/python" --no-deps -r "$scripts/$name-requirements.txt"
done
uv pip install --python "$root/ardy-env/bin/python" --no-deps -e "$root/ardy[demo]"
uv pip check --python "$root/ardy-env/bin/python"
uv pip check --python "$root/encoder-env/bin/python"
echo "Installed at $root; prepare weights and start the encoder separately."
