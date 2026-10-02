#!/bin/bash
# Сборка Sadness VPN для Linux: AppImage, deb, rpm, pacman.
#
# Запускается в Linux (у разработчика — Ubuntu 22.04 в WSL2: сборка на старом
# glibc 2.35 работает и на новых дистрибутивах — Fedora, Arch, Bazzite).
# Нужны: python3.11 + venv с requirements-linux.txt, Node.js 20, rpm, bsdtar, zstd.
#
#   bash tools/build_linux.sh /путь/к/исходникам /путь/к/venv
set -euo pipefail
SRC="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV="${2:-$SRC/../venv}"
WORK=/opt/svpn/build
rsync -a --delete --exclude venv311 --exclude node_modules --exclude dist --exclude build \
      --exclude data --exclude .git --exclude '*.pyc' "$SRC/" "$WORK/"
cd "$WORK"
VERSION=$("$VENV/bin/python" -c 'import json; print(json.load(open("package.json"))["version"])')
echo "== Sadness VPN $VERSION для Linux"

echo "== 1/4 тесты"
"$VENV/bin/python" -m unittest discover -s tests -t . -q

echo "== 2/4 бэкенд (PyInstaller)"
"$VENV/bin/pyinstaller" --noconfirm --log-level WARN --workpath build/pyi-linux \
    --distpath dist/linux-runtime SadnessVPN-linux.spec
RUNTIME=dist/linux-runtime/SadnessVPN
test -x "$RUNTIME/SadnessVPN" && test -x "$RUNTIME/_internal/bin/mihomo"

echo "== 3/4 проверка собранного бэкенда"
DATA=$(mktemp -d)
SADNESS_DATA_DIR="$DATA" XDG_DATA_HOME="$DATA" "$RUNTIME/SadnessVPN" --headless --port 45697 >/tmp/svpn-smoke.log 2>&1 &
PID=$!
for i in $(seq 1 60); do
    curl -s http://127.0.0.1:45697/api/health | grep -q SadnessVPN && break
    sleep 0.5
done
curl -s http://127.0.0.1:45697/api/health | grep -q SadnessVPN || { cat /tmp/svpn-smoke.log; kill $PID; exit 1; }
curl -s http://127.0.0.1:45697/api/diagnostics >/dev/null
kill $PID; wait $PID 2>/dev/null || true
rm -rf "$DATA"
echo "   бэкенд отвечает"

echo "== 4/4 Electron: AppImage, deb, rpm, pacman"
[ -d node_modules/electron ] || npm ci --no-audit --no-fund --loglevel=error
npx electron-builder --linux --x64 --publish never 2>&1 | grep -vE '^\s*(•|$)' || true
ls -la dist/electron-runtime/ | grep -E "SadnessVPN-$VERSION" || { echo "артефакты не собраны"; exit 1; }
sha256sum dist/electron-runtime/SadnessVPN-"$VERSION"-linux-* | sed 's#dist/electron-runtime/##'
