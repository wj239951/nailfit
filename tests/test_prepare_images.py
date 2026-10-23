"""prepare_images.py 的单元测试：裁剪、压缩、dry-run、目录批处理。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from scripts import prepare_images as prep


@pytest.fixture()
def img_dir():
    """项目内临时目录（不依赖系统 TEMP）。"""
    root = Path(__file__).resolve().parent / "_img_tmp"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def make_image(path: Path, size: tuple[int, int] = (900, 1200), color=(200, 180, 170)) -> None:
    Image.new("RGB", size, color).save(path)


def test_center_crop_landscape_ratio() -> None:
    img = Image.new("RGB", (300, 900))
    out = prep.center_crop(img, 768, 1024)
    # 目标比例 3:4，原图过窄：保留全宽，按比例补高
    assert out.size == (300, 400)


def test_center_crop_wide_image() -> None:
    img = Image.new("RGB", (900, 300))
    out = prep.center_crop(img, 768, 1024)
    # 原图过宽：保留全高，按比例裁宽
    assert out.size == (225, 300)


def test_process_one_outputs_small_jpeg(img_dir: Path) -> None:
    src = img_dir / "shot.png"
    make_image(src, (1200, 2600))
    dest = img_dir / "s901.jpg"

    info = prep.process_one(src, dest, width=768, height=1024, focus="center", max_kb=300)

    assert dest.exists()
    with Image.open(dest) as out:
        assert out.size == (768, 1024)
    assert dest.stat().st_size <= 300 * 1024
    assert info["quality"] >= 40


def test_main_dry_run_does_not_write(img_dir: Path) -> None:
    make_image(img_dir / "a.png")
    out_dir = img_dir / "out"

    code = prep.main(["--src", str(img_dir), "--out", str(out_dir), "--dry-run"])

    assert code == 0
    assert not out_dir.exists()


def test_main_processes_directory_with_prefix(img_dir: Path) -> None:
    make_image(img_dir / "a.png")
    make_image(img_dir / "b.jpg", (600, 800))
    out_dir = img_dir / "out"

    code = prep.main(["--src", str(img_dir), "--out", str(out_dir), "--prefix", "s"])

    assert code == 0
    assert sorted(p.name for p in out_dir.glob("*.jpg")) == ["s001.jpg", "s002.jpg"]


def test_parse_box_ok() -> None:
    assert prep.parse_box("0,95,1206,1500") == (0, 95, 1206, 1500)


def test_parse_box_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        prep.parse_box("0,95,1206")


def test_process_one_with_box(img_dir: Path) -> None:
    src = img_dir / "shot.png"
    make_image(src, (1200, 2600))
    dest = img_dir / "s902.jpg"

    info = prep.process_one(
        src, dest, width=768, height=1024, focus="center", max_kb=300, box=(0, 100, 1200, 1500)
    )

    assert info["original"] == (1200, 2600)
    with Image.open(dest) as out:
        assert out.size == (768, 1024)


def test_process_one_pad_fit_letterboxes(img_dir: Path) -> None:
    src = img_dir / "wide.png"
    make_image(src, (1200, 600))
    dest = img_dir / "s903.jpg"

    info = prep.process_one(
        src, dest, width=768, height=1024, focus="center", max_kb=300, fit="pad", pad_color="#f2efe9"
    )

    with Image.open(dest) as out:
        assert out.size == (768, 1024)
        # 宽图上下补边 → 顶部像素应是底色
        top_pixel = out.convert("RGB").getpixel((10, 10))
        assert all(abs(a - b) <= 6 for a, b in zip(top_pixel, (242, 239, 233)))
    assert info["original"] == (1200, 600)


def test_main_accepts_file_out(img_dir: Path) -> None:
    src = img_dir / "one.jpg"
    make_image(src, (600, 800))
    out = img_dir / "sub" / "exact.jpg"

    code = prep.main(["--src", str(src), "--out", str(out)])

    assert code == 0
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == (768, 1024)


def test_main_skips_non_images(img_dir: Path) -> None:
    make_image(img_dir / "a.png")
    (img_dir / "notes.txt").write_text("not an image", encoding="utf-8")
    out_dir = img_dir / "out"

    code = prep.main(["--src", str(img_dir), "--out", str(out_dir)])

    assert code == 0
    assert [p.name for p in out_dir.glob("*.jpg")] == ["a.jpg"]
