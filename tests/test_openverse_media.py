"""M26 / M27 新增能力的测试：Openverse 候选抓取、样例库占位图、首页图廊。

这些测试不需要网络：
- Openverse 用 FakeClient 回放 API 响应，覆盖许可/尺寸/相关性过滤与候选清单；
- 占位图用 PIL 真画到 tmp_path，验证尺寸、幂等与 --force；
- 图廊只读仓库里真实存在的样例库图片。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import scripts.openverse_candidates as candidates_script
from core.media import (
    OPENVERSE_LICENSES,
    OpenverseProvider,
    ProviderError,
    openverse_queries,
)
from core.styles import load_styles_json
from core.ui_view import gallery_styles
from scripts.make_sample_images import build as build_sample_images
from scripts.make_sample_images import draw_card
from scripts.validate_media import validate_media_styles

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "styles.sample.json"

STYLE = {
    "id": "d001",
    "name": "裸粉 · 法式椭圆",
    "color_family": "nude_pink",
    "style": "french",
    "shape": ["oval"],
    "tone": "warm",
    "value": "light",
}


# ---------------------------------------------------------------- 测试替身


class FakeResp:
    def __init__(
        self,
        *,
        payload: dict | None = None,
        content: bytes = b"",
        status_code: int = 200,
        content_type: str = "application/json",
    ) -> None:
        self._payload = payload
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("响应不是 JSON")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responses: list[FakeResp]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, **kwargs) -> FakeResp:
        self.calls.append(("GET", url))
        return self.responses.pop(0)

    def post(self, url: str, **kwargs) -> FakeResp:
        self.calls.append(("POST", url))
        return self.responses.pop(0)


def _ov_item(**overrides) -> dict:
    base = {
        "title": "Nude French Manicure with Oval Nails",
        "url": "https://images.example/1.jpg",
        "foreign_landing_url": "https://example.org/photos/1",
        "license": "cc0",
        "license_version": "1.0",
        "attribution": "Photo by Jane (CC0)",
        "creator": "Jane",
        "source": "flickr",
        "category": "photograph",
        "width": 1200,
        "height": 1600,
        "tags": [{"name": "nails"}],
    }
    base.update(overrides)
    return base


def _search_payload(*items: dict) -> FakeResp:
    return FakeResp(payload={"result_count": len(items), "results": list(items)}, content=b"")


JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


# ---------------------------------------------------------------- Openverse 检索


def test_openverse_queries_specific_then_falls_back():
    queries = openverse_queries(STYLE)
    # 风格词本身就是 "french manicure"，所以首条查询带 manicure、不再补 "nails"
    assert queries[0] == "nude pink french manicure oval"
    assert "nude pink nails" in queries
    assert "nails" in queries
    assert len(queries) == len(set(queries)), "查询链不应有重复"
    # 没有可用字段时也能退到最宽泛的查询
    assert openverse_queries({"id": "x"}) == ["nails"]


def test_openverse_provider_filters_by_license_size_and_relevance():
    items = [
        _ov_item(),  # 合法：CC0、尺寸够、标题相关
        _ov_item(url="https://images.example/nc.jpg", license="by-nc", title="nude nails"),
        _ov_item(url="https://images.example/small.jpg", width=200, height=260),
        _ov_item(url="https://images.example/cat.jpg", title="Cat Processing 101", tags=[]),
    ]
    client = FakeClient([_search_payload(*items), _search_payload(*items), _search_payload(*items)])
    provider = OpenverseProvider(client=client, root=ROOT, timeout=1.0)

    found = provider.search(STYLE, limit=3)

    assert [item["image_url"] for item in found] == ["https://images.example/1.jpg"]
    assert found[0]["license_detail"] == "CC CC0 1.0"
    assert found[0]["creator"] == "Jane"
    assert found[0]["foreign_landing_url"] == "https://example.org/photos/1"


def test_openverse_provider_downloads_candidates(tmp_path):
    client = FakeClient(
        [
            _search_payload(_ov_item()),
            FakeResp(content=JPEG, content_type="image/jpeg"),
        ]
    )
    provider = OpenverseProvider(client=client, root=ROOT, timeout=1.0)

    records = provider.candidates(STYLE, limit=1, out_dir=tmp_path / "openverse")

    assert len(records) == 1
    assert records[0]["rank"] == 1
    local = Path(str(records[0]["local_image"]))
    assert local.is_file()
    assert local.parent.name == "d001"


def test_openverse_provider_raises_provider_error_on_http_failure():
    client = FakeClient([FakeResp(status_code=500, payload={}), FakeResp(status_code=500, payload={})])
    provider = OpenverseProvider(client=client, root=ROOT, timeout=1.0, retries=1)
    with pytest.raises(ProviderError):
        provider.search(STYLE, limit=1)


def test_openverse_relevance_requires_nail_token():
    provider = OpenverseProvider(client=FakeClient([]), root=ROOT)
    assert provider._candidate(STYLE, _ov_item(title="Cat Processing 101", tags=[])) is None
    candidate = provider._candidate(STYLE, _ov_item())
    assert candidate is not None and candidate["relevance"] >= 2.0


# ---------------------------------------------------------------- 候选脚本


def test_collect_candidates_records_style_and_review_state(tmp_path):
    provider = OpenverseProvider(
        client=FakeClient(
            [
                _search_payload(_ov_item()),
                _search_payload(_ov_item()),
                _search_payload(_ov_item()),
                FakeResp(content=JPEG, content_type="image/jpeg"),
            ]
        ),
        root=ROOT,
        timeout=1.0,
    )
    candidates, searched = candidates_script.collect_candidates(
        [STYLE], out_dir=tmp_path, per_style=2, limit=1, provider=provider, logger=lambda _msg: None
    )

    assert searched == 1
    assert len(candidates) == 1
    assert candidates[0]["style_id"] == "d001"
    assert candidates[0]["style_name"] == STYLE["name"]
    assert candidates[0]["review"]["status"] == "pending"


def test_openverse_candidates_main_writes_manifest(tmp_path, monkeypatch, capsys):
    styles_file = tmp_path / "styles.json"
    styles_file.write_text(json.dumps({"styles": [STYLE]}, ensure_ascii=False), encoding="utf-8")
    fake_client = FakeClient(
        [
            _search_payload(_ov_item()),
            FakeResp(content=JPEG, content_type="image/jpeg"),
        ]
    )
    monkeypatch.setattr(
        candidates_script,
        "OpenverseProvider",
        lambda **kwargs: OpenverseProvider(client=fake_client, root=ROOT, timeout=1.0),
    )

    rc = candidates_script.main(
        [
            "--styles",
            str(styles_file),
            "--out",
            str(tmp_path / "cache"),
            "--limit",
            "1",
            "--per-style",
            "1",
            "--json",
        ]
    )
    capsys.readouterr()

    assert rc == 0
    manifest_path = tmp_path / "cache" / "candidates.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["provider"] == "openverse"
    assert manifest["candidate_count"] == 1
    assert manifest["licenses"] == list(OPENVERSE_LICENSES)
    assert manifest["candidates"][0]["style_id"] == "d001"
    assert "人工复核" in manifest["review_note"]


def test_openverse_candidates_main_returns_1_when_empty(tmp_path, monkeypatch, capsys):
    styles_file = tmp_path / "styles.json"
    styles_file.write_text(json.dumps({"styles": [STYLE]}, ensure_ascii=False), encoding="utf-8")
    fake_client = FakeClient([_search_payload(), _search_payload(), _search_payload()])
    monkeypatch.setattr(
        candidates_script,
        "OpenverseProvider",
        lambda **kwargs: OpenverseProvider(client=fake_client, root=ROOT, timeout=1.0),
    )

    rc = candidates_script.main(
        ["--styles", str(styles_file), "--out", str(tmp_path / "cache"), "--limit", "1"]
    )
    capsys.readouterr()

    assert rc == 1
    manifest = json.loads((tmp_path / "cache" / "candidates.json").read_text(encoding="utf-8"))
    assert manifest["candidate_count"] == 0


# ---------------------------------------------------------------- 校验脚本


def test_validate_media_accepts_openverse_license():
    style = {
        "id": "o001",
        "brand": "Openverse",
        "description": "CC0 候选图",
        "search_query": "nude nails",
        "media": {
            "image": "static/refs/o001.jpg",
            "source_url": "https://example.org/photos/1",
            "license": "openverse",
            "provider": "openverse",
            "relevance": 3.0,
        },
    }
    errors, _stats = validate_media_styles([style], check_images=False)
    assert errors == []


# ---------------------------------------------------------------- 占位图生成


def _style_with_image(tmp_path: Path) -> dict:
    return {**STYLE, "media": {"image": "static/styles/s001.jpg", "license": "demo"}}


def test_sample_image_build_creates_card_and_is_idempotent(tmp_path):
    style = _style_with_image(tmp_path)

    first = build_sample_images([style], root=tmp_path)
    assert first["created"] == 1 and not first["failed"]
    image_path = tmp_path / "static" / "styles" / "s001.jpg"
    assert image_path.is_file()
    with Image.open(image_path) as img:
        assert img.size == (768, 1024)

    second = build_sample_images([style], root=tmp_path)
    assert second["created"] == 0 and second["skipped"] == 1

    third = build_sample_images([style], root=tmp_path, force=True)
    assert third["created"] == 1


def test_sample_image_dry_run_writes_nothing(tmp_path):
    style = _style_with_image(tmp_path)
    result = build_sample_images([style], root=tmp_path, dry_run=True)
    assert result["created"] == 1
    assert not (tmp_path / "static" / "styles" / "s001.jpg").exists()


def test_draw_card_returns_image():
    card = draw_card(STYLE)
    assert card.size == (768, 1024)
    assert card.mode == "RGB"


def test_sample_library_images_all_exist():
    styles = load_styles_json(SAMPLE)
    assert len(styles) >= 15
    missing = []
    for style in styles:
        image = (style.get("media") or {}).get("image") or style.get("image") or ""
        if not (ROOT / str(image)).is_file():
            missing.append(str(style["id"]))
    assert missing == [], f"样例库缺图：{missing}"


# ---------------------------------------------------------------- 首页图廊


def test_gallery_styles_returns_only_images_that_exist():
    items = gallery_styles("data/styles.sample.json", limit=8)
    assert len(items) == 8
    for item in items:
        assert item["image"].is_file()
        assert item["caption"]
        assert item["name"]


def test_gallery_styles_limit_and_missing_library():
    assert gallery_styles(None) == []
    assert gallery_styles("data/does-not-exist.json") == []
    assert len(gallery_styles("data/styles.sample.json", limit=0)) >= 15
    assert len(gallery_styles("data/styles.sample.json", limit=3)) == 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
