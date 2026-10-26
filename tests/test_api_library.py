"""款式库选择（sample / demo）的 API 测试。

前端需要切换「样例库（15 款占位图）」与「演示库（43 款真实截图）」，
这里验证接口层的库选择参数、错误码与推荐链路。
"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_styles_default_is_sample_library() -> None:
    r = client.get("/api/styles")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 15
    assert body["styles"][0]["id"] == "s001"


def test_styles_demo_library() -> None:
    r = client.get("/api/styles", params={"library": "demo"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 15
    assert body["styles"][0]["id"].startswith("d")


def test_styles_unknown_library_422() -> None:
    r = client.get("/api/styles", params={"library": "nope"})
    assert r.status_code == 422
    assert "未知款式库" in r.json()["detail"]


def _payload(**overrides: object) -> dict:
    payload: dict = {
        "features": {
            "nail_bed_ratio": "short_wide",
            "nail_shape": "squoval",
            "length": "short",
            "ita_band": "light",
            "warmth": "warm",
            "hand_type": "fleshy",
            "scene": "commute",
        },
        "use_llm": False,
    }
    payload.update(overrides)
    return payload


def test_recommend_with_demo_library() -> None:
    r = client.post("/api/recommend", json=_payload(library="demo"))
    assert r.status_code == 200
    body = r.json()
    assert len(body["recommendations"]) == 3
    # 三档推荐必须来自演示库（d 编号），不能混入样例库
    assert all(card["style_id"].startswith("d") for card in body["recommendations"])


def test_recommend_unknown_library_422() -> None:
    r = client.post("/api/recommend", json=_payload(library="nope"))
    assert r.status_code == 422
    assert "未知款式库" in r.json()["detail"]
