"""Тесты работают с временным каталогом данных, а не с ./data разработчика.

Пакет импортируется раньше тестовых модулей, поэтому переменная задаётся до
того, как engine/ui прочитают путь к данным при импорте.
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("SADNESS_DATA_DIR"):
    _DATA_DIR = tempfile.mkdtemp(prefix="sadness-tests-data-")
    os.environ["SADNESS_DATA_DIR"] = _DATA_DIR
    atexit.register(shutil.rmtree, _DATA_DIR, ignore_errors=True)
