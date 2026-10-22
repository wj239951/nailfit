from __future__ import annotations

import pytest

from core.data import load_rules, load_styles, load_taxonomy
from core.features import FeatureError, HandFeatures
from core.rules import RuleEngine, length_compatible

SHORT_WIDE_WARM = {
    "nail_bed_ratio": "short_wide",
    "length": "short",
    "ita_band": "light",
    "warmth": "warm",
    "hand_type": "fleshy",
    "scene": "commute",
}


@pytest.fixture()
def engine() -> RuleEngine:
    return RuleEngine(load_taxonomy(), load_rules())


@pytest.fixture()
def features() -> HandFeatures:
    return HandFeatures.from_dict(SHORT_WIDE_WARM)


def test_match_hits_bed_rule(engine: RuleEngine, features: HandFeatures) -> None:
    assert "bed_short_wide" in {r.id for r in engine.match(features)}


def test_round_shape_is_hard_filtered(engine: RuleEngine, features: HandFeatures) -> None:
    kept, avoided = engine.filter_styles(load_styles(), features)
    kept_ids = {s["id"] for s in kept}
    avoided_ids = {s["style_id"] for s in avoided}
    assert "s006" not in kept_ids, "圆头甲型应被甲床规则排除"
    assert "s006" in avoided_ids
    assert any("甲床" in item["reason"] for item in avoided if item["style_id"] == "s006")


def test_long_style_incompatible_with_short_nail() -> None:
    styles = {s["id"]: s for s in load_styles()}
    features = HandFeatures.from_dict(SHORT_WIDE_WARM)
    assert length_compatible(styles["s001"], features, load_taxonomy())
    assert not length_compatible(styles["s008"], features, load_taxonomy())


def test_invalid_feature_value_rejected() -> None:
    with pytest.raises(FeatureError):
        HandFeatures.from_dict({"length": "eternal"})


def test_unknown_feature_key_rejected() -> None:
    with pytest.raises(FeatureError):
        HandFeatures.from_dict({"nail_color": "red"})
