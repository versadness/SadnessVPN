"""Роуты Zapret. Всё состояние живёт в ui/zapret_service.py."""
import threading
from types import SimpleNamespace

from flask import Blueprint, jsonify, request

bp = Blueprint("zapret", __name__)

deps = SimpleNamespace(service=None, broadcast=None, log=None)


def init(service, broadcast, log):
    deps.service = service
    deps.broadcast = broadcast
    deps.log = log


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

    generation = service.begin_start()
    if generation is None:
        return jsonify({"ok": False, "error": "Zapret уже запускается или работает"})

    def do_start():
        deps.broadcast({"type": "zapret_status", "running": False,
                        "strategy": None, "state": "starting"})
        started = service.finish_start(strategy_id, generation)
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
