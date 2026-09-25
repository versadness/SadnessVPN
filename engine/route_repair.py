"""Безопасное восстановление маршрутов, потерявших свой сервер.

Подписка может перестать отдавать сервер, а группу можно удалить целиком.
Сохранённое назначение ``server:<ui_id>`` после этого указывает в пустоту,
и сборка конфигурации падает с ValueError уже в момент подключения.

Здесь потерянное назначение переводится обратно на основной сервер:
приложение возвращается к общему режиму, правило — на выбранный VPN.
Превращать потерю в ``direct`` нельзя: это молча вывело бы трафик наружу.
Подбирать «похожий» сервер тоже нельзя — устойчивость ui_id обеспечивает
server_fingerprint при обновлении подписки, а гадать здесь небезопасно.
"""
import copy

# Приложение без своего сервера снова слушается общего режима, правило —
# идёт через сервер, выбранный на главном экране. Ни одно значение здесь
# не может стать "direct".
APP_FALLBACK = "default"
RULE_FALLBACK = "proxy"


def known_server_ids(groups) -> set:
    return {
        server["ui_id"]
        for group in groups or []
        if isinstance(group, dict)
        for server in group.get("servers") or []
        if isinstance(server, dict) and isinstance(server.get("ui_id"), str) and server["ui_id"]
    }


def _points_at_missing_server(destination, known) -> bool:
    return (
        isinstance(destination, str)
        and destination.startswith("server:")
        and destination[len("server:"):] not in known
    )


def _plural(count, one, few, many) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def describe(report) -> str:
    """Одна строка для журнала — без адресов, ключей и ссылок подписки."""
    if not report["changed"]:
        return ""
    parts = []
    apps, rules = len(report["apps"]), len(report["rules"])
    if apps:
        parts.append(f"{apps} {_plural(apps, 'приложение', 'приложения', 'приложений')}")
    if rules:
        parts.append(f"{rules} {_plural(rules, 'правило', 'правила', 'правил')}")
    verb = _plural(report["total"], "переведено", "переведены", "переведены")
    return "Маршрутизация восстановлена: " + " и ".join(parts) + f" {verb} на основной VPN"


def notice(report) -> str:
    """Одно уведомление на всю починку, а не по одному на каждое правило."""
    if not report["changed"]:
        return ""
    return (
        "Некоторые маршруты ссылались на удалённые серверы "
        f"и были безопасно переключены на основной VPN: {report['total']}"
    )


def repair_routing(apps_config, groups):
    """Вернуть (конфигурация, отчёт). Аргументы не изменяются."""
    known = known_server_ids(groups)
    config = copy.deepcopy(apps_config) if isinstance(apps_config, dict) else {}
    apps, rules = [], []
    for app in config.get("apps") or []:
        if isinstance(app, dict) and _points_at_missing_server(app.get("destination"), known):
            app["destination"] = APP_FALLBACK
            apps.append(app.get("exe", ""))
    for rule in config.get("rules") or []:
        if isinstance(rule, dict) and _points_at_missing_server(rule.get("destination"), known):
            rule["destination"] = RULE_FALLBACK
            rules.append(rule.get("id", ""))
    report = {
        "apps": apps,
        "rules": rules,
        "total": len(apps) + len(rules),
        "changed": bool(apps or rules),
    }
    report["message"] = describe(report)
    report["notice"] = notice(report)
    return config, report
