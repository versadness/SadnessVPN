"""Статистика и диагностика — роуты без собственного изменяемого состояния."""
from types import SimpleNamespace

from flask import Blueprint, jsonify

from engine.diagnostics import export_journal
from engine.stats import tracker as stats_tracker

bp = Blueprint("system", __name__)

# Заполняется из ui/server.py при регистрации блюпринта.
deps = SimpleNamespace(broadcast=None)


def init(broadcast):
    deps.broadcast = broadcast


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
