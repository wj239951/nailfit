"""M18 评测脚本单测（不打真 LLM）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.data import load_styles, load_taxonomy
from core.features import HandFeatures
from eval import run as evalrun

ROOT = Path(__file__).resolve().parent.parent
STYLES = load_styles()
TAXONOMY = load_taxonomy()
STYLE_MAP = evalrun.styles_index(STYLES)
CASES = evalrun.load_cases()


def _rec(style_id: str, tier: str = "safe", family: str | None = None) -> dict:
    style = STYLE_MAP[style_id]
    return {
        "style_id": style_id,
        "tier": tier,
        "color_family": family or style["color_family"],
        "reason": "测试理由",
    }


def _scratch_dir() -> Path:
    """测试临时目录：放项目内（沙箱下系统 TEMP 不可写）。"""
    path = ROOT / "tests" / "_tmp_eval"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_cases_file_valid():
    assert len(CASES) >= 6
    for case in CASES:
        HandFeatures.from_dict(case["features"])
        if case.get("known_gap"):
            assert isinstance(case["known_gap"], str)
        else:
            assert case.get("expect"), f"{case['id']} 既没有 expect 也没有 known_gap"


def test_load_cases_rejects_duplicate_ids():
    import json
    import shutil

    path = _scratch_dir() / "cases.json"
    try:
        payload = {"cases": [{"id": "x", "features": CASES[0]["features"]}] * 2}
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="重复"):
            evalrun.load_cases(path)
    finally:
        shutil.rmtree(_scratch_dir(), ignore_errors=True)


def test_contract_passes_on_real_recommendation():
    result = evalrun.recommend(HandFeatures.from_dict(CASES[0]["features"]), use_llm=False, styles=STYLES)
    assert evalrun.check_contract(result["recommendations"], STYLE_MAP, TAXONOMY) == []


def test_contract_catches_bad_cards():
    recs = [
        _rec("s001"),
        _rec("s002", family="nude_pink"),  # 色系重复
        {"style_id": "s999", "tier": "safe", "color_family": "berry", "reason": ""},
    ]
    issues = evalrun.check_contract(recs, STYLE_MAP, TAXONOMY)
    assert any("color_family 重复" in issue for issue in issues)
    assert any("style_id 不存在" in issue for issue in issues)
    assert any("reason 为空" in issue for issue in issues)


def test_contract_accepts_extra_and_fill_tiers():
    recs = [_rec("s001"), _rec("s002", tier="extra"), _rec("s003", tier="fill")]
    assert evalrun.check_contract(recs, STYLE_MAP, TAXONOMY) == []


def test_fit_strict_only_checks_safe_tier():
    expect = {"tone": ["warm", "neutral"], "strict_tiers": ["safe"]}
    features = HandFeatures.from_dict(CASES[0]["features"])
    # s003 是冷调：safe 档要报错，highlight 档不报
    safe_card = _rec("s003", tier="safe")
    highlight_card = _rec("s003", tier="highlight")
    assert evalrun.check_fit(safe_card, STYLE_MAP["s003"], expect, features)
    assert evalrun.check_fit(highlight_card, STYLE_MAP["s003"], expect, features) == []


def test_fit_forbid_applies_to_all_tiers():
    expect = {"forbid_families": ["berry"]}
    features = HandFeatures.from_dict(CASES[0]["features"])
    for tier in ("safe", "highlight", "bold"):
        card = _rec("s003", tier=tier)
        issues = evalrun.check_fit(card, STYLE_MAP["s003"], expect, features)
        assert any("在禁止项" in issue for issue in issues)


def test_hue_gap_circular():
    assert evalrun._hue_gap(350, 10) == pytest.approx(20)
    assert evalrun._hue_gap(0, 180) == pytest.approx(180)
    assert evalrun._hue_gap(30, 30) == pytest.approx(0)


def test_evaluate_case_returns_expected_fields():
    item = evalrun.evaluate_case(CASES[0], STYLES, TAXONOMY, STYLE_MAP, runs=1)
    for key in (
        "contract_ok",
        "fit_ok",
        "scene_hit_rate",
        "tier_coverage",
        "hue_spread",
        "hue_ok",
        "stability",
        "jitter_change_rate",
        "known_gap",
    ):
        assert key in item
    assert item["contract_ok"] is True
    assert item["tier_coverage"] == 3


def test_summary_separates_known_gaps():
    gap_case = dict(CASES[0])
    gap_case["id"] = "c-synthetic-gap"
    gap_case["known_gap"] = "synthetic known gap for test"
    report = evalrun.evaluate([CASES[0], gap_case], STYLES, TAXONOMY, runs=1)
    summary = report["summary"]
    assert summary["cases"] == 2
    assert summary["known_gap_cases"] == 1
    assert summary["fit_pass_rate"] == pytest.approx(1.0)


def test_jitter_change_rate_detects_change(monkeypatch):
    features = HandFeatures.from_dict(CASES[0]["features"])

    def fake_recommend(feats, **kwargs):
        # 暖调被挪走后 top-1 变化，其余抖动保持
        top = "s005" if feats.warmth != "warm" else "s001"
        return {"recommendations": [{"style_id": top}]}

    monkeypatch.setattr(evalrun, "recommend", fake_recommend)
    rate = evalrun.jitter_change_rate(features, TAXONOMY, STYLES, baseline_top1="s001")
    assert 0 < rate <= 1


def test_llm_metrics_computes_valid_rate(monkeypatch):
    def fake_recommend(feats, **kwargs):
        return {
            "recommendations": [{"style_id": "s001", "tier": "safe", "color_family": "nude_pink", "reason": "r"}] * 3,
            "meta": {"explainer": {"degraded": False, "llm_cards": 3}},
        }

    monkeypatch.setattr(evalrun, "recommend", fake_recommend)
    metrics = evalrun._llm_metrics(CASES, STYLES, STYLE_MAP, TAXONOMY, limit=2)
    assert metrics["cases"] == 2
    assert metrics["valid_rate"] == pytest.approx(1.0)
    assert metrics["degraded_cases"] == 0
    # 契约重复色系 → 记录错误但不中断
    assert metrics["errors"]


def test_main_strict_returns_zero_for_current_cases(capsys):
    exit_code = evalrun.main(["--no-report", "--strict", "--runs", "1"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "契约通过" in captured.out


# --------------------------------------------------------------------------- #
# M19：手照视觉层指标
# --------------------------------------------------------------------------- #


def _photo_case(**overrides) -> dict:
    case = {
        "id": "m19-test",
        "name": "测试手照",
        "source": "hand_photo",
        "image": "raw_hands/fake.jpg",
        "features": {
            "ita_band": "light",
            "warmth": "warm",
            "scene": "commute",
            "hand_type": "standard",
            "nail_bed_ratio": "standard",
            "nail_shape": "round",
            "length": "short",
        },
        "expect": {"tone": ["warm", "neutral"]},
    }
    case.update(overrides)
    return case


def _fake_result(features: dict, quality: str = "ok"):
    from types import SimpleNamespace

    return SimpleNamespace(features=features, quality=quality)


def test_load_cases_rejects_unknown_source():
    import json
    import shutil

    path = _scratch_dir() / "cases.json"
    try:
        payload = {"cases": [{"id": "x", "features": CASES[0]["features"], "source": "camera"}]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="source 非法"):
            evalrun.load_cases(path)
    finally:
        shutil.rmtree(_scratch_dir(), ignore_errors=True)


def test_load_cases_requires_image_for_hand_photo():
    import json
    import shutil

    path = _scratch_dir() / "cases.json"
    try:
        payload = {"cases": [{"id": "x", "features": CASES[0]["features"], "source": "hand_photo"}]}
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="没有 image"):
            evalrun.load_cases(path)
    finally:
        shutil.rmtree(_scratch_dir(), ignore_errors=True)


def test_check_vision_accuracy_and_detection():
    case = _photo_case()
    calls: list[Path] = []

    def fake_extract(image_path):
        calls.append(image_path)
        return _fake_result(dict(case["features"]))  # 与标注完全一致

    vision = evalrun.check_vision([case], root=ROOT, extract=fake_extract)
    assert vision["cases"] == 1
    assert vision["detected"] == 1
    assert vision["detection_rate"] == 1.0
    assert set(vision["accuracy"]) == set(evalrun.VISION_FIELDS)
    assert all(rate == 1.0 for rate in vision["accuracy"].values())
    assert calls and calls[0].name == "fake.jpg"


def test_check_vision_only_counts_fields_vision_returns():
    case = _photo_case()
    # 只看肤色：姿态不合格时几何字段不输出，分母应只算肤色
    vision = evalrun.check_vision(
        [case],
        root=ROOT,
        extract=lambda _path: _fake_result({"ita_band": "light", "warmth": "neutral"}, quality="clenched"),
    )
    assert set(vision["accuracy"]) == {"ita_band", "warmth"}
    assert vision["accuracy"]["ita_band"] == 1.0
    assert vision["accuracy"]["warmth"] == 0.0
    assert vision["per_case"][0]["matches"]["warmth"] is False


def test_check_vision_reports_failed_extraction():
    case = _photo_case()

    def boom(_path):
        raise RuntimeError("no hand")

    vision = evalrun.check_vision([case], root=ROOT, extract=boom)
    assert vision["detected"] == 0
    assert vision["detection_rate"] == 0.0
    assert "no hand" in vision["per_case"][0]["error"]


def test_evaluate_counts_hand_photo_cases():
    report = evalrun.evaluate([_photo_case()], STYLES, TAXONOMY, runs=1)
    assert report["summary"]["hand_photo_cases"] == 1
    assert "vision" not in report


def test_evaluate_case_handles_recommend_error(monkeypatch):
    from core.validator import ContractError

    def boom(*_args, **_kwargs):
        raise ContractError("三条推荐的色系重复: nude_pink")

    monkeypatch.setattr(evalrun, "recommend", boom)
    item = evalrun.evaluate_case(CASES[0], STYLES, TAXONOMY, STYLE_MAP, runs=1)
    assert item["contract_ok"] is False
    assert "推荐失败" in item["contract_issues"][0]
    assert item["error"]


def test_main_vision_flag(monkeypatch, capsys):
    monkeypatch.setattr(
        evalrun,
        "check_vision",
        lambda cases, **kwargs: {
            "cases": 1,
            "detected": 1,
            "detection_rate": 1.0,
            "accuracy": {"ita_band": 1.0},
            "per_case": [],
        },
    )
    exit_code = evalrun.main(["--no-report", "--runs", "1", "--vision"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "视觉层：检测 1/1" in captured.out
