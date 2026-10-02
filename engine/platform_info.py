"""Что доступно на текущей ОС — для интерфейса и отказов с понятной причиной.

На Linux пока нет Zapret (WinDivert/winws работают только в Windows; на Linux
нужен другой движок — nfqws), AmneziaWG (на Windows это служба) и встроенного
автообновления (оно ставит MSI). Остальное — подключение через Mihomo, правила,
подписки, смена сервера на лету и резерв — работает одинаково.
"""
from __future__ import annotations

import os

LINUX_UPDATES_MESSAGE = ("На Linux новая версия ставится вручную: скачайте свежий AppImage или пакет "
                         "со страницы релизов на GitHub.")
LINUX_ZAPRET_MESSAGE = "Zapret пока недоступен на Linux."
LINUX_AWG_MESSAGE = ("AmneziaWG пока недоступен на Linux — используйте обычный WireGuard "
                     "или подписку VLESS/Hysteria2.")


def is_windows() -> bool:
    return os.name == "nt"


def features() -> dict:
    windows = is_windows()
    return {
        "os": "windows" if windows else "linux",
        "zapret": windows,
        "amneziawg": windows,
        "updates": windows,
        "glass_blur": windows,
    }
