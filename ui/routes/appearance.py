"""Аватар и обои профиля. Файлы лежат в PROFILE_DIR, имя — в настройках."""
import io
import os
import secrets
import time
from types import SimpleNamespace

from flask import Blueprint, jsonify, request, send_file
from PIL import Image

from ui import app_state

bp = Blueprint("appearance", __name__)

deps = SimpleNamespace(broadcast=None)


def init(broadcast):
    deps.broadcast = broadcast


def _uploaded_image_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _appearance_setting(kind: str) -> str:
    if kind == "avatar":
        return "avatar_file"
    if kind == "wallpaper":
        return "wallpaper_file"
    raise ValueError("Неизвестный тип оформления")


def _saved_appearance_path(kind: str) -> str | None:
    key = _appearance_setting(kind)
    filename = os.path.basename(app_state.app_settings.get(key, ""))
    if not filename:
        return None
    path = os.path.abspath(os.path.join(app_state.PROFILE_DIR, filename))
    if os.path.dirname(path) != os.path.abspath(app_state.PROFILE_DIR):
        return None
    return path if os.path.isfile(path) else None


@bp.route("/api/appearance/<kind>", methods=["GET"])
def api_appearance_get(kind):
    try:
        path = _saved_appearance_path(kind)
    except ValueError:
        path = None
    if not path:
        return "", 404
    response = send_file(path, conditional=True, max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/api/appearance/<kind>", methods=["POST"])
def api_appearance_upload(kind):
    settings = app_state.app_settings
    try:
        key = _appearance_setting(kind)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    upload = request.files.get("file")
    if not upload:
        return jsonify({"ok": False, "error": "Файл не выбран"})
    limit = 2 * 1024 * 1024 if kind == "avatar" else 8 * 1024 * 1024
    data = upload.stream.read(limit + 1)
    if len(data) > limit:
        return jsonify({"ok": False, "error": "Изображение слишком большое"})
    extension = _uploaded_image_extension(data)
    try:
        with Image.open(io.BytesIO(data)) as decoded:
            if decoded.width * decoded.height > (4096*4096 if kind == "avatar" else 32_000_000):
                raise ValueError("Слишком высокое разрешение изображения")
            decoded.verify()
    except (OSError, ValueError, Image.DecompressionBombError):
        return jsonify(ok=False, error="Повреждённое изображение или недопустимое разрешение"), 400
    if not extension:
        return jsonify({"ok": False, "error": "Поддерживаются PNG, JPEG и WebP"})
    os.makedirs(app_state.PROFILE_DIR, exist_ok=True)
    # Never overwrite the previous image before its replacement is committed
    # in settings. A failed settings write must preserve both old references
    # and old bytes, including uploads of the same format.
    filename = kind + "-" + secrets.token_hex(8) + extension
    target = os.path.join(app_state.PROFILE_DIR, filename)
    temporary = target + "." + secrets.token_hex(6) + ".tmp"
    previous_name = settings.get(key, "")
    try:
        with open(temporary, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
        settings[key] = filename
        if not app_state.save_settings(settings):
            raise OSError("Не удалось сохранить настройки оформления")
    except Exception as exc:
        settings[key] = previous_name
        for unused in (temporary, target):
            try:
                if os.path.exists(unused):
                    os.remove(unused)
            except OSError:
                pass
        return jsonify({"ok": False, "error": str(exc)})
    # Settings already committed: failing to remove an old/locked image must
    # not report failure or roll the in-memory settings back out of sync.
    if previous_name and previous_name != filename:
        previous = os.path.join(app_state.PROFILE_DIR, os.path.basename(previous_name))
        try:
            if os.path.isfile(previous):
                os.remove(previous)
        except OSError:
            pass
    url = f"/api/appearance/{kind}?v={int(time.time() * 1000)}"
    # Имя сохранённого файла отдаётся явно: интерфейс не должен выводить его
    # из адреса картинки.
    deps.broadcast({"type": "appearance_updated", "kind": kind, "url": url, "file": filename})
    return jsonify({"ok": True, "url": url, "file": filename})


@bp.route("/api/appearance/<kind>/reset", methods=["POST"])
def api_appearance_reset(kind):
    settings = app_state.app_settings
    try:
        key = _appearance_setting(kind)
        path = _saved_appearance_path(kind)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    previous = settings.get(key, "")
    settings[key] = ""
    if not app_state.save_settings(settings):
        settings[key] = previous
        return jsonify({"ok": False, "error": "Не удалось сохранить настройки"})
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    deps.broadcast({"type": "appearance_updated", "kind": kind, "url": "", "file": ""})
    return jsonify({"ok": True})
