"""Validate calibration files before they reach the Windows adapter."""
import json
from pathlib import Path

ROLES = {"composer", "microphone", "finish", "send"}


def load_selectors(path):
    path = Path(path)
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.keys() <= ROLES:
            raise ValueError("invalid selector roles")
        for role, selector in data.items():
            if (not isinstance(selector, dict)
                    or set(selector) != {"control_type", "name", "automation_id"}
                    or not all(isinstance(value, str) for value in selector.values())
                    or selector["control_type"] != ("EditControl" if role == "composer" else "ButtonControl")
                    or not (selector["name"] or selector["automation_id"])):
                raise ValueError("invalid selector")
        return data, ""
    except (OSError, ValueError, TypeError):
        return {}, "Сохранённые настройки не удалось прочитать. Настрой кнопки заново."


def save_selectors(path, selectors):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(selectors, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_preferences(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        result = {}
        if isinstance(data.get("voice_summary"), bool):
            result["voice_summary"] = data["voice_summary"]
        if isinstance(data.get("voice_id"), str):
            result["voice_id"] = data["voice_id"]
        return result
    except (OSError, ValueError):
        return {}


def save_preferences(path, preferences):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
