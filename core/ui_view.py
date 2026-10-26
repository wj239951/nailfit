"""前端展示用的纯函数（不依赖 Streamlit，可单测）。

Streamlit 页面（app/streamlit_app.py）只负责布局与交互，所有数据整理都放这里，
这样换前端（Gradio / FastAPI + JS）时逻辑不用重写。
"""

from __future__ import annotations

import json
from pathlib import Path

from .data import load_styles, load_taxonomy
from .features import FeatureError, HandFeatures
from .labels import summarize
from .media import media_caption
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
    ("样例库（占位图）", "data/styles.sample.json"),
    ("演示库（带演示图）", "data/styles.demo.json"),
]


def library_choices() -> list[tuple[str, str]]:
    """只返回磁盘上确实存在的款式库，避免前端选到缺失文件。

    标签里带上实际条数，加款式/换库后不用手改文案。
    """
    choices: list[tuple[str, str]] = []
    for label, path in LIBRARY_CHOICES:
        if not (ROOT / path).exists():
            continue
        try:
            count = len(load_styles(path))
        except Exception:  # noqa: BLE001 - 坏库文件不阻塞页面，交给校验脚本报错
            choices.append((label, path))
            continue
        choices.append((f"{label[:-1]}，{count} 条）", path))
    return choices


def default_library_label() -> str:
    """默认选带演示图的演示库（演示时卡片能直接显示图片），没有则退回第一个可用库。"""
    choices = library_choices()
    for label, path in choices:
        if path.endswith("styles.demo.json"):
            return label
    return choices[0][0] if choices else ""


def tier_label(tier: str | None) -> str:
    return TIER_LABELS.get(str(tier), str(tier or "—"))


def image_file(image: str | None) -> Path | None:
    """款式图相对仓库根的路径 → 绝对路径（不存在时返回 None，前端显示占位）。"""
    if not image:
        return None
    path = (ROOT / image).resolve()
    return path if path.exists() else None


def gallery_styles(styles_path: str | None, *, limit: int = 8) -> list[dict]:
    """首页「款式库图廊」：从指定款式库挑前 N 条**有图**的款式。

    返回 [{"style_id", "name", "image": Path, "caption"}]。缺图的条目直接跳过，
    这样首页不会出现空白占位；`limit=0` 表示不限制条数。
    """
    if not styles_path:
        return []
    try:
        styles = list(load_styles(styles_path))
    except Exception:  # noqa: BLE001 - 坏库文件不阻塞首页，交给校验脚本报错
        return []
    result: list[dict] = []
    for style in styles:
        if limit and len(result) >= limit:
            break
        image = image_file((style.get("media") or {}).get("image") or style.get("image"))
        if image is None:
            continue
        tags = "、".join(str(tag) for tag in (style.get("tags") or [])[:3])
        result.append(
            {
                "style_id": style.get("id"),
                "name": style.get("name") or style.get("id"),
                "image": image,
                "caption": f"{style.get('name') or style.get('id')} · {tags}" if tags else str(style.get("name") or ""),
            }
        )
    return result


def build_features(selection: dict[str, str]) -> HandFeatures:
    """把前端下拉框的取值组装成 HandFeatures 并校验（与后端同一套校验）。

    `ita_degrees` 是视觉层派生出来的数值字段（不在 taxonomy 的枚举里），允许透传，
    手照识别后「用这组特征推荐」时不会因为它被当成未知字段而失败。
    """
    enums = load_taxonomy()["features"]
    extra_fields = {"ita_degrees"}
    unknown = sorted(set(selection) - set(enums) - extra_fields)
    if unknown:
        raise FeatureError("未知特征字段：" + "、".join(unknown))
    payload: dict[str, object] = {}
    for field, allowed in enums.items():
        value = selection.get(field)
        if not value:
            continue
        if value not in allowed:
            raise ValueError(f"{field}={value!r} 不在允许取值中")
        payload[field] = value
    ita = selection.get("ita_degrees")
    if ita not in (None, ""):
        payload["ita_degrees"] = float(ita)
    return HandFeatures.from_dict(payload)


def card_view(card: dict) -> dict:
    """把 pipeline 的单张卡片转成前端展示用的结构。

    图片走 media 层：优先参考图（缓存/本地），没有时退回 card["image"]，
    再没有就是占位。media_caption 是必须展示的来源/授权标注。
    """
    score = float(card.get("match_score") or 0.0)
    media = card.get("media") or {}
    image = media.get("image") or card.get("image")
    return {
        "style_id": card.get("style_id"),
        "name": card.get("name") or card.get("style_id"),
        "image": image_file(image),
        "media": dict(media),
        "media_caption": media_caption(media),
        "media_source_url": media.get("source_url"),
        "media_provider": media.get("provider"),
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
