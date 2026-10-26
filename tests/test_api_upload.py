"""上传接口与静态资源挂载的 API 测试（M28，供 Vue 前端联调）。"""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_static_image_is_served() -> None:
    """Vue 前端用 /static/... 同源加载款式图，必须能取到。"""
    r = client.get("/static/styles/s001.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] in {"image/jpeg", "image/jpg"}
    assert len(r.content) > 1000


def test_root_reports_static_mount() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["static"].startswith("/static")


def test_upload_rejects_empty_body() -> None:
    r = client.post(
        "/api/vision/upload",
        content=b"",
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 422
    assert "上传内容为空" in r.json()["detail"]


def test_upload_rejects_non_image_bytes() -> None:
    r = client.post(
        "/api/vision/upload",
        content=b"not-an-image",
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 422
