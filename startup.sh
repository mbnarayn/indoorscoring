#!/bin/bash
# App Service startup: installs dependencies when the platform build step did not, then starts the API.
set -e
cd "$(dirname "$0")"

DEPS_DIR=/home/site/deps
HASH_FILE="$DEPS_DIR/.requirements.sha256"
REQ_HASH=$(sha256sum requirements.txt | cut -d' ' -f1)

if [ ! -f "$HASH_FILE" ] || [ "$(cat "$HASH_FILE")" != "$REQ_HASH" ]; then
  echo "Installing Python dependencies into $DEPS_DIR ..."
  rm -rf "$DEPS_DIR"
  python -m pip install --no-cache-dir --target "$DEPS_DIR" -r requirements.txt
  echo "$REQ_HASH" > "$HASH_FILE"
fi

export PYTHONPATH="$DEPS_DIR:$PYTHONPATH"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
