"""Роуты Zapret. Всё состояние живёт в ui/zapret_service.py."""
import threading
from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from engine.game_filter import GameFilterError
from ui import app_state

bp = Blueprint("zapret", __name__)

deps = SimpleNamespace(service=None, broadcast=None, log=None,
                       vpn_servers=lambda: [], vpn_mode=lambda: None)


def init(service, broadcast, log, vpn_servers=None, vpn_mode=None):
    deps.service = service
    deps.broadcast = broadcast
    deps.log = log
    if vpn_servers is not None:
        deps.vpn_servers = vpn_servers
    if vpn_mode is not None:
        deps.vpn_mode = vpn_mode


@bp.route("/api/zapret/strategies", methods=["GET"])
def api_zapret_strategies():
    return jsonify({"strategies": deps.service.strategies()})


@bp.route("/api/zapret/start", methods=["POST"])
def api_zapret_start():
    service = deps.service
    data = request.get_json(silent=True) or {}
    strategy_id = service.canonical_strategy_id(data.get("strategy_id", "flowseal_general"))
    if strategy_id not in {item["id"] for item in service.strategies()}:
        return jsonify({"ok": False, "error": "Неизвестная стратегия"})

    # Игровой фильтр берётся из сохранённых настроек: winws не запускается с
    # наполовину собранной конфигурацией, поэтому проверяем до begin_start().
    settings = app_state.app_settings
    try:
        filter_config = app_state.normalize_zapret_game_filter(
            settings.get("zapret_game_filter")
        )
    except GameFilterError as exc:
        return jsonify({"ok": False, "error": f"Игровой фильтр: {exc}"}), 422
    if settings.get("zapret_strategy") != strategy_id:
        settings["zapret_strategy"] = strategy_id
        app_state.save_settings(settings)

    generation = service.begin_start()
    if generation is None:
        return jsonify({"ok": False, "error": "Zapret уже запускается или работает"})

    # Адреса VPN-серверов собираются до запуска: winws не должен
    # десинхронизировать внешнее соединение самого туннеля.
    try:
        vpn_servers = deps.vpn_servers()
    except Exception as exc:
        deps.log(f"Zapret: не удалось собрать адреса VPN-серверов: {exc}", "warn")
        vpn_servers = []

    def do_start():
        deps.broadcast({"type": "zapret_status", "running": False,
                        "strategy": None, "state": "starting"})
        started = service.finish_start(strategy_id, generation, filter_config, vpn_servers)
        if started is None:
            return
        deps.broadcast({
            "type":     "zapret_status",
            "running":  started,
            "strategy": service.strategy,
            "state":    "on" if started else "err",
        })

    threading.Thread(target=do_start, daemon=True).start()
    return jsonify({"ok": True})


@bp.route("/api/zapret/stop", methods=["POST"])
def api_zapret_stop():
    service = deps.service
    if not service.begin_stop():
        return jsonify(ok=True)
    deps.broadcast({"type": "zapret_status", "running": service.running,
                    "strategy": service.strategy, "state": "stopping"})

    def finish():
        try:
            service.stop()
        except Exception as exc:
            deps.log(str(exc), "err")
        finally:
            deps.broadcast({"type": "zapret_status", **service.status()})

    threading.Thread(target=finish, daemon=True).start()
    return jsonify(ok=True)


@bp.route("/api/zapret/status", methods=["GET"])
def api_zapret_status():
    return jsonify(deps.service.status())


@bp.route("/api/zapret/game-filter", methods=["GET", "POST"])
def api_zapret_game_filter():
    """Читает и сохраняет игровой фильтр. 400 — ввод, 500 — отказ записи."""
    service, settings = deps.service, app_state.app_settings
    if request.method == "POST":
        if service.state != "off":
            return jsonify(ok=False, error="Сначала остановите Zapret"), 409
        try:
            value = app_state.normalize_zapret_game_filter(
                (request.get_json(silent=True) or {}).get("game_filter")
            )
        except GameFilterError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        previous = settings.get("zapret_game_filter")
        settings["zapret_game_filter"] = value
        if not app_state.save_settings(settings):
            settings["zapret_game_filter"] = previous
            return jsonify(ok=False, error="Не удалось сохранить игровой фильтр"), 500
        deps.broadcast({"type": "zapret_game_filter", "game_filter": value})
    stored = settings.get("zapret_game_filter")
    strategy = settings.get("zapret_strategy")
    return jsonify(
        ok=True,
        game_filter=stored,
        summary=service.game_filter_summary(stored, strategy),
        coverage=service.coverage(stored, strategy, deps.vpn_mode()),
    )


@bp.route("/api/zapret/coverage", methods=["GET"])
def api_zapret_coverage():
    """Охват выбранной стратегии — для предпросмотра до запуска обхода."""
    settings = app_state.app_settings
    strategy = request.args.get("strategy_id") or settings.get("zapret_strategy")
    coverage = deps.service.coverage(settings.get("zapret_game_filter"), strategy,
                                     deps.vpn_mode())
    if coverage is None:
        return jsonify(ok=False, error="Неизвестная стратегия"), 404
    return jsonify(ok=True, coverage=coverage)
