"""前端展示层纯函数的单元测试（不依赖 Streamlit）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.errors import EmptyStyleLibraryError  # noqa: E402
from core.features import FeatureError  # noqa: E402
from core.presets import SCENE_LABELS, SCENARIOS, scene_options  # noqa: E402
from core.ui_view import (  # noqa: E402
    build_features,
    card_view,
    feature_summary,
    generate,
    image_file,
    library_choices,
    payload_json,
    tier_label,
)


def test_build_features_from_selection() -> None:
    selection = dict(SCENARIOS["deep_festival"])
    features = build_features(selection)
    values = features.to_dict()
    assert values["ita_band"] == "deep"
    assert values["scene"] == "festival"


def test_build_features_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        build_features({"length": "eternal"})


def test_build_features_rejects_unknown_field() -> None:
    with pytest.raises(FeatureError):
        build_features({"nail_bed_ratio": "standard", "length": "short", "unknown": "x"})


def test_build_features_passes_through_ita_degrees() -> None:
    """手照识别会带回 ita_degrees（派生数值），不能被当成未知字段。"""
    features = build_features({"nail_shape": "square", "ita_degrees": 58.3})
    assert features.nail_shape == "square"
    assert features.ita_degrees == pytest.approx(58.3)


def test_generate_accepts_vision_payload() -> None:
    """模拟 features_from_image 的返回结构（枚举字段 + scene + ita_degrees）。"""
    payload = generate(
        {"nail_bed_ratio": "standard", "nail_shape": "round", "length": "short",
         "ita_band": "light", "warmth": "warm", "hand_type": "standard",
         "scene": "commute", "ita_degrees": 64.4},
        use_llm=False,
    )
    assert len(payload["recommendations"]) == 3


def test_scene_options_are_taxonomy_scenes() -> None:
    """手照识别侧的场景下拉必须是 scene 枚举，不能用特征预设名（回归）。"""
    scenes = scene_options()
    assert set(SCENE_LABELS) == set(scenes)
    assert {"commute", "date", "wedding", "festival", "cool", "y2k"} <= set(scenes)
    assert "slender_cool" not in scenes


def test_build_features_rejects_preset_name_as_scene() -> None:
    """把预设名当场景传会报非法值（而不是被误当成未知字段）。"""
    with pytest.raises(ValueError):
        build_features({"scene": "slender_cool"})


def test_tier_label() -> None:
    assert tier_label("safe") == "稳妥款"
    assert tier_label("bold") == "大胆款"
    assert tier_label("unknown-tier") == "unknown-tier"


def test_library_choices_point_to_existing_files() -> None:
    choices = dict(library_choices())
    assert choices, "至少要有一个可用款式库"
    for path in choices.values():
        assert (ROOT / path).exists(), path


def test_image_file_handles_missing() -> None:
    assert image_file(None) is None
    assert image_file("static/demo/not_exist.jpg") is None


def test_generate_with_demo_library() -> None:
    payload = generate(
        SCENARIOS["slender_cool"],
        styles_path="data/styles.demo.json",
        use_llm=False,
    )
    assert len(payload["recommendations"]) == 3
    assert payload["meta"]["candidates_considered"] >= 3

    views = [card_view(card) for card in payload["recommendations"]]
    for view in views:
        assert view["name"]
        assert view["image"] is not None and view["image"].exists()
        assert 0 <= view["score_percent"] <= 100
        assert view["tier_text"]
        assert view["reason"]


def test_generate_without_candidates_raises() -> None:
    with pytest.raises(EmptyStyleLibraryError):
        generate(SCENARIOS["short_wide_warm"], styles=[], use_llm=False)


def test_feature_summary_and_json() -> None:
    payload = generate(SCENARIOS["long_y2k"], styles_path="data/styles.demo.json", use_llm=False)
    summary = feature_summary(payload)
    assert "甲床" in summary and "Y2K" in summary

    raw = payload_json(payload)
    assert json.loads(raw)["recommendations"][0]["style_id"]
