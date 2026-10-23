from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from core.data import load_styles, load_taxonomy
from core.styles import check_images, validate_style, validate_styles


@pytest.fixture()
def taxonomy() -> dict:
    return load_taxonomy()


@pytest.fixture()
def style_image_root():
    """项目内的临时目录：不依赖系统 TEMP（部分受限环境里 stat/ scandir 会被拒绝）。"""
    root = Path(__file__).resolve().parent / "_style_image_root"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture()
def styles() -> list[dict]:
    return list(load_styles())


def _clone(styles: list[dict]) -> dict:
    return copy.deepcopy(styles[0])


def test_sample_styles_pass(styles: list[dict], taxonomy: dict) -> None:
    assert validate_styles(styles, taxonomy) == []


def test_missing_field_reported(styles: list[dict], taxonomy: dict) -> None:
    style = _clone(styles)
    style.pop("hue")
    errors = validate_style(style, taxonomy)
    assert any("hue" in item for item in errors)


def test_invalid_enum_reported(styles: list[dict], taxonomy: dict) -> None:
    style = _clone(styles)
    style["color_family"] = "rainbow"
    errors = validate_style(style, taxonomy)
    assert any("color_family" in item for item in errors)


def test_invalid_shape_reported(styles: list[dict], taxonomy: dict) -> None:
    style = _clone(styles)
    style["shape"] = ["triangle"]
    errors = validate_style(style, taxonomy)
    assert any("shape" in item for item in errors)


def test_hue_out_of_range(styles: list[dict], taxonomy: dict) -> None:
    style = _clone(styles)
    style["hue"] = 400
    errors = validate_style(style, taxonomy)
    assert any("hue" in item for item in errors)


def test_duplicate_id_reported(styles: list[dict], taxonomy: dict) -> None:
    duplicated = [copy.deepcopy(styles[0]), copy.deepcopy(styles[0])]
    errors = validate_styles(duplicated, taxonomy)
    assert any("重复" in item for item in errors)


def test_image_path_must_be_relative(styles: list[dict], taxonomy: dict) -> None:
    style = _clone(styles)
    style["image"] = "C:/absolute/path.jpg"
    errors = validate_style(style, taxonomy)
    assert any("static/" in item for item in errors)


def test_check_images_reports_missing(styles: list[dict], style_image_root: Path) -> None:
    errors = check_images(styles[:1], style_image_root)
    assert len(errors) == 1


def test_check_images_passes_when_file_exists(styles: list[dict], style_image_root: Path) -> None:
    style = copy.deepcopy(styles[0])
    image_path = style_image_root / style["image"]
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake")
    assert check_images([style], style_image_root) == []
