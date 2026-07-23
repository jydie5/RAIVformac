from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_QUALITY_SETTINGS_PATH = (
    Path.home() / "Library" / "Application Support" / "RAIV" / "settings.json"
)
QUALITY_SETTINGS_KEY = "quality"
VALID_MODELS = {"models-se", "models-pro"}
VALID_NOISE = {
    "models-se": {-1, 0, 1, 2, 3},
    "models-pro": {3},
}


def load_settings_file(settings_path: Path) -> dict[str, Any]:
    try:
        with settings_path.expanduser().open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_quality_preset(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name", "")).strip()
    model = str(value.get("model", ""))
    try:
        scale = int(value.get("scale"))
        noise = int(value.get("noise"))
        tile = int(value.get("tile", 0))
        threshold = int(value.get("threshold", 2234))
    except (TypeError, ValueError):
        return None
    if not name or len(name) > 40 or model not in VALID_MODELS:
        return None
    if scale < 1 or scale > 4 or noise not in VALID_NOISE[model]:
        return None
    if model == "models-pro" and scale != 3:
        return None
    if tile < 0 or tile > 4096 or threshold < 1 or threshold > 12000:
        return None
    return {
        "name": name,
        "mode": "corrected",
        "model": model,
        "scale": scale,
        "noise": str(noise),
        "tile": tile,
        "threshold": threshold,
        "tta": bool(value.get("tta", False)),
        "description": str(value.get("description", "")).strip(),
    }


def load_quality_preferences(settings_path: Path | None) -> dict[str, Any]:
    path = settings_path or DEFAULT_QUALITY_SETTINGS_PATH
    settings = load_settings_file(path)
    quality = settings.get(QUALITY_SETTINGS_KEY)
    if not isinstance(quality, dict):
        quality = {}
    custom_presets = [
        preset
        for item in quality.get("custom_presets", [])
        if (preset := validate_quality_preset(item)) is not None
    ]
    return {
        "ui_mode": "manual" if quality.get("ui_mode") == "manual" else "simple",
        "selected_preset": str(quality.get("selected_preset") or "自然"),
        "custom_presets": custom_presets,
    }


def save_quality_preferences(
    settings_path: Path | None,
    *,
    ui_mode: str,
    selected_preset: str,
    custom_presets: list[dict[str, Any]],
) -> None:
    path = (settings_path or DEFAULT_QUALITY_SETTINGS_PATH).expanduser()
    valid_presets = [
        preset
        for item in custom_presets
        if (preset := validate_quality_preset(item)) is not None
    ]
    settings = load_settings_file(path)
    settings[QUALITY_SETTINGS_KEY] = {
        "ui_mode": "manual" if ui_mode == "manual" else "simple",
        "selected_preset": str(selected_preset or "自然"),
        "custom_presets": valid_presets,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary_path.replace(path)
