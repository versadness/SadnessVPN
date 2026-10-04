#!/bin/bash
# Наборы правил Mihomo (.mrs) из MetaCubeX/meta-rules-dat для маршрутов:
# российские сайты напрямую, блокировка рекламы, сервисы «всегда через VPN».
# Кладутся в assets/rules; приложение копирует их ядру при подключении.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/app/src/main/assets/rules"
BASE="https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo"
mkdir -p "$OUT"
for name in category-ru category-gov-ru category-ads-all youtube discord telegram; do
    curl -fsSL --retry 3 -o "$OUT/site-$name.mrs" "$BASE/geosite/$name.mrs"
done
for name in ru telegram; do
    curl -fsSL --retry 3 -o "$OUT/ip-$name.mrs" "$BASE/geoip/$name.mrs"
done
ls -la "$OUT"
