"""M7 自动打标签的单元测试（autotag）。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data import load_taxonomy  # noqa: E402
from core.styles import validate_styles  # noqa: E402
from scripts.autotag import (  # noqa: E402
    build_library,
    classify_color,
    dominant_rgb,
    length_from_name,
    main,
    shape_from_name,
    style_from_name,
)


@pytest.fixture()
def tmp_dir():
    """项目内临时目录（不依赖系统 TEMP，便于受限环境下运行）。"""
    root = Path(__file__).resolve().parent / "_autotag_tmp"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)



def _make(path: Path, rgb: tuple[int, int, int]) -> Path:
    Image.new("RGB", (120, 160), rgb).save(path)
    return path


# ---- 颜色 ----------------------------------------------------------------


def test_dominant_rgb_returns_red(tmp_dir):
    path = _make(tmp_dir / "red.jpg", (200, 40, 50))
    r, g, b = dominant_rgb(path)
    assert r > 150 and g < 110 and b < 110


def test_classify_pure_red():
    color = classify_color("demo", (180, 30, 40))
    assert color["color_family"] == "true_red"
    assert color["tone"] == "warm"
    assert color["saturation"] == "high"
    assert 345 <= color["hue"] <= 360 or color["hue"] < 15


def test_classify_pale_nude():
    color = classify_color("nude_pastel", (245, 222, 218))
    assert color["color_family"] == "nude_pink"
    assert color["value"] == "light"
    assert color["saturation"] == "low"


def test_classify_navy_is_cool_deep():
    color = classify_color("demo", (40, 55, 90))
    assert color["color_family"] == "blue_green"
    assert color["tone"] == "cool"
    assert color["value"] == "deep"


# ---- 文件名关键词 --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("demo22_almond_blue_mix", "solid"),
        ("demo12_sheer_glitter_heart", "glitter"),
        ("demo07_brown_cateye_gold", "cat_eye"),
        ("demo01_nude_french", "french"),
        ("demo15_macaron_gradients", "gradient"),
        ("demo13_blue_white_doodle", "drawing"),
        ("demo25_short_square_cream", "solid"),
        ("demo26_short_square_olive_cateye", "cat_eye"),
    ],
)
def test_style_from_name(name, expected):
    assert style_from_name(name) == expected


def test_shape_from_name():
    assert shape_from_name("x_almond") == ["almond", "oval"]
    assert shape_from_name("x_short_square") == ["square", "squoval"]
    assert shape_from_name("x") == ["oval", "squoval", "almond"]


def test_length_from_name():
    assert length_from_name("demo05_white_lace_long") == "long"
    assert length_from_name("demo10_nude_french_dots") == "mid"
    assert length_from_name("demo05_short_round") == "short"


# ---- 建库 ----------------------------------------------------------------


def _library_source(tmp_dir: Path) -> Path:
    src = tmp_dir / "images"
    src.mkdir()
    _make(src / "a1_nude_french_oval.jpg", (230, 200, 195))
    _make(src / "a2_berry_cateye_almond.jpg", (110, 40, 90))
    _make(src / "a3_olive_green_short_square.jpg", (120, 130, 70))
    return src


def test_build_library_validates(tmp_dir):
    src = _library_source(tmp_dir)
    doc = build_library(src)
    assert len(doc["styles"]) == 3
    assert [entry["id"] for entry in doc["styles"]] == ["d001", "d002", "d003"]
    assert validate_styles(doc["styles"], load_taxonomy()) == []
    for entry in doc["styles"]:
        assert entry["tags"]
        assert entry["scene"]
        assert 0 <= entry["hue"] < 360
        assert entry["image"].startswith("static/demo/")


def test_build_library_skips_underscore_files(tmp_dir):
    src = _library_source(tmp_dir)
    Image.new("RGB", (60, 80), (10, 200, 10)).save(src / "_sheet.jpg")
    doc = build_library(src)
    assert len(doc["styles"]) == 3


def test_build_library_applies_overrides(tmp_dir):
    src = _library_source(tmp_dir)
    doc = build_library(src, {"d001": {"scene": ["date"], "color_family": "berry"}})
    first = doc["styles"][0]
    assert first["scene"] == ["date"]
    assert first["color_family"] == "berry"
    assert validate_styles(doc["styles"], load_taxonomy()) == []


def test_build_library_rejects_empty_dir(tmp_dir):
    empty = tmp_dir / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        build_library(empty)


def test_main_writes_json(tmp_dir, capsys):
    src = _library_source(tmp_dir)
    out = tmp_dir / "styles.demo.json"
    assert main(["--src", str(src), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(doc["styles"]) == 3
    assert "validate_styles" in capsys.readouterr().out


def test_main_dry_run_does_not_write(tmp_dir, capsys):
    src = _library_source(tmp_dir)
    out = tmp_dir / "styles.demo.json"
    assert main(["--src", str(src), "--out", str(out), "--dry-run"]) == 0
    assert not out.exists()
    assert "可处理图片：3 张" in capsys.readouterr().out
