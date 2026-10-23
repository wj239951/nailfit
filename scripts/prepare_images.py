"""把原始美甲图批量处理成款式库图片（M6 用）。

处理规则：居中裁成竖构图（默认 3:4）→ 缩放到 768x1024 → JPEG 质量自适应压到 ≤300KB。
手机截图可用 --box 先裁掉状态栏/评论区，或用 --focus top 保留偏上的手部区域；
比例差太多的宽图用 --fit pad 整图放进 3:4 画布补底色；--dry-run 只打印计划、不写文件。

用法：
    # 目录批量（先 dry-run 看计划）
    python scripts/prepare_images.py --src raw_images --out static/styles --dry-run
    python scripts/prepare_images.py --src raw_images --out static/styles --prefix s --start 14

    # 单张 + 手动框选照片区域（截图类推荐）
    python scripts/prepare_images.py --src raw_images/0816.jpg --out static/styles/s014.jpg --box 0,95,1206,1500

    # 宽图：整图放进 3:4，两侧补底色
    python scripts/prepare_images.py --src raw_images/wide.jpg --out static/demo/demo03.jpg --box 0,700,1206,1608 --fit pad --pad-color "#f5f2ec"

命名：给了 --prefix 就按 s001.jpg 递增编号，否则沿用原文件名（换成 .jpg）。
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageColor, ImageOps

ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
QUALITY_RANGE = range(88, 39, -6)


def parse_box(value: str) -> tuple[int, int, int, int]:
    """解析 --box "x1,y1,x2,y2"（左上 + 右下）。"""
    parts = [int(piece.strip()) for piece in value.split(",")]
    if len(parts) != 4 or parts[2] <= parts[0] or parts[3] <= parts[1]:
        raise ValueError("--box 需要 4 个整数且 x2>x1、y2>y1，例如 0,95,1206,1500")
    return parts[0], parts[1], parts[2], parts[3]


def center_crop(
    img: Image.Image, width: int, height: int, focus: str = "center"
) -> Image.Image:
    """按目标宽高比裁剪：center 居中裁，top 保留上半部分（截图上常见手部偏上）。"""
    target = width / height
    w, h = img.size
    if w / h > target:
        crop_w, crop_h = int(round(h * target)), h
    else:
        crop_w, crop_h = w, int(round(w / target))
    left = (w - crop_w) // 2
    top = 0 if focus == "top" else (h - crop_h) // 2
    return img.crop((left, top, left + crop_w, top + crop_h))


def save_jpeg_under_limit(img: Image.Image, dest: Path, max_kb: int) -> tuple[int, int]:
    """返回 (quality, bytes)。压到 ≤max_kb 为止；真压不下去就保留最小的一版。"""
    limit = max_kb * 1024
    payload = b""
    quality = QUALITY_RANGE[-1]
    for quality in QUALITY_RANGE:
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        payload = buffer.getvalue()
        if len(payload) <= limit:
            break
    dest.write_bytes(payload)
    return quality, len(payload)


def process_one(
    source: Path,
    dest: Path,
    *,
    width: int,
    height: int,
    focus: str,
    max_kb: int,
    box: tuple[int, int, int, int] | None = None,
    fit: str = "crop",
    pad_color: str = "#f2efe9",
) -> dict:
    with Image.open(source) as img:
        img = img.convert("RGB")
        original = img.size
        if box is not None:
            img = img.crop(box)
        if fit == "pad":
            # 宽图 / 比例差太多的图：整图放进 3:4 画布，两侧或上下补底色
            canvas = ImageOps.pad(
                img, (width, height), method=Image.LANCZOS, color=ImageColor.getrgb(pad_color)
            )
        else:
            canvas = center_crop(img, width, height, focus).resize((width, height), Image.LANCZOS)
    quality, size = save_jpeg_under_limit(canvas, dest, max_kb)
    return {
        "source": source,
        "dest": dest,
        "original": original,
        "bytes": size,
        "quality": quality,
    }


def collect_sources(items: list[Path]) -> list[Path]:
    """目录则递归收集图片；文件则直接使用。保持有序，便于编号可复现。"""
    sources: list[Path] = []
    for item in items:
        if item.is_dir():
            sources.extend(
                p for p in sorted(item.rglob("*")) if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
            )
        elif item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
            sources.append(item)
        elif item.exists():
            print(f"跳过（不是图片或目录）：{item}", file=sys.stderr)
        else:
            print(f"跳过（不存在）：{item}", file=sys.stderr)
    return sources


def target_name(source: Path, prefix: str, index: int) -> str:
    return f"{prefix}{index:03d}.jpg" if prefix else f"{source.stem}.jpg"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="款式图批量裁切 / 缩放 / 压缩（≤300KB）")
    parser.add_argument("--src", nargs="+", required=True, help="原图目录或文件列表")
    parser.add_argument("--out", type=Path, default=ROOT / "static" / "styles", help="输出目录；单张时也可写完整文件名（如 static/demo/demo01.jpg）")
    parser.add_argument("--width", type=int, default=768, help="输出宽（默认 768）")
    parser.add_argument("--height", type=int, default=1024, help="输出高（默认 1024）")
    parser.add_argument("--max-kb", type=int, default=300, help="单张体积上限 KB（默认 300）")
    parser.add_argument("--focus", choices=("center", "top"), default="center", help="裁剪焦点")
    parser.add_argument("--fit", choices=("crop", "pad"), default="crop", help="crop=裁成 3:4；pad=整图放进 3:4 补底色")
    parser.add_argument("--pad-color", default="#f2efe9", help="--fit pad 时的补边颜色，如 #f2efe9")
    parser.add_argument("--box", type=parse_box, default=None, help='手动框选 "x1,y1,x2,y2"（截图去 UI）')
    parser.add_argument("--prefix", default="", help="输出编号前缀，如 s → s001.jpg")
    parser.add_argument("--start", type=int, default=1, help="编号起始值（配合 --prefix）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    args = parser.parse_args(argv)

    if args.box is not None and len(args.src) > 1:
        print("提示：--box 是按单张图坐标写的，批量处理时请逐张调用。", file=sys.stderr)

    sources = collect_sources([Path(item) for item in args.src])
    if not sources:
        print("没有找到可处理的图片", file=sys.stderr)
        return 1

    file_out = args.out.suffix.lower() in IMAGE_SUFFIXES
    if file_out:
        if len(sources) > 1:
            print("--out 写成文件路径时只能处理 1 张图；批量请给目录。", file=sys.stderr)
            return 2
        plans = [(sources[0], args.out)]
    else:
        plans = [
            (source, args.out / target_name(source, args.prefix, args.start + offset))
            for offset, source in enumerate(sources)
        ]

    if args.dry_run:
        for source, dest in plans:
            extra = f"  box={args.box}" if args.box else ""
            print(f"[dry-run] {source}  →  {dest}{extra}")
        print(f"\n共 {len(plans)} 张；去掉 --dry-run 即开始处理。")
        return 0

    if file_out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
    else:
        args.out.mkdir(parents=True, exist_ok=True)
    ok = 0
    for source, dest in plans:
        try:
            info = process_one(
                source,
                dest,
                width=args.width,
                height=args.height,
                focus=args.focus,
                max_kb=args.max_kb,
                box=args.box,
                fit=args.fit,
                pad_color=args.pad_color,
            )
        except Exception as exc:  # noqa: BLE001 - 单张失败不阻塞整批
            print(f"✗ 失败：{source}（{exc}）", file=sys.stderr)
            continue
        ok += 1
        flag = "" if info["bytes"] <= args.max_kb * 1024 else f"  ⚠ 超过 {args.max_kb}KB"
        print(
            f"✓ {source.name:<32} {info['original'][0]}x{info['original'][1]}"
            f"  →  {dest.name:<12} {info['bytes'] / 1024:.0f}KB  q={info['quality']}{flag}"
        )

    print(f"\n完成 {ok}/{len(plans)} 张 → {args.out}")
    if ok:
        print("下一步：python scripts/validate_styles.py --check-images")
    return 0 if ok == len(plans) else 1


if __name__ == "__main__":
    raise SystemExit(main())
