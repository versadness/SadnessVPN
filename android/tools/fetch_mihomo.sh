#!/bin/bash
# Скачивает официальные сборки Mihomo для Linux и кладёт их в jniLibs как libmihomo.so.
#
# Именно Linux, а не Android: Android-сборка при запуске туннеля читает
# /data/system/packages.xml (список приложений), а обычному приложению без root
# это запрещено — туннель не поднимается. Статическая Linux-сборка работает на
# ядре Android так же и туннель от VpnService принимает через file-descriptor.
# Имя lib*.so обязательно: только такие файлы Android распаковывает в каталог
# нативных библиотек, откуда приложению разрешено запускать программы.
set -euo pipefail
VERSION="${1:-v1.19.30}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
declare -A ABI=( [arm64-v8a]=arm64 [armeabi-v7a]=armv7 [x86_64]=amd64-compatible )
for abi in "${!ABI[@]}"; do
    name="mihomo-linux-${ABI[$abi]}-$VERSION.gz"
    gh release download "$VERSION" -R MetaCubeX/mihomo -p "$name" -D "$TMP" --clobber
    mkdir -p "$ROOT/app/src/main/jniLibs/$abi"
    gunzip -c "$TMP/$name" > "$ROOT/app/src/main/jniLibs/$abi/libmihomo.so"
    echo "$abi: $(sha256sum "$ROOT/app/src/main/jniLibs/$abi/libmihomo.so" | cut -c1-16)…"
done
rm -rf "$TMP"
