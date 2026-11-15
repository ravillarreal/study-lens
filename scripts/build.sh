#!/usr/bin/env bash
# Arma dist/study-lens: un solo archivo ejecutable (zipapp con shiv) con el programa
# y sus dependencias de Python (ziamath). Usa el python3 del sistema para GTK.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

"$PY" -m pip install -q --target "$STAGE" -r "$ROOT/requirements.txt"
cp "$ROOT"/study_lens.py "$ROOT"/shortcuts.py "$ROOT"/mathrender.py "$ROOT"/hyprsetup.py "$STAGE/"
cp -r "$ROOT/hypr" "$ROOT/.opencode" "$STAGE/"
find "$STAGE" -name '__pycache__' -prune -exec rm -rf {} +

mkdir -p "$ROOT/dist"
"$PY" -m shiv --site-packages "$STAGE" --entry-point study_lens:main \
  --python "/usr/bin/env python3" --compressed --reproducible \
  --output-file "$ROOT/dist/study-lens"
chmod +x "$ROOT/dist/study-lens"
ls -lh "$ROOT/dist/study-lens"
