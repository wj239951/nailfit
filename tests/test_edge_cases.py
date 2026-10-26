"""异常与边界处理（M4）的回归测试。

覆盖四类边界：
1. 款式库为空 / 文件缺失 / JSON 损坏 / 结构错误
2. 过滤后没有候选、候选不足 3 款
3. 特征值非法
4. API 状态码映射（503 / 422）与 CLI 退出码
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core import data as data_module
from core.errors import DataFormatError, EmptyStyleLibraryError, NoCandidateError
from core.features import FeatureError, HandFeatures
from core.pipeline import recommend

client = TestClient(app)

SHORT_FEATURES = HandFeatures(length="short")
LONG_STYLE = {
    "id": "t_long",
    "name": "长甲款",
    "length_fit": "long",
    "color_family": "red",
    "hue": 0,
    "scene": ["commute"],
    "image": "static/styles/t_long.jpg",
}
SHORT_STYLE = {
    "id": "t_short",
    "name": "短甲款",
    "length_fit": "short",
    "color_family": "red",
    "hue": 0,
    "scene": ["commute"],
    "image": "static/styles/t_short.jpg",
}


@pytest.fixture()
def edge_dir():
    """项目内临时目录（不依赖系统 TEMP）。"""
    root = Path(__file__).resolve().parent / "_edge_data"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------- 1. 数据层 ----------


def test_load_styles_missing_file(edge_dir: Path) -> None:
    data_module.load_styles.cache_clear()
    with pytest.raises(DataFormatError, match="不存在"):
        data_module.load_styles(str(edge_dir / "nope.json"))


def test_load_styles_invalid_json(edge_dir: Path) -> None:
    path = edge_dir / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    data_module.load_styles.cache_clear()
    with pytest.raises(DataFormatError, match="JSON"):
        data_module.load_styles(str(path))


def test_load_styles_wrong_structure(edge_dir: Path) -> None:
    path = edge_dir / "wrong.json"
    path.write_text(json.dumps({"styles": "oops"}, ensure_ascii=False), encoding="utf-8")
    data_module.load_styles.cache_clear()
    with pytest.raises(DataFormatError, match="格式错误"):
        data_module.load_styles(str(path))


def test_load_styles_empty_library(edge_dir: Path) -> None:
    path = edge_dir / "empty.json"
    path.write_text(json.dumps({"styles": []}), encoding="utf-8")
    data_module.load_styles.cache_clear()
    with pytest.raises(EmptyStyleLibraryError, match="款式库为空"):
        data_module.load_styles(str(path))


# ---------- 2. 编排层 ----------


def test_pipeline_empty_styles_raise_empty_library() -> None:
    with pytest.raises(EmptyStyleLibraryError, match="款式库为空"):
        recommend(SHORT_FEATURES, styles=[], use_llm=False)


def test_pipeline_all_styles_filtered() -> None:
    with pytest.raises(NoCandidateError, match="没有通过硬性过滤"):
        recommend(SHORT_FEATURES, styles=[LONG_STYLE], use_llm=False)


def test_pipeline_too_few_styles() -> None:
    with pytest.raises(NoCandidateError, match="至少需要 3 款"):
        recommend(SHORT_FEATURES, styles=[SHORT_STYLE], use_llm=False)


# ---------- 3. 特征非法 ----------


def test_invalid_feature_value() -> None:
    with pytest.raises(FeatureError, match="不在允许取值"):
        HandFeatures.from_dict({"length": "eternal"})


def test_unknown_feature_field() -> None:
    with pytest.raises(FeatureError, match="未知特征字段"):
        HandFeatures.from_dict({"nail_bed_ratio": "standard", "age": 3})


# ---------- 4. API 状态码 ----------


def test_api_empty_library_returns_503(monkeypatch) -> None:
    monkeypatch.setattr("api.routes.load_styles", lambda *args, **kwargs: [])
    resp = client.post(
        "/api/recommend",
        json={"features": HandFeatures().to_dict(), "use_llm": False},
    )
    assert resp.status_code == 503
    assert "款式库" in resp.json()["detail"]


def test_api_too_few_candidates_returns_422(monkeypatch) -> None:
    monkeypatch.setattr("api.routes.load_styles", lambda *args, **kwargs: [SHORT_STYLE])
    resp = client.post(
        "/api/recommend",
        json={"features": HandFeatures().to_dict(), "use_llm": False},
    )
    assert resp.status_code == 422
    assert "至少需要 3 款" in resp.json()["detail"]


def test_api_invalid_feature_returns_422() -> None:
    resp = client.post(
        "/api/recommend",
        json={"features": {"length": "eternal"}, "use_llm": False},
    )
    assert resp.status_code == 422
    assert "特征非法" in resp.json()["detail"]


# ---------- 5. CLI 退出码 ----------


def test_demo_cli_returns_2_on_error(monkeypatch, capsys) -> None:
    from scripts import demo

    def boom(*_args, **_kwargs):
        raise NoCandidateError("没有通过硬性过滤的款式")

    monkeypatch.setattr(demo, "recommend", boom)
    monkeypatch.setattr("sys.argv", ["demo.py"])
    assert demo.main() == 2
    assert "推荐失败" in capsys.readouterr().err


def test_manual_cli_returns_2_on_error(monkeypatch, capsys) -> None:
    from scripts import manual

    def boom(*_args, **_kwargs):
        raise NoCandidateError("没有通过硬性过滤的款式")

    monkeypatch.setattr(manual, "recommend", boom)
    assert manual.main(["--yes"]) == 2
    assert "推荐失败" in capsys.readouterr().err
