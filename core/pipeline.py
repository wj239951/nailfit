"""端到端编排：特征 → 过滤 → 排序 → 三选一 → 解释 → 校验 → 卡片。

API 层（api/routes.py）和命令行（scripts/demo.py）都只调用这里，
保证两条入口的行为完全一致。

异常策略：
- 款式库为空/数据损坏 → EmptyStyleLibraryError（API 映射 503）
- 过滤后没有候选、候选不足 3 款 → NoCandidateError（API 映射 422）
- 输出契约失败 → ContractError（由 validator 抛出，API 映射 502）
- 手照质量不达标/视觉特征不全 → VisionUnusableError（API 映射 422，前端转手工录入）
"""

from __future__ import annotations

from pathlib import Path

from .data import load_styles, load_taxonomy
from .errors import EmptyStyleLibraryError, NoCandidateError, VisionUnusableError
from .explainer import explain
from .features import HandFeatures, FeatureError
from .media import empty_media, resolve_card_media
from .retriever import SemanticScorer
from .rules import RuleEngine, normalize
from .selector import Scored, pick_three, rank
from .validator import validate_cards


def _tier(style: dict, taxonomy: dict) -> str:
    for name, scenes in taxonomy.get("tiers", {}).items():
        if set(scenes) & set(style.get("scene", [])):
            return name
    return "extra"


def recommend(
    features: HandFeatures,
    *,
    free_text: str | None = None,
    use_llm: bool = True,
    styles: tuple[dict, ...] | list[dict] | None = None,
    engine: RuleEngine | None = None,
    semantic: SemanticScorer | None = None,
    explainer_kwargs: dict | None = None,
) -> dict:
    taxonomy = load_taxonomy()
    engine = engine or RuleEngine(taxonomy)
    if not isinstance(features, HandFeatures):
        raise FeatureError("features 必须是 HandFeatures 实例")
    features.validate()  # 直接构造的非法特征（如 nail_shape="triangle"）在这里拦下
    styles = list(styles if styles is not None else load_styles())
    if not styles:
        raise EmptyStyleLibraryError("款式库为空：请先在 data/styles.sample.json 录入款式")

    kept, avoided = engine.filter_styles(styles, features)
    if not kept:
        raise NoCandidateError(
            "没有通过硬性过滤的款式：请放宽场景/甲长限制，或补充款式库"
        )
    if len(kept) < 3:
        raise NoCandidateError(
            f"过滤后只剩 {len(kept)} 款，至少需要 3 款才能给出三档推荐"
        )

    ranked = rank(engine, kept, features)

    # 语义加分（可选，失败静默）
    if semantic is not None and semantic.enabled and free_text:
        sims = semantic.score(free_text, kept)
        if sims:
            weight = float(taxonomy["scoring"].get("weight_semantic", 0.0))
            boosted = [
                Scored(
                    style=r.style,
                    score=r.score + weight * sims.get(r.style["id"], 0.0),
                    reasons=r.reasons,
                    rule_ids=r.rule_ids,
                )
                for r in ranked
            ]
            ranked = sorted(boosted, key=lambda x: (-x.score, x.style["id"]))

    picks = pick_three(ranked, taxonomy, features)
    if len(picks) < 3:
        # pick_three 会按色系去重，库里同色系太多时会凑不满 3 款。
        # 这种情况不是“契约 bug”，而是候选不足，应走 422 让用户补库/放宽条件。
        raise NoCandidateError(
            f"可用色系不足：过滤后只剩 {len(picks)} 个不同色系的款式，凑不满三档推荐；"
            "请给款式库补几个其它色系，或放宽场景/甲长限制"
        )
    max_score = engine.max_score(engine.match(features))
    explanations = explain(
        features,
        picks,
        avoided,
        use_llm=use_llm,
        free_text=free_text,
        **(explainer_kwargs or {}),
    )
    rec_text = explanations.get("recommendations", {})
    explainer_meta = explanations.get("meta", {})

    cards = []
    used_tiers: set[str] = set()
    for pick in picks:
        sid = pick.style["id"]
        text = rec_text.get(sid, {})
        reason = (text.get("reason") or "").strip() or "；".join(pick.reasons[:2]) or "与你的特征匹配"
        tier = _tier(pick.style, taxonomy)
        if tier in used_tiers:
            # 同一档位重复时退到不重复的补充档，避免两张卡都叫“补充款”
            tier = next(
                (name for name in ("fill", "extra") if name not in used_tiers),
                "extra",
            )
        used_tiers.add(tier)
        cards.append(
            {
                "style_id": sid,
                "name": pick.style.get("name"),
                "image": pick.style.get("image"),
                "color_family": pick.style.get("color_family"),
                "style": pick.style.get("style"),
                "shape": pick.style.get("shape"),
                "length_fit": pick.style.get("length_fit"),
                "tier": tier,
                "match_score": normalize(pick.score, max_score),
                "matched_rules": list(pick.rule_ids[:3]),
                "matched_reasons": list(pick.reasons[:3]),
                "reason": reason,
                "caution": text.get("caution"),
            }
        )

    validate_cards(cards, {s["id"] for s in styles}, taxonomy)

    # 展示层：给每张卡挂参考图（只读缓存/本地图，不联网；失败退化成纯文字卡）
    media_map = resolve_card_media(
        {s["id"]: s for s in styles}, [c["style_id"] for c in cards]
    )
    for card in cards:
        card["media"] = media_map.get(card["style_id"]) or empty_media()

    return {
        "features": features.to_dict(),
        "recommendations": cards,
        "avoid": explanations.get("avoid", []),
        "meta": {
            "candidates_considered": len(kept),
            "excluded": len(avoided),
            "engine": "rules+explain",
            "explainer": explainer_meta,
        },
    }


# --------------------------------------------------------------------------- 视觉层入口（M8/M9）
def features_from_image(
    image_path: str | Path,
    *,
    scene: str = "commute",
    overrides: dict[str, str] | None = None,
    model_path: str | Path | None = None,
    auto_download: bool = False,
    preview: bool = True,
) -> tuple[dict[str, str], dict]:
    """手照 → (可能不全的特征 dict, 视觉元信息)。

    照片质量不达标时 `meta["quality"]` 不是 "ok"，特征会缺项（对应字段列在
    `meta["unreliable"]`），调用方应把缺的项交给用户手工补（M11），而不是硬猜。
    """
    from . import vision  # 延迟导入：mediapipe / opencv 是可选依赖

    taxonomy_features = list(load_taxonomy()["features"])
    result = vision.extract(
        image_path,
        model_path=model_path,
        preview=preview,
        auto_download=auto_download,
    )
    payload: dict[str, str] = dict(result.features)
    for field in result.unreliable:
        payload.pop(field, None)
    # 只接受 taxonomy 里声明的 7 个特征字段：前端可能把 ita_degrees 之类的
    # 派生指标一起传回来，直接塞进 HandFeatures.from_dict 会报“未知特征字段”。
    allowed_features = set(taxonomy_features)
    for key, value in (overrides or {}).items():
        key = str(key)
        if key in allowed_features:
            payload[key] = str(value)  # 人工修正优先于视觉结果
    payload["scene"] = scene
    if "ita_degrees" in result.metrics:
        payload["ita_degrees"] = round(float(result.metrics["ita_degrees"]), 1)

    meta = {
        "image": str(image_path),
        "quality": result.quality,
        "handedness": result.observation.handedness,
        "handedness_score": round(result.observation.handedness_score, 3),
        "gesture": result.observation.gesture,
        "gesture_score": round(result.observation.gesture_score, 3),
        "confidences": dict(result.confidences),
        "unreliable": list(result.unreliable),
        "notes": list(result.notes),
        "ita_degrees": round(float(result.metrics.get("ita_degrees", 0.0)), 1),
        "metrics": {key: round(value, 3) for key, value in result.metrics.items()},
        "preview": str(result.preview) if result.preview else None,
    }
    return payload, meta


def recommend_from_image(
    image_path: str | Path,
    *,
    scene: str = "commute",
    use_llm: bool = False,
    free_text: str | None = None,
    overrides: dict[str, str] | None = None,
    model_path: str | Path | None = None,
    auto_download: bool = False,
    preview: bool = True,
    styles: tuple[dict, ...] | list[dict] | None = None,
    engine: RuleEngine | None = None,
    semantic: SemanticScorer | None = None,
) -> dict:
    """手照直接出推荐（M9）；质量不达标或缺特征时抛 VisionUnusableError。"""
    payload, vision_meta = features_from_image(
        image_path,
        scene=scene,
        overrides=overrides,
        model_path=model_path,
        auto_download=auto_download,
        preview=preview,
    )
    missing = [field for field in vision_meta.get("unreliable", []) if field not in payload]
    if missing or vision_meta.get("quality") == "low":
        detail = "、".join(missing) if missing else "照片质量过低"
        raise VisionUnusableError(
            f"这张照片没能可靠地给出这些特征：{detail}。"
            "有两种做法：① 在前端用下拉把这几项补上（不需要重拍）；"
            "② 想要全自动就手背平放在桌面、手机从正上方拍一张；"
            "③ 或改用「手工录入」功能补齐缺项。"
        )
    try:
        features = HandFeatures.from_dict(payload)
    except FeatureError as exc:
        raise VisionUnusableError(
            f"这张照片只识别出一部分特征（{exc}）。可以在前端用下拉补齐，"
            "或手背平放从正上方重拍一张。"
        ) from exc

    result = recommend(
        features,
        free_text=free_text,
        use_llm=use_llm,
        styles=styles,
        engine=engine,
        semantic=semantic,
    )
    result["vision"] = vision_meta
    return result
