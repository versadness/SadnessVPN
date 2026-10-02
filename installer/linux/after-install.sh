#!/bin/sh
# Пакеты deb/rpm/pacman: права ядру VPN выдаются при установке.
# Пароль администратора здесь уже спросил пакетный менеджер, поэтому при
# подключении VPN приложение пароль больше не запрашивает (engine/linux_core.py).
CORE="/opt/Sadness VPN/resources/runtime/_internal/bin/mihomo"
if [ -f "$CORE" ]; then
    chmod 0755 "$CORE"
    if command -v setcap >/dev/null 2>&1; then
        setcap cap_net_admin,cap_net_bind_service,cap_net_raw+ep "$CORE" || \
            echo "Sadness VPN: setcap не сработал — при первом подключении приложение спросит пароль" >&2
    else
        echo "Sadness VPN: нет setcap (libcap) — при первом подключении приложение спросит пароль" >&2
    fi
fi
# Значок и ярлык в меню.
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
exit 0
