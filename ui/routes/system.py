"""Окно, статистика и диагностика — роуты без собственного изменяемого состояния."""
from types import SimpleNamespace

from flask import Blueprint, jsonify

from engine.diagnostics import export_journal
from engine.stats import tracker as stats_tracker

bp = Blueprint("system", __name__)

# Заполняется из ui/server.py при регистрации блюпринта.
deps = SimpleNamespace(broadcast=None, window_command=None)


def init(broadcast, window_command):
    deps.broadcast = broadcast
    deps.window_command = window_command


@bp.route("/api/window/minimize", methods=["POST"])
def api_win_minimize():
    return deps.window_command("minimize")


@bp.route("/api/window/show", methods=["POST"])
def api_win_show():
    return deps.window_command("show")


@bp.route("/api/window/close", methods=["POST"])
def api_win_close():
    return deps.window_command("request_close")


@bp.route("/api/window/togglemax", methods=["POST"])
def api_win_togglemax():
    return deps.window_command("toggle_maximize")


@bp.route("/api/diagnostics", methods=["GET"])
def api_diagnostics():
    return jsonify({"ok": True, "text": export_journal(),
                    "scope": "Сохранённая история, до 4 МБ"})


@bp.route("/api/stats", methods=["GET"])
def api_stats():
    return jsonify(stats_tracker.get_snapshot())


@bp.route("/api/stats/reset-today", methods=["POST"])
def api_stats_reset_today():
    stats_tracker.reset_today()
    snapshot = stats_tracker.get_snapshot()
    deps.broadcast({"type": "stats", **snapshot})
    return jsonify({"ok": True, "stats": snapshot})


@bp.route("/api/stats/reset-all", methods=["POST"])
def api_stats_reset_all():
    stats_tracker.reset_all()
    snapshot = stats_tracker.get_snapshot()
    deps.broadcast({"type": "stats", **snapshot})
    return jsonify({"ok": True, "stats": snapshot})
