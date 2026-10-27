"""M30：自动打标款式的冷暖校准与匹配度回归。"""

from __future__ import annotations

import json

from core.data import TONE_BY_COLOR_FAMILY, library_path, load_styles
from core.features import HandFeatures
from core.pipeline import recommend
from core.styles import load_styles_json

DEMO = library_path("demo")
SAMPLE = library_path("sample")

FEATURES = HandFeatures(
    nail_bed_ratio="slender",
    nail_shape="oval",
    length="long",
    ita_band="light",
    warmth="cool",
    hand_type="standard",
    scene="date",
)


def test_demo_autotag_tones_follow_color_family():
    styles = load_styles(DEMO)
    assert len(styles) == 43
    wrong = {
        style["id"]: (style["color_family"], style["tone"])
        for style in styles
        if style.get("autotag")
        and style["color_family"] in TONE_BY_COLOR_FAMILY
        and style["tone"] != TONE_BY_COLOR_FAMILY[style["color_family"]]
    }
    assert wrong == {}, f"自动打标款式的 tone 未校准：{wrong}"


def test_known_berry_styles_are_cool_after_calibration():
    styles = {style["id"]: style for style in load_styles(DEMO)}
    for sid in ("d040", "d032"):
        assert styles[sid]["color_family"] == "berry"
        assert styles[sid]["tone"] == "cool"


def test_authored_styles_are_not_rewritten():
    raw = {style["id"]: style["tone"] for style in load_styles_json(SAMPLE)}
    loaded = {style["id"]: style["tone"] for style in load_styles(SAMPLE)}
    assert raw == loaded


def test_match_scores_rise_after_calibration():
    raw_styles = tuple(load_styles_json(DEMO))
    # 未校准：浆果紫被判成 warm，命中不了「冷调浅肤色」规则
    raw_result = recommend(FEATURES, use_llm=False, styles=raw_styles)
    raw_top = max(card["match_score"] for card in raw_result["recommendations"])
    assert raw_top <= 0.80, raw_top

    # 校准后：同一组特征在演示库上应该出现明显更高的匹配度
    result = recommend(FEATURES, use_llm=False, styles=load_styles(DEMO))
    scores = [card["match_score"] for card in result["recommendations"]]
    assert max(scores) >= 0.90, scores
    assert min(scores) >= 0.50, scores


def test_recommendation_contract_still_holds_on_demo():
    raw = json.loads(DEMO.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    result = recommend(FEATURES, use_llm=False, styles=load_styles(DEMO))
    cards = result["recommendations"]
    assert len(cards) == 3
    assert len({card["color_family"] for card in cards}) == 3
