from __future__ import annotations

from core.features import HandFeatures
from core.pipeline import recommend

SHORT_WIDE_WARM = {
    "nail_bed_ratio": "short_wide",
    "length": "short",
    "ita_band": "light",
    "warmth": "warm",
    "hand_type": "fleshy",
    "scene": "commute",
}

DEEP_FESTIVAL = {
    "nail_bed_ratio": "standard",
    "length": "short",
    "ita_band": "deep",
    "warmth": "warm",
    "hand_type": "standard",
    "scene": "festival",
}


def test_recommend_returns_three_diverse_cards() -> None:
    payload = recommend(HandFeatures.from_dict(SHORT_WIDE_WARM), use_llm=False)
    cards = payload["recommendations"]

    assert len(cards) == 3
    assert len({c["style_id"] for c in cards}) == 3
    assert len({c["color_family"] for c in cards}) == 3, "三条推荐不得同色系"
    assert all(0.0 <= c["match_score"] <= 1.0 for c in cards)
    assert all(c["reason"].strip() for c in cards)
    # matched_rules 存规则 id（ascii 小写），matched_reasons 存可读原因
    assert all(r.isascii() for c in cards for r in c["matched_rules"])
    assert all(len(r) > 6 for c in cards for r in c["matched_reasons"])


def test_top_pick_for_short_wide_warm_is_nude_french() -> None:
    payload = recommend(HandFeatures.from_dict(SHORT_WIDE_WARM), use_llm=False)
    assert payload["recommendations"][0]["style_id"] == "s001"


def test_deep_skin_blocks_light_nude() -> None:
    payload = recommend(HandFeatures.from_dict(DEEP_FESTIVAL), use_llm=False)
    ids = {c["style_id"] for c in payload["recommendations"]}
    assert "s001" not in ids, "深肤色不应推荐浅裸色"


def test_avoid_list_is_present() -> None:
    payload = recommend(HandFeatures.from_dict(SHORT_WIDE_WARM), use_llm=False)
    assert isinstance(payload["avoid"], list)


def test_relaxed_fallback_keeps_families_distinct() -> None:
    """候选拥挤（色相都挨着）时，放宽步骤也不能选重色系。"""
    from core.data import load_taxonomy
    from core.selector import Scored, pick_three

    features = HandFeatures.from_dict(SHORT_WIDE_WARM)
    cramped = [
        Scored(style={"id": "x1", "color_family": "nude_pink", "hue": 20, "scene": ["commute"]}, score=0.9, reasons=()),
        Scored(style={"id": "x2", "color_family": "nude_pink", "hue": 21, "scene": ["commute"]}, score=0.8, reasons=()),
        Scored(style={"id": "x3", "color_family": "nude_pink", "hue": 22, "scene": ["date"]}, score=0.7, reasons=()),
        Scored(style={"id": "x4", "color_family": "nude_pink", "hue": 23, "scene": ["festival"]}, score=0.6, reasons=()),
        Scored(style={"id": "x5", "color_family": "berry", "hue": 24, "scene": ["commute"]}, score=0.5, reasons=()),
        Scored(style={"id": "x6", "color_family": "blue_green", "hue": 25, "scene": ["date"]}, score=0.4, reasons=()),
    ]
    chosen = pick_three(cramped, load_taxonomy(), features)
    assert len(chosen) == 3
    families = [item.style["color_family"] for item in chosen]
    assert len(set(families)) == 3, f"色系重复：{families}"
