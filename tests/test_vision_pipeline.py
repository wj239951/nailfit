"""M9：视觉层接进主流程的集成测试（不真的跑 mediapipe，也不依赖手照）。

用 monkeypatch 把 core.vision.extract 换成一个假的 VisionResult，
验证「手照 → 特征 → 推荐」和 API 两个入口的状态码与字段。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import vision
from core.errors import VisionUnusableError
from core.pipeline import features_from_image, recommend_from_image
from core.presets import DEFAULTS


def _fake_observation() -> vision.HandObservation:
    return vision.HandObservation(
        image=Path("fake_hand.jpg"),
        handedness="Right",
        handedness_score=0.98,
        landmarks=[(0.0, 0.0)] * 21,
        image_size=(1000, 1400),
        bbox=(0.0, 0.0, 600.0, 900.0),
        gesture="Open_Palm",
        gesture_score=0.91,
    )


def make_result(
    *,
    quality: str = "ok",
    unreliable: list[str] | None = None,
    metrics: dict[str, float] | None = None,
) -> vision.VisionResult:
    features = {
        "nail_bed_ratio": DEFAULTS["nail_bed_ratio"],
        "nail_shape": DEFAULTS["nail_shape"],
        "length": DEFAULTS["length"],
        "ita_band": DEFAULTS["ita_band"],
        "warmth": DEFAULTS["warmth"],
        "hand_type": DEFAULTS["hand_type"],
    }
    # 真实提取里「不可靠」的字段不会出现在 features 中
    for field in unreliable or []:
        features.pop(field, None)
    return vision.VisionResult(
        observation=_fake_observation(),
        quality=quality,
        features=features,
        confidences={"nail_shape": 0.5, "ita_band": 0.75},
        metrics=metrics or {"ita_degrees": 41.2, "palm_ratio": 1.02, "hand_extension": 0.92},
        notes=["fake result"],
        unreliable=list(unreliable or []),
        preview=None,
    )


@pytest.fixture()
def fake_extract(monkeypatch):
    def _install(result: vision.VisionResult | Exception):
        def fake(image_path, *args, **kwargs):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(vision, "extract", fake)
        return result

    return _install


def test_features_from_image_ok(fake_extract):
    fake_extract(make_result())
    payload, meta = features_from_image("fake_hand.jpg", scene="commute")

    assert payload["scene"] == "commute"
    assert meta["quality"] == "ok"
    assert meta["handedness"] == "Right"
    assert meta["gesture"] == "Open_Palm"
    assert meta["ita_degrees"] == 41.2
    assert meta["unreliable"] == []


def test_features_from_image_drops_unreliable(fake_extract):
    fake_extract(make_result(quality="clenched", unreliable=["nail_shape", "length"]))
    payload, meta = features_from_image("fake_hand.jpg", scene="commute")

    assert "nail_shape" not in payload
    assert "length" not in payload
    assert payload["ita_band"]  # 肤色不受影响
    assert set(meta["unreliable"]) == {"nail_shape", "length"}


def test_features_from_image_overrides_win(fake_extract):
    fake_extract(make_result())
    payload, _ = features_from_image("fake_hand.jpg", overrides={"nail_shape": "oval"})

    assert payload["nail_shape"] == "oval"


def test_recommend_from_image_returns_cards(fake_extract):
    fake_extract(make_result())
    result = recommend_from_image("fake_hand.jpg", scene="commute", use_llm=False)

    assert len(result["recommendations"]) == 3
    assert result["vision"]["quality"] == "ok"
    assert result["vision"]["gesture"] == "Open_Palm"


def test_recommend_from_image_unusable_raises(fake_extract):
    fake_extract(
        make_result(
            quality="clenched",
            unreliable=["nail_bed_ratio", "nail_shape", "length", "hand_type"],
        )
    )
    with pytest.raises(VisionUnusableError):
        recommend_from_image("fake_hand.jpg", scene="commute")


def test_recommend_from_image_detection_error(fake_extract):
    fake_extract(vision.VisionError("没检测到手"))
    with pytest.raises(vision.VisionError):
        recommend_from_image("fake_hand.jpg")


# ------------------------------------------------------------------ API
@pytest.fixture()
def client():
    from api.main import app

    return TestClient(app)


def test_api_vision_extract(client, fake_extract):
    fake_extract(make_result())
    response = client.post("/api/vision/extract", json={"image_path": "fake_hand.jpg"})

    assert response.status_code == 200
    body = response.json()
    assert body["quality"] == "ok"
    assert body["features"]["ita_band"]
    assert body["ita_degrees"] == 41.2


def test_api_vision_extract_422(client, fake_extract):
    fake_extract(vision.VisionError("没检测到手"))
    response = client.post("/api/vision/extract", json={"image_path": "missing.jpg"})

    assert response.status_code == 422
    assert "手照识别失败" in response.json()["detail"]


def test_api_recommend_from_image(client, fake_extract):
    fake_extract(make_result())
    response = client.post(
        "/api/recommend/from-image",
        json={"image_path": "fake_hand.jpg", "scene": "commute"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["recommendations"]) == 3
    assert body["vision"]["quality"] == "ok"


def test_api_recommend_from_image_422_for_bad_photo(client, fake_extract):
    fake_extract(
        make_result(
            quality="pose",
            unreliable=["nail_bed_ratio", "nail_shape", "length", "hand_type"],
        )
    )
    response = client.post(
        "/api/recommend/from-image",
        json={"image_path": "fake_hand.jpg", "scene": "commute"},
    )

    assert response.status_code == 422
    assert "手照信息不足" in response.json()["detail"]


def test_features_from_image_ignores_unknown_overrides(fake_extract):
    """前端可能把 ita_degrees 等派生字段当修正回传，不能塞进 HandFeatures。"""
    fake_extract(make_result())
    payload, _ = features_from_image(
        "fake_hand.jpg", overrides={"ita_degrees": "88", "bogus": "x"}
    )

    assert payload["ita_degrees"] == 41.2  # 仍用视觉指标，不被覆盖
    assert "bogus" not in payload
