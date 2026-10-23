"""中文字段标签：CLI、前端、评测共用，避免各处重复维护。"""

from __future__ import annotations

FEATURE_LABELS: dict[str, dict[str, str]] = {
    "nail_bed_ratio": {
        "short_wide": "甲床偏短宽",
        "standard": "甲床比例标准",
        "slender": "甲床偏细长",
    },
    "nail_shape": {
        "round": "圆甲",
        "square": "方甲",
        "oval": "椭圆",
        "almond": "杏仁",
        "squoval": "方圆形",
    },
    "length": {
        "very_short": "极短甲",
        "short": "短甲",
        "mid": "中等甲长",
        "long": "长甲",
    },
    "ita_band": {"light": "肤色偏浅", "mid": "肤色中等", "deep": "肤色偏深"},
    "warmth": {"cool": "冷调", "neutral": "中性调", "warm": "暖调"},
    "hand_type": {"slim": "手指纤细", "standard": "手型标准", "fleshy": "手型偏肉感"},
    "scene": {
        "commute": "通勤",
        "date": "约会",
        "wedding": "婚礼",
        "festival": "节日",
        "cool": "酷感",
        "y2k": "Y2K",
    },
}

FIELD_TITLES: dict[str, str] = {
    "nail_bed_ratio": "甲床比例",
    "nail_shape": "当前甲型",
    "length": "甲长",
    "ita_band": "肤色深浅",
    "warmth": "肤色冷暖",
    "hand_type": "手型",
    "scene": "使用场景",
}

FIELD_ORDER = [
    "nail_bed_ratio",
    "nail_shape",
    "length",
    "ita_band",
    "warmth",
    "hand_type",
    "scene",
]


def label(field: str, value: str | None) -> str:
    if value is None:
        return ""
    return FEATURE_LABELS.get(field, {}).get(str(value), str(value))


def summarize(features: dict) -> str:
    parts = [label(field, features.get(field)) for field in FIELD_ORDER]
    return "、".join(part for part in parts if part)
