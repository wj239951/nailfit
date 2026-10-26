"""媒体解析层（M24）测试：Provider / 缓存 / 降级 / 校验 / 预取。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core.media import (
    LICENSES,
    LocalProvider,
    MediaResolver,
    PexelsProvider,
    ProviderError,
    SearchProvider,
    empty_media,
    media_caption,
    media_image_path,
    resolve_card_media,
)
from core.data import load_taxonomy
from core.presets import SCENARIOS
from core.styles import check_images, load_styles_json, validate_styles
from core.ui_view import card_view, generate
from scripts.migrate_styles_v2 import migrate_style
from scripts.prefetch_media import main as prefetch_main
from scripts.validate_media import validate_media_styles

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "styles.demo.json"
LOCAL_IMAGE = "static/demo/demo01_nude_french.jpg"


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


def _demo_entries() -> list[dict]:
    raw = json.loads(DEMO.read_text(encoding="utf-8"))
    return raw.get("styles") or []


# ---------------------------------------------------------------- 数据契约


def test_demo_library_is_schema_v2():
    raw = json.loads(DEMO.read_text(encoding="utf-8"))
    assert raw.get("version") == 2
    entries = _demo_entries()
    assert len(entries) >= 40
    for style in entries:
        for field in ("brand", "description", "search_query"):
            assert isinstance(style.get(field), str) and style[field].strip(), style.get("id")
        media = style.get("media")
        assert isinstance(media, dict), style.get("id")
        assert media.get("license") in LICENSES
        assert str(media.get("image") or "").startswith("static/"), style.get("id")


def test_demo_library_still_passes_schema_validation():
    styles = load_styles_json(DEMO)
    assert validate_styles(styles, load_taxonomy()) == []
    assert check_images(styles, ROOT) == []


def test_validate_media_demo_library_is_clean():
    errors, stats = validate_media_styles(load_styles_json(DEMO), check_images=True)
    assert errors == []
    assert stats["with_image"] == stats["total"]


def test_validate_media_rejects_bad_license_and_relevance():
    style = {
        "id": "bad001",
        "name": "坏条目",
        "brand": "演示素材",
        "description": "描述",
        "search_query": "查询词",
        "tier": "safe",
        "media": {
            "image": None,
            "source_url": None,
            "license": "nope",
            "provider": "none",
            "relevance": 9,
        },
    }
    errors, _ = validate_media_styles([style], check_images=False)
    joined = "\n".join(errors)
    assert "license" in joined
    assert "relevance" in joined


def test_validate_media_requires_source_url_for_web_license():
    style = {
        "id": "bad002",
        "name": "坏条目",
        "brand": "演示素材",
        "description": "描述",
        "search_query": "查询词",
        "tier": "safe",
        "media": {
            "image": "cache/refs/d001.jpg",
            "source_url": None,
            "license": "pexels",
            "provider": "pexels",
        },
    }
    errors, _ = validate_media_styles([style], check_images=False)
    joined = "\n".join(errors)
    assert "source_url" in joined
    assert "static/" in joined


def test_migrate_style_is_idempotent():
    source = next(entry for entry in _demo_entries() if entry.get("image"))
    base = copy.deepcopy(source)
    for field in ("brand", "description", "search_query", "media"):
        base.pop(field, None)

    assert migrate_style(base, kind="demo", fetched_at="2026-10-26") is True
    once = copy.deepcopy(base)
    assert migrate_style(base, kind="demo", fetched_at="2026-10-26") is False

    for field in ("brand", "description", "search_query"):
        assert once[field].strip()
    assert once["media"]["image"] == source["image"]
    assert once["media"]["license"] == "demo"
    assert base["media"]["image"] == once["media"]["image"]
    assert base["search_query"] == once["search_query"]
    assert base["brand"] == once["brand"]


# ---------------------------------------------------------------- 媒体模型


def test_empty_media_is_placeholder():
    media = empty_media()
    assert media["image"] is None
    assert media["license"] == "placeholder"
    assert media["provider"] == "none"
    assert media["verified"] is False


def test_media_caption_variants():
    assert media_caption(empty_media()) == "暂无参考图 · 仅展示文字推荐"
    assert media_caption({"license": "demo", "image": LOCAL_IMAGE}) == (
        "工程演示素材 · 仅风格参考，非本手模拟效果"
    )
    assert media_caption({"license": "pexels", "image": "cache/refs/x.jpg"}) == (
        "图片：Pexels（可商用） · 仅风格参考，非本手模拟效果"
    )
    assert media_caption({"license": "unknown", "image": "cache/refs/x.jpg"}) == (
        "图片来自网络（公开网页）· 仅风格参考，非本手模拟效果"
    )


def test_media_image_path_only_accepts_existing_static_files():
    assert media_image_path({"image": LOCAL_IMAGE}) == (ROOT / LOCAL_IMAGE).resolve()
    assert media_image_path({"image": "cache/refs/x.jpg"}) is None
    assert media_image_path({"image": "static/demo/does-not-exist.jpg"}) is None


# ---------------------------------------------------------------- Provider


def test_local_provider_resolves_existing_image():
    provider = LocalProvider(ROOT)
    media = provider.resolve({"id": "d001", "media": {"image": LOCAL_IMAGE, "license": "demo"}})
    assert media is not None
    assert media.image == LOCAL_IMAGE
    assert media.provider == "local"
    assert media.license == "demo"
    assert media.verified is True
    assert provider.resolve({"id": "d002", "media": {"image": "static/demo/nope.jpg"}}) is None


def test_providers_raise_without_api_key(tmp_path):
    client = FakeClient([])
    with pytest.raises(ProviderError):
        PexelsProvider("", client=client, root=tmp_path).resolve(
            {"id": "x", "search_query": "裸色美甲"}
        )
    with pytest.raises(ProviderError):
        SearchProvider("", client=client, root=tmp_path).resolve(
            {"id": "x", "search_query": "裸色美甲"}
        )


def test_pexels_provider_downloads_first_photo(tmp_path):
    search = FakeResp(
        payload={
            "photos": [
                {
                    "src": {"portrait": "https://images.pexels.com/photos/1/p.jpg"},
                    "url": "https://www.pexels.com/photo/1/",
                }
            ]
        }
    )
    image = FakeResp(content=b"jpeg-bytes", content_type="image/jpeg")
    client = FakeClient([search, image])
    provider = PexelsProvider(
        "key", timeout=1, client=client, refs_dir=tmp_path / "refs", root=tmp_path
    )
    media = provider.resolve({"id": "d001", "search_query": "nude nail"})

    assert media is not None
    assert media.license == "pexels"
    assert media.provider == "pexels"
    assert media.source_url == "https://www.pexels.com/photo/1/"
    assert media.image == "refs/d001.jpg"
    assert (tmp_path / media.image).read_bytes() == b"jpeg-bytes"
    assert client.calls[0][0] == "GET"


def test_search_provider_extracts_first_image(tmp_path):
    search = FakeResp(
        payload={
            "results": [
                {
                    "url": "https://www.xiaohongshu.com/explore/1",
                    "authority": 4,
                    "rerank_score": 2.3,
                    "site_name": "小红书",
                }
            ]
        }
    )
    fetch = FakeResp(payload={"content": "正文 ![参考图](https://cdn.example.com/nail.jpg) 后文"})
    image = FakeResp(content=b"jpg-bytes", content_type="image/jpeg")
    client = FakeClient([search, fetch, image])
    provider = SearchProvider(
        "key", timeout=1, client=client, refs_dir=tmp_path / "refs", root=tmp_path
    )
    media = provider.resolve({"id": "d001", "search_query": "温柔裸色甲"})

    assert media is not None
    assert media.license == "unknown"
    assert media.provider == "search"
    assert media.source_url == "https://www.xiaohongshu.com/explore/1"
    assert media.relevance == 2.3
    assert (tmp_path / media.image).is_file()
    assert any("tools/search" in url for _, url in client.calls)


def test_search_provider_skips_low_authority_results(tmp_path):
    search = FakeResp(
        payload={"results": [{"url": "https://a.example.com/x", "authority": 1, "rerank_score": 3.0}]}
    )
    client = FakeClient([search])
    provider = SearchProvider("key", client=client, root=tmp_path, refs_dir=tmp_path / "refs")

    assert provider.resolve({"id": "d001", "search_query": "甲型"}) is None
    assert len(client.calls) == 1  # 没有进入 Fetch


# ---------------------------------------------------------------- Resolver


def test_resolver_caches_local_media(tmp_path):
    cache = tmp_path / "media_cache.json"
    resolver = MediaResolver(cache_path=cache)
    style = {"id": "d001", "media": {"image": LOCAL_IMAGE, "license": "demo"}}

    media = resolver.resolve_style(style, providers=[LocalProvider(ROOT)])
    assert media["image"] == LOCAL_IMAGE
    resolver.save_cache()

    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["items"]["d001"]["provider"] == "local"

    again = MediaResolver(cache_path=cache).resolve_style({"id": "d001"})
    assert again["image"] == LOCAL_IMAGE


def test_resolver_degrades_to_placeholder():
    resolver = MediaResolver(cache_path=None, root=ROOT)
    degraded = resolver.resolve_style({"id": "missing-1"})
    assert degraded["image"] is None
    assert degraded["license"] == "placeholder"
    assert degraded["provider"] == "none"


def test_resolver_degrades_when_provider_raises(tmp_path):
    class BoomProvider:
        name = "boom"

        def resolve(self, style):
            raise ProviderError("搜索接口超时")

    resolver = MediaResolver(cache_path=tmp_path / "c.json")
    media = resolver.resolve_style(
        {"id": "d002"}, providers=[BoomProvider()], allow_network=True
    )
    assert media["image"] is None
    assert "媒体解析失败" in (media["note"] or "")


def test_resolve_card_media_is_read_only(tmp_path):
    styles_by_id = {
        "d001": {"id": "d001", "media": {"image": LOCAL_IMAGE, "license": "demo"}},
    }
    cache = tmp_path / "none.json"
    media_map = resolve_card_media(styles_by_id, ["d001", "nope"], cache_path=cache)

    assert media_map["d001"]["image"] == LOCAL_IMAGE
    assert media_map["nope"]["image"] is None
    assert not cache.exists()


# ---------------------------------------------------------------- 展示链路


def test_pipeline_attaches_media_to_cards():
    payload = generate(
        SCENARIOS["slender_cool"], use_llm=False, styles_path="data/styles.demo.json"
    )
    assert payload["recommendations"]
    for card in payload["recommendations"]:
        media = card.get("media")
        assert isinstance(media, dict), card["style_id"]
        assert media.get("image"), f"卡片缺少参考图：{card['style_id']}"


def test_card_view_exposes_media_fields():
    payload = generate(
        SCENARIOS["slender_cool"], use_llm=False, styles_path="data/styles.demo.json"
    )
    views = [card_view(card) for card in payload["recommendations"]]
    assert all(view["media"] for view in views)
    assert all("仅风格参考" in view["media_caption"] for view in views)


# ---------------------------------------------------------------- 预取脚本


def test_prefetch_local_writes_cache(tmp_path):
    styles_path = tmp_path / "styles.json"
    cache = tmp_path / "media_cache.json"
    entries = [
        {"id": "t001", "name": "甲一", "tier": "safe", "image": LOCAL_IMAGE},
        {"id": "t002", "name": "甲二", "tier": "bold", "image": LOCAL_IMAGE},
    ]
    styles_path.write_text(json.dumps({"styles": entries}, ensure_ascii=False), encoding="utf-8")

    code = prefetch_main(
        ["--styles", str(styles_path), "--cache", str(cache), "--provider", "local"]
    )
    assert code == 0
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert set(data["items"]) == {"t001", "t002"}


def test_prefetch_reports_missing_images(tmp_path):
    styles_path = tmp_path / "bad.json"
    styles_path.write_text(
        json.dumps({"styles": [{"id": "t003", "name": "缺图", "image": "static/demo/nope.jpg"}]}),
        encoding="utf-8",
    )
    code = prefetch_main(
        ["--styles", str(styles_path), "--cache", str(tmp_path / "b.json"), "--provider", "local"]
    )
    assert code == 1


# ---------------------------------------------------------------- 搜索文本来源


def test_search_sources_lists_clean_text_sources(tmp_path):
    search = FakeResp(
        payload={
            "results": [
                {
                    "title": "2026 美甲趋势",
                    "url": "https://a.example.com/x",
                    "site_name": "趋势站",
                    "date": "2026-10-01",
                    "summary": "裸色与法式仍然主流",
                    "authority": 2,
                    "rerank_score": 1.9,
                },
                {"title": "没有链接的结果", "url": "", "rerank_score": 2.4},
                {"title": "低相关度", "url": "https://b.example.com/y", "rerank_score": 0.4},
            ]
        }
    )
    client = FakeClient([search])
    provider = SearchProvider("key", client=client, root=tmp_path, refs_dir=tmp_path / "refs")

    sources = provider.search_sources("美甲趋势", count=5)

    assert [source["url"] for source in sources] == [
        "https://a.example.com/x",
        "https://b.example.com/y",
    ]
    assert sources[0]["site"] == "趋势站"
    assert sources[0]["summary"] == "裸色与法式仍然主流"
    assert sources[0]["relevance"] == 1.9
    assert client.calls[0][0] == "POST"
    assert "tools/search" in client.calls[0][1]
    assert len(client.calls) == 1  # 只做 Search，不进入 Fetch、不下载图片


def test_search_sources_requires_api_key(tmp_path):
    with pytest.raises(ProviderError):
        SearchProvider("", client=FakeClient([]), root=tmp_path).search_sources("美甲")


def test_web_sources_formats_links():
    from scripts.web_sources import format_sources

    text = format_sources(
        "美甲",
        [
            {
                "title": "标题",
                "url": "https://a.example.com/x",
                "site": "站名",
                "date": "2026-10-01",
                "summary": "要点",
                "relevance": 1.5,
                "authority": 2,
            }
        ],
    )

    assert "标题" in text
    assert "https://a.example.com/x" in text
    assert "站名" in text
    assert "相关度" in text

