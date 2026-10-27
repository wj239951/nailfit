"""M32 网络参考图：清单加载、推荐响应挂载、预取清单读写。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import core.references as references
from api.main import app
from core.data import library_path
from core.styles import load_styles_json
from scripts import prefetch_references as prefetch

#: 项目里真实存在的图片，便于构造“有效参考图”
REAL_IMAGE = "static/styles/s001.jpg"


def _entry(image=REAL_IMAGE, license="cc0", **extra):
    entry = {
        "image": image,
        "title": extra.get("title", "参考图"),
        "author": extra.get("author", "someone"),
        "license": license,
        "source_url": extra.get("source_url", "https://example.com/photo"),
        "provider": "openverse",
    }
    return entry


def _write_manifest(tmp_path: Path, entries: dict) -> Path:
    path = tmp_path / "references.json"
    path.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------ 清单加载
def test_load_references_filters_invalid_entries(tmp_path):
    path = _write_manifest(
        tmp_path,
        {
            "s001": [
                _entry(),  # 有效
                _entry(license="cc-by-nc"),  # 许可不在白名单
                _entry(image="static/refs/s001/99.jpg"),  # 文件不存在
                _entry(image="https://cdn.example.com/x.jpg"),  # 不是 static/ 路径
            ],
            "s002": "not-a-list",
        },
    )
    catalog = references.load_references(path)
    assert list(catalog) == ["s001"]
    assert len(catalog["s001"]) == 1
    view = catalog["s001"][0]
    assert view["license"] == "cc0"
    assert view["license_label"] == "CC0"
    assert view["image"] == REAL_IMAGE
    assert view["source_url"].startswith("https://")


def test_references_for_respects_limit(tmp_path):
    path = _write_manifest(tmp_path, {"s001": [_entry(title=f"图{i}") for i in range(3)]})
    assert len(references.references_for("s001", limit=2, path=path)) == 2
    assert references.references_for("s001", limit=0, path=path) == []
    assert references.references_for("missing", path=path) == []


def test_load_references_tolerates_missing_or_broken_file(tmp_path):
    assert references.load_references(tmp_path / "nope.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert references.load_references(broken) == {}


# ------------------------------------------------------------------ 挂载
def test_attach_references_only_touches_recommendations(tmp_path):
    path = _write_manifest(tmp_path, {"s001": [_entry()], "s002": [_entry(license="by")]})
    payload = {
        "features": {"scene": "commute"},
        "recommendations": [
            {"style_id": "s001", "reason": "x"},
            {"style_id": "s999"},
        ],
        "avoid": [],
    }
    result = references.attach_references(payload, limit=3, path=path)
    assert len(result["recommendations"][0]["references"]) == 1
    assert result["recommendations"][1]["references"] == []
    assert result["recommendations"][0]["reason"] == "x"  # 原有字段不动


def test_recommend_api_mounts_references(monkeypatch):
    """推荐接口在预取清单存在时返回 references（用真实款式库 id 造清单）。"""
    sample_styles = load_styles_json(str(library_path("sample")))

    def fake_load(path=None):
        return {
            str(style["id"]): [
                {
                    "image": REAL_IMAGE,
                    "title": "网络参考",
                    "author": "tester",
                    "license": "by",
                    "license_label": "CC BY",
                    "source_url": "https://example.com/x",
                    "provider": "openverse",
                }
            ]
            for style in sample_styles
        }

    monkeypatch.setattr(references, "load_references", fake_load)
    client = TestClient(app)
    response = client.post(
        "/api/recommend",
        json={
            "features": {
                "nail_bed_ratio": "standard",
                "nail_shape": "oval",
                "length": "mid",
                "ita_band": "light",
                "warmth": "warm",
                "hand_type": "standard",
                "scene": "commute",
            },
            "library": "sample",
            "use_llm": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["recommendations"]) == 3
    for card in body["recommendations"]:
        assert len(card["references"]) == 1
        assert card["references"][0]["license_label"] == "CC BY"


def test_recommend_api_without_manifest_returns_empty(monkeypatch):
    monkeypatch.setattr(references, "load_references", lambda path=None: {})
    client = TestClient(app)
    response = client.post(
        "/api/recommend",
        json={
            "features": {
                "nail_bed_ratio": "standard",
                "nail_shape": "oval",
                "length": "mid",
                "ita_band": "light",
                "warmth": "warm",
                "hand_type": "standard",
                "scene": "commute",
            },
            "library": "sample",
            "use_llm": False,
        },
    )
    assert response.status_code == 200
    for card in response.json()["recommendations"]:
        assert card["references"] == []


# ------------------------------------------------------------------ 预取清单
def test_manifest_roundtrip(tmp_path):
    path = tmp_path / "data" / "references.json"
    entries = {"d001": [prefetch.to_manifest_entry({"local_image": REAL_IMAGE, "title": "t"})]}
    prefetch.save_manifest(path, entries, provider="openverse")
    manifest = prefetch.load_manifest(path)
    assert manifest["version"] == 1
    assert manifest["provider"] == "openverse"
    assert manifest["entries"]["d001"][0]["image"] == REAL_IMAGE
    assert manifest["entries"]["d001"][0]["license"] is None  # 缺字段时为 None，不抛异常


def test_load_manifest_tolerates_missing_file(tmp_path):
    manifest = prefetch.load_manifest(tmp_path / "nope.json")
    assert manifest == {"version": 1, "entries": {}}


def test_parse_args_defaults():
    args = prefetch.parse_args([])
    assert args.library == "demo"
    assert args.per_style == 3
    assert args.limit == 0
    assert Path(args.manifest).name == "references.json"
