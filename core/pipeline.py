"""端到端编排：特征 → 过滤 → 排序 → 三选一 → 解释 → 校验 → 卡片。

API 层（api/routes.py）和命令行（scripts/demo.py）都只调用这里，
保证两条入口的行为完全一致。

异常策略：
- 款式库为空/数据损坏 → EmptyStyleLibraryError（API 映射 503）
- 过滤后没有候选、候选不足 3 款 → NoCandidateError（API 映射 422）
- 输出契约失败 → ContractError（由 validator 抛出，API 映射 502）
"""

from __future__ import annotations

from .data import load_styles, load_taxonomy
from .errors import EmptyStyleLibraryError, NoCandidateError
from .explainer import explain
from .features import HandFeatures
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

    cards = []
    used_tiers: set[str] = set()
    for pick in picks:
        sid = pick.style["id"]
        text = rec_text.get(sid, {})
        reason = (text.get("reason") or "").strip() or "；".join(pick.reasons[:2]) or "与你的特征匹配"
        tier = _tier(pick.style, taxonomy)
        if tier in used_tiers:
            tier = "fill"
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

    return {
        "features": features.to_dict(),
        "recommendations": cards,
        "avoid": explanations.get("avoid", []),
        "meta": {
            "candidates_considered": len(kept),
            "excluded": len(avoided),
            "engine": "rules+explain",
        },
    }
