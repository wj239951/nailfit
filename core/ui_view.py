"""前端展示用的纯函数（不依赖 Streamlit，可单测）。

Streamlit 页面（app/streamlit_app.py）只负责布局与交互，所有数据整理都放这里，
这样换前端（Gradio / FastAPI + JS）时逻辑不用重写。
"""

from __future__ import annotations

import json
from pathlib import Path

from .data import load_taxonomy
from .features import FeatureError, HandFeatures
from .labels import summarize
from .pipeline import recommend

ROOT = Path(__file__).resolve().parents[1]

TIER_LABELS: dict[str, str] = {
    "safe": "稳妥款",
    "highlight": "亮点款",
    "bold": "大胆款",
    "fill": "补充款",
    "extra": "其他",
}

LIBRARY_CHOICES: list[tuple[str, str]] = [
    ("样例库（13 条，占位图）", "data/styles.sample.json"),
    ("演示库（43 条，带演示图）", "data/styles.demo.json"),
]


def library_choices() -> list[tuple[str, str]]:
    """只返回磁盘上确实存在的款式库，避免前端选到缺失文件。"""
    return [(label, path) for label, path in LIBRARY_CHOICES if (ROOT / path).exists()]


def tier_label(tier: str | None) -> str:
    return TIER_LABELS.get(str(tier), str(tier or "—"))


def image_file(image: str | None) -> Path | None:
    """款式图相对仓库根的路径 → 绝对路径（不存在时返回 None，前端显示占位）。"""
    if not image:
        return None
    path = (ROOT / image).resolve()
    return path if path.exists() else None


def build_features(selection: dict[str, str]) -> HandFeatures:
    """把前端下拉框的取值组装成 HandFeatures 并校验（与后端同一套校验）。"""
    enums = load_taxonomy()["features"]
    unknown = sorted(set(selection) - set(enums))
    if unknown:
        raise FeatureError("未知特征字段：" + "、".join(unknown))
    payload: dict[str, str] = {}
    for field, allowed in enums.items():
        value = selection.get(field)
        if not value:
            continue
        if value not in allowed:
            raise ValueError(f"{field}={value!r} 不在允许取值中")
        payload[field] = value
    return HandFeatures.from_dict(payload)


def card_view(card: dict) -> dict:
    """把 pipeline 的单张卡片转成前端展示用的结构。"""
    score = float(card.get("match_score") or 0.0)
    return {
        "style_id": card.get("style_id"),
        "name": card.get("name") or card.get("style_id"),
        "image": image_file(card.get("image")),
        "tier": card.get("tier"),
        "tier_text": tier_label(card.get("tier")),
        "score_percent": int(round(max(0.0, min(1.0, score)) * 100)),
        "reason": card.get("reason") or "",
        "caution": card.get("caution"),
        "matched_rules": list(card.get("matched_rules") or []),
        "matched_reasons": list(card.get("matched_reasons") or []),
    }


def feature_summary(payload: dict) -> str:
    return summarize(payload.get("features") or {})


def avoid_tips(payload: dict) -> list[str]:
    return [str(tip) for tip in (payload.get("avoid") or [])]


def generate(
    selection: dict[str, str],
    *,
    free_text: str = "",
    use_llm: bool = False,
    styles_path: str | None = None,
    styles: list[dict] | None = None,
) -> dict:
    """跑一次完整推荐；入参和 pipeline 一样，异常向上抛给前端展示。"""
    features = build_features(selection)
    if styles is None and styles_path:
        from .data import load_styles

        styles = list(load_styles(styles_path))
    return recommend(
        features,
        free_text=(free_text or None),
        use_llm=use_llm,
        styles=styles,
    )


def payload_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
