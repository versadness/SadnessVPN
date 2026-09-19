"""Коллекции профиля: прокси-серверы, WireGuard и маршруты приложений.

Списки groups/wg_groups и словарь apps_config заменяются целиком (импорт
подписки, удаление группы), поэтому обращаться к ним нужно через модуль —
`profile_state.groups`, а не `from ... import groups`. Импортированное имя
осталось бы указывать на прежний объект после замены.

Какой сервер выбран, хранится не здесь, а в app_state.app_settings
(selected_group / selected_index / selected_wg_*): это пользовательская
настройка, которая переживает перезапуск.
"""
import hashlib
import json
import uuid as _uuid_mod

from engine.apps import load_apps
from engine.storage import load_groups, save_groups
from engine.wg_storage import load_wg_groups, save_wg_groups


def ensure_server_ids(groups: list) -> bool:
    """Выдаёт каждому сохранённому серверу устойчивый идентификатор.

    Идентификатор не зависит от позиции в списке: после обновления подписки
    порядок меняется, а выбор пользователя должен остаться на том же сервере.
    """
    changed = False
    seen = set()
    for group in groups:
        for server in group.get("servers", []):
            server_id = server.get("ui_id")
            if (
                not isinstance(server_id, str)
                or not server_id
                or len(server_id) > 128
                or server_id in seen
            ):
                server_id = _uuid_mod.uuid4().hex
                server["ui_id"] = server_id
                changed = True
            seen.add(server_id)
    return changed


def server_fingerprint(server):
    fields = {k: v for k, v in server.items() if k not in {"ui_id", "remark", "ping", "name"}}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


groups: list = load_groups()
if ensure_server_ids(groups):
    save_groups(groups)

wg_groups: list = load_wg_groups()
if ensure_server_ids(wg_groups):
    save_wg_groups(wg_groups)

apps_config: dict = load_apps()


def save_proxy_groups():
    ensure_server_ids(groups)
    save_groups(groups)


def save_wireguard_groups():
    ensure_server_ids(wg_groups)
    save_wg_groups(wg_groups)
