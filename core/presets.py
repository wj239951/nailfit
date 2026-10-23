"""CLI / 前端 / 测试共用的特征预设，避免三处重复维护。

字段取值本身定义在 `data/taxonomy.yaml → features`，这里只放默认值与场景预设。
"""

from __future__ import annotations

from .data import load_taxonomy

FEATURE_FIELDS = [
    "nail_bed_ratio",
    "nail_shape",
    "length",
    "ita_band",
    "warmth",
    "hand_type",
    "scene",
]

DEFAULTS: dict[str, str] = {
    "nail_bed_ratio": "standard",
    "nail_shape": "oval",
    "length": "short",
    "ita_band": "light",
    "warmth": "warm",
    "hand_type": "standard",
    "scene": "commute",
}

SCENARIOS: dict[str, dict[str, str]] = {
    "short_wide_warm": {
        "nail_bed_ratio": "short_wide",
        "nail_shape": "oval",
        "length": "short",
        "ita_band": "light",
        "warmth": "warm",
        "hand_type": "fleshy",
        "scene": "commute",
    },
    "slender_cool": {
        "nail_bed_ratio": "slender",
        "nail_shape": "almond",
        "length": "mid",
        "ita_band": "light",
        "warmth": "cool",
        "hand_type": "slim",
        "scene": "date",
    },
    "deep_festival": {
        "nail_bed_ratio": "standard",
        "nail_shape": "squoval",
        "length": "short",
        "ita_band": "deep",
        "warmth": "warm",
        "hand_type": "standard",
        "scene": "festival",
    },
    "long_y2k": {
        "nail_bed_ratio": "standard",
        "nail_shape": "square",
        "length": "long",
        "ita_band": "mid",
        "warmth": "neutral",
        "hand_type": "standard",
        "scene": "y2k",
    },
}

SCENARIO_LABELS: dict[str, str] = {
    "short_wide_warm": "短宽甲 · 暖肤 · 通勤",
    "slender_cool": "细长甲床 · 冷肤 · 约会",
    "deep_festival": "标准手 · 深肤 · 节日",
    "long_y2k": "长甲 · 方形 · Y2K",
}


def feature_options() -> dict[str, list[str]]:
    """从 taxonomy 读每项特征的合法取值（与后端校验同源）。"""
    return load_taxonomy()["features"]


def scenario_payload(name: str) -> dict[str, str]:
    return dict(SCENARIOS[name])
