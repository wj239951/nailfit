"""解释层（M17）单测：全部走 mock，不访问网络。"""

from __future__ import annotations

import json

import httpx
import pytest

from core import explainer
from core.features import HandFeatures
from core.pipeline import recommend
from core.presets import SCENARIOS
from core.validator import MAX_REASON_CHARS

FEATURES = HandFeatures.from_dict(SCENARIOS["short_wide_warm"])
GOOD_REASON = "这款方圆甲在短甲上显得干净利落，裸调能衬出你的浅暖肤色。"


def _candidate_ids(messages: list[dict[str, str]]) -> list[str]:
    user = json.loads(messages[1]["content"])
    return [item["style_id"] for item in user["candidates"]]


@pytest.fixture()
def fake_llm(monkeypatch):
    """记录调用次数，并返回给定构造的 JSON。"""
    calls: list[dict] = []

    def _install(payload_builder):
        def fake_call(messages, **kwargs):
            calls.append(kwargs)
            return payload_builder(_candidate_ids(messages))

        monkeypatch.setattr(explainer, "_call_llm", fake_call)
        return calls

    return _install


def _full_payload(ids: list[str]) -> dict:
    return {
        "recommendations": [
            {"style_id": sid, "reason": f"{GOOD_REASON}（{sid}）", "caution": None}
            for sid in ids
        ],
        "avoid": ["短甲先别做长款"],
    }


def test_llm_success_sets_mode_and_meta(fake_llm):
    fake_llm(_full_payload)
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": "sk-test"})
    meta = payload["meta"]["explainer"]
    assert meta["mode"] == "llm"
    assert meta["degraded"] is False
    assert meta["llm_cards"] == 3
    assert meta["model"]
    for card in payload["recommendations"]:
        assert GOOD_REASON in card["reason"]


def test_missing_key_degrades_to_template(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": ""})
    meta = payload["meta"]["explainer"]
    assert meta["mode"] == "template"
    assert meta["degraded"] is True
    assert "DEEPSEEK_API_KEY" in meta["error"]
    assert len(payload["recommendations"]) == 3


def test_call_error_degrades_to_template(monkeypatch):
    def boom(messages, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(explainer, "_call_llm", boom)
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": "sk-test"})
    meta = payload["meta"]["explainer"]
    assert meta["mode"] == "template"
    assert meta["degraded"] is True
    assert "ConnectError" in meta["error"]


def test_partial_and_unknown_ids_fall_back(fake_llm):
    fake_llm(
        lambda ids: {
            "recommendations": [
                {"style_id": ids[0], "reason": GOOD_REASON, "caution": None},
                {"style_id": "s999", "reason": "编造款式", "caution": None},
            ],
            "avoid": [],
        }
    )
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": "sk-test"})
    meta = payload["meta"]["explainer"]
    assert meta["llm_cards"] == 1
    assert meta["degraded"] is True
    assert "回退模板" in meta["error"]
    # 未返回的两条仍由模板兜底，且不会出现编造的 s999
    assert [card["style_id"] for card in payload["recommendations"]] != ["s999"]


def test_overlong_reason_is_clamped(fake_llm):
    fake_llm(
        lambda ids: {
            "recommendations": [
                {"style_id": sid, "reason": "很" * (MAX_REASON_CHARS * 3), "caution": None}
                for sid in ids
            ],
            "avoid": ["长" * 200],
        }
    )
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": "sk-test"})
    for card in payload["recommendations"]:
        assert 0 < len(card["reason"]) <= MAX_REASON_CHARS
    assert all(len(tip) <= explainer.MAX_AVOID_CHARS for tip in payload["avoid"])
    assert len(payload["avoid"]) <= explainer.MAX_AVOID_ITEMS


def test_use_llm_false_never_calls_model(monkeypatch):
    calls = []

    def boom(messages, **kwargs):  # pragma: no cover - 不应被调用
        calls.append(messages)
        raise AssertionError("use_llm=False 时不应该调用模型")

    monkeypatch.setattr(explainer, "_call_llm", boom)
    payload = recommend(FEATURES, use_llm=False)
    meta = payload["meta"]["explainer"]
    assert meta["mode"] == "template"
    assert meta["degraded"] is False
    assert calls == []


def test_call_llm_retries_without_response_format(monkeypatch):
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    bad = httpx.Response(400, request=request)
    good = httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(_full_payload(["s001", "s002", "s003"]))}}]},
        request=request,
    )
    sent: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(dict(json or {}))
        return bad if len(sent) == 1 else good

    monkeypatch.setattr(explainer.httpx, "post", fake_post)
    data = explainer._call_llm(
        explainer.build_messages(FEATURES, [], []),
        api_key="sk-test",
        base_url="http://127.0.0.1:11434/v1",
        model="deepseek-r1:7b",
        timeout=5,
    )
    assert data["recommendations"]
    assert "response_format" in sent[0]
    assert "response_format" not in sent[1]


def test_retry_fills_missing_ids(monkeypatch):
    calls = {"n": 0}
    captured: list[list[dict]] = []

    def fake(messages, **kwargs):
        calls["n"] += 1
        captured.append(messages)
        ids = _candidate_ids(messages)
        if calls["n"] == 1:
            return {"recommendations": [{"style_id": ids[0], "reason": GOOD_REASON, "caution": None}]}
        return _full_payload(ids)

    monkeypatch.setattr(explainer, "_call_llm", fake)
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": "sk-test"})
    meta = payload["meta"]["explainer"]
    assert calls["n"] == 2
    assert meta["mode"] == "llm"
    assert meta["degraded"] is False
    assert meta["llm_cards"] == 3
    # 第二次调用带上了“缺失 style_id”反馈
    repair_prompt = captured[1][-1]["content"]
    assert "style_id" in repair_prompt


def test_retry_error_keeps_first_partial_result(monkeypatch):
    calls = {"n": 0}

    def fake(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            ids = _candidate_ids(messages)
            return {"recommendations": [{"style_id": ids[0], "reason": GOOD_REASON, "caution": None}]}
        raise httpx.ReadTimeout("slow model")

    monkeypatch.setattr(explainer, "_call_llm", fake)
    payload = recommend(FEATURES, use_llm=True, explainer_kwargs={"api_key": "sk-test"})
    meta = payload["meta"]["explainer"]
    assert meta["mode"] == "llm"
    assert meta["llm_cards"] == 1
    assert meta["degraded"] is True
    assert "ReadTimeout" in meta["error"]


def test_pipeline_meta_always_has_explainer():
    payload = recommend(FEATURES, use_llm=False)
    assert payload["meta"]["explainer"]["mode"] == "template"
