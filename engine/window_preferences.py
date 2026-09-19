"""Small independent window preference; never overwrites VPN settings."""
import json
from pathlib import Path
from engine.paths import data_dir
from engine.json_store import atomic_write_json


def load_maximized():
    try:
        data=json.loads((Path(data_dir())/'window-state.json').read_text(encoding='utf-8'))
        return isinstance(data,dict) and data.get('maximized') is True
    except (OSError,ValueError):return False


def save_maximized(value):
    atomic_write_json(str(Path(data_dir())/'window-state.json'),{'maximized':value is True})
