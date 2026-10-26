"""生成样例库占位图（M27）：让「样例库」在前端也有图可看，不再显示空白占位。

背景：data/styles.sample.json 只描述 15 条示例款式，图片路径指向 static/styles/，
但仓库里没有真实图片 —— 打开页面切到「样例库」时卡片没有图。这里按款式标签
画一批风格化的**占位示意图**（不是真实款式，页面上会明确标注），保证：

- 前端任何库都能显示图片，演示时不出现「图片都不显示」的空白；
- 占位图随仓库提交，克隆下来即可用；
- 图片内容由标签确定（色系 → 配色、款式 → 纹样、甲型 → 形状），可复现。

用法：

    python scripts/make_sample_images.py                  # 只补缺图（默认样例库）
    python scripts/make_sample_images.py --force          # 全部重画
    python scripts/make_sample_images.py --styles data/styles.demo.json --dry-run

退出码：0 = 全部有图；1 = 有款式缺图或写文件失败。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CANVAS = (768, 1024)
MARGIN = 64

# 色系 → (主色, 亮色, 背景色)
PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "nude_pink": ((226, 196, 183), (243, 222, 211), (250, 243, 239)),
    "true_red": ((178, 44, 53), (211, 92, 99), (251, 239, 239)),
    "berry": ((126, 50, 84), (165, 92, 124), (246, 236, 242)),
    "orange_brown": ((174, 112, 78), (208, 152, 114), (250, 242, 233)),
    "blue_green": ((92, 138, 140), (137, 176, 174), (234, 244, 243)),
    "mono": ((172, 172, 172), (207, 207, 207), (245, 245, 245)),
    "metal": ((172, 175, 184), (214, 216, 224), (244, 245, 248)),
    "glitter": ((206, 170, 112), (238, 212, 158), (252, 246, 233)),
}

STYLE_TEXT: dict[str, str] = {
    "solid": "纯色",
    "french": "法式",
    "gradient": "渐变",
    "cat_eye": "猫眼",
    "chrome": "镜面",
    "drawing": "手绘",
    "rhinestone": "贴钻",
    "checker": "棋盘格",
    "marble": "大理石",
    "mixed": "混搭",
    "glitter": "亮片",
}

SHAPE_TEXT: dict[str, str] = {
    "round": "圆甲",
    "square": "方甲",
    "oval": "椭圆甲",
    "almond": "杏仁甲",
    "squoval": "方圆甲",
}

# 各甲型在画布上的（宽度, 高度）比例，避免 5 个甲片都是一样的方块
SHAPE_SIZE: dict[str, tuple[float, float]] = {
    "round": (0.92, 0.92),
    "square": (1.0, 1.0),
    "oval": (0.84, 1.06),
    "almond": (0.80, 1.14),
    "squoval": (0.94, 0.98),
}

FONT_PATHS: dict[str, tuple[str, ...]] = {
    "bold": (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
    "regular": (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ),
}


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """优先用系统中文字体（Windows 微软雅黑），找不到再退回 Pillow 默认字体。"""
    for path in FONT_PATHS["bold" if bold else "regular"]:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:  # 旧 Pillow
        return ImageFont.load_default()


def _mix(
    color: tuple[int, int, int],
    other: tuple[int, int, int],
    ratio: float,
) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, ratio))
    return tuple(round(a + (b - a) * ratio) for a, b in zip(color, other))  # type: ignore[return-value]


def _shade(color: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    """ratio > 0 提亮（混白），< 0 压暗（混黑）。"""
    target = (255, 255, 255) if ratio >= 0 else (0, 0, 0)
    return _mix(color, target, abs(ratio))


def palette_for(style: dict) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    base, accent, bg = PALETTES.get(str(style.get("color_family") or ""), PALETTES["mono"])
    # 暖调偏红黄、冷调偏蓝，浅色整体提亮
    tone = str(style.get("tone") or "neutral")
    if tone == "warm":
        base = (min(255, base[0] + 8), base[1], max(0, base[2] - 6))
        accent = (min(255, accent[0] + 8), accent[1], max(0, accent[2] - 6))
    elif tone == "cool":
        base = (max(0, base[0] - 6), base[1], min(255, base[2] + 8))
        accent = (max(0, accent[0] - 6), accent[1], min(255, accent[2] + 8))
    value = str(style.get("value") or "mid")
    if value == "light":
        base, accent = _shade(base, 0.18), _shade(accent, 0.12)
    elif value == "deep":
        base, accent = _shade(base, -0.2), _shade(accent, -0.12)
    return base, accent, bg


def _vertical_gradient(
    size: tuple[int, int],
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
) -> Image.Image:
    width, height = size
    strip = Image.new("RGB", (1, height))
    draw = ImageDraw.Draw(strip)
    for y in range(height):
        draw.point((0, y), fill=_mix(top, bottom, y / max(1, height - 1)))
    return strip.resize((width, height))


def _nail_mask(size: tuple[int, int], box: tuple[int, int, int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def _decor_layer(
    size: tuple[int, int],
    box: tuple[int, int, int, int],
    radius: int,
    base: tuple[int, int, int],
    accent: tuple[int, int, int],
    style_word: str,
    rng: random.Random,
) -> Image.Image:
    """在底色图层上画甲面纹样，随后按 mask 合成。"""
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    layer = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(layer)

    if style_word == "french":
        band = max(10, int(height * 0.16))
        draw.rounded_rectangle((x1, y1, x2, y1 + band), radius=radius, fill=(250, 244, 238))
        draw.rounded_rectangle((x1, y1 + band, x2, y1 + band + 6), radius=3, fill=accent)
    elif style_word == "gradient":
        inner = _vertical_gradient((width, height), _shade(accent, 0.22), base)
        layer.paste(inner, (x1, y1))
    elif style_word == "cat_eye":
        for offset in range(-2, 3):
            line_x = x1 + width // 2 + offset * 9
            draw.line((line_x - 30, y2, line_x + 40, y1), fill=_shade(accent, 0.42), width=7)
        draw.ellipse(
            (x1 + width * 0.3, y1 + height * 0.18, x1 + width * 0.7, y1 + height * 0.34),
            fill=_shade(accent, 0.55),
        )
    elif style_word == "chrome":
        mid = _mix(accent, (255, 255, 255), 0.35)
        layer.paste(_vertical_gradient((width, height), mid, _shade(base, -0.12)), (x1, y1))
        draw.line((x1 + width * 0.24, y1 + 6, x1 + width * 0.14, y2 - 6), fill=(255, 255, 255), width=5)
    elif style_word == "drawing":
        for _ in range(5):
            cx = rng.randint(x1 + 12, max(x1 + 13, x2 - 12))
            cy = rng.randint(y1 + 20, max(y1 + 21, y2 - 24))
            r = rng.randint(5, 11)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=_shade(accent, 0.32), width=3)
            draw.line((cx, cy + r, cx, cy + r + 12), fill=_shade(accent, 0.32), width=3)
    elif style_word == "rhinestone":
        for _ in range(3):
            cx = rng.randint(x1 + 18, max(x1 + 19, x2 - 18))
            cy = rng.randint(y1 + 26, max(y1 + 27, y2 - 22))
            r = rng.randint(6, 9)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(246, 248, 250), outline=_shade(base, -0.18))
            draw.ellipse((cx - r + 2, cy - r + 2, cx - r + 5, cy - r + 5), fill=(255, 255, 255))
    elif style_word == "checker":
        cell = max(10, width // 4)
        for row in range(0, height, cell):
            for col in range(0, width, cell):
                if (row // cell + col // cell) % 2 == 0:
                    draw.rectangle(
                        (x1 + col, y1 + row, x1 + col + cell, y1 + row + cell),
                        fill=_shade(accent, 0.2),
                    )
    elif style_word == "marble":
        for _ in range(2):
            points = [(x1 + width * 0.1, y1 + height * 0.2)]
            step = max(6, height // 8)
            for index in range(1, 8):
                points.append(
                    (x1 + width * (0.1 + 0.12 * index) + rng.randint(-8, 8), y1 + step * index)
                )
            draw.line(points, fill=_shade(accent, 0.45), width=4, joint="curve")
    elif style_word == "glitter":
        for _ in range(40):
            cx = rng.randint(x1 + 6, max(x1 + 7, x2 - 6))
            cy = rng.randint(y1 + 8, max(y1 + 9, y2 - 8))
            r = rng.randint(1, 3)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 250, 235))
    elif style_word == "mixed":
        for _ in range(12):
            cx = rng.randint(x1 + 8, max(x1 + 9, x2 - 8))
            cy = rng.randint(y1 + 10, max(y1 + 11, y2 - 10))
            r = rng.randint(2, 4)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 252, 240))
        draw.ellipse(
            (x1 + width * 0.28, y1 + height * 0.1, x1 + width * 0.72, y1 + height * 0.26),
            outline=(255, 255, 255),
            width=3,
        )

    # 统一高光：左上一道很淡的柔光，避免抢掉纹样
    draw.rounded_rectangle(
        (x1 + width * 0.22, y1 + height * 0.1, x1 + width * 0.3, y1 + height * 0.4),
        radius=radius,
        outline=_mix(base, (255, 255, 255), 0.5),
        width=2,
    )
    return layer


def draw_card(style: dict, *, seed: int = 7) -> Image.Image:
    """按款式标签画一张 768×1024 的占位示意图。"""
    width, height = CANVAS
    base, accent, bg = palette_for(style)
    rng = random.Random(seed)
    style_word = str(style.get("style") or "solid")

    canvas = _vertical_gradient(CANVAS, _shade(bg, 0.12), _shade(bg, -0.05)).convert("RGB")

    # 背景装饰：两个淡色大圆
    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.ellipse((width * 0.55, -height * 0.1, width * 1.2, height * 0.42), fill=(*accent, 26))
    odraw.ellipse((-width * 0.18, height * 0.45, width * 0.32, height * 0.95), fill=(*base, 20))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    # 甲片：5 个并排，底部对齐，中间略高
    nail_w, gap = 102, 26
    total = 5 * nail_w + 4 * gap
    left = (width - total) // 2
    heights = [156, 196, 222, 196, 156]
    shape = str((style.get("shape") or ["oval"])[0])
    ratio_w, ratio_h = SHAPE_SIZE.get(shape, (0.9, 1.0))
    bottom = 636
    for index in range(5):
        nail_w_i = int(nail_w * ratio_w)
        nail_h = int(heights[index] * ratio_h)
        x1 = left + index * (nail_w + gap) + (nail_w - nail_w_i) // 2
        box = (x1, bottom - nail_h, x1 + nail_w_i, bottom)
        radius = max(18, nail_w_i // 2 - 2)
        mask = _nail_mask(CANVAS, box, radius)
        layer = _decor_layer(CANVAS, box, radius, _shade(base, 0.02), accent, style_word, rng)
        canvas = Image.composite(layer, canvas, mask)
        ImageDraw.Draw(canvas).rounded_rectangle(box, radius=radius, outline=_shade(base, -0.22), width=2)

    draw = ImageDraw.Draw(canvas)
    font_bold = load_font(46, bold=True)
    font_mid = load_font(26, bold=True)
    font_small = load_font(22)
    ink = (58, 50, 48)
    muted = (138, 128, 124)

    # 页眉
    draw.text((MARGIN, 46), "NAILFIT · 样式示意", font=font_small, fill=_shade(accent, -0.3))
    name = str(style.get("name") or style.get("id") or "未命名款式")
    size = 46
    while draw.textlength(name, font=font_bold) > width - 2 * MARGIN and size > 26:
        size -= 4
        font_bold = load_font(size, bold=True)
    draw.text((MARGIN, 84), name, font=font_bold, fill=ink)
    draw.text((MARGIN, 150), "样例库占位示意图 · 非真实款式", font=font_mid, fill=muted)

    # 底部信息 chips（去重，避免「镜面 / 镜面」重复）
    chips: list[str] = []
    seen_chips: set[str] = set()
    for tag in (style.get("tags") or [])[:3]:
        text = str(tag)
        if text not in seen_chips:
            seen_chips.add(text)
            chips.append(text)
    if style_word in STYLE_TEXT and STYLE_TEXT[style_word] not in seen_chips:
        seen_chips.add(STYLE_TEXT[style_word])
        chips.append(STYLE_TEXT[style_word])
    if shape in SHAPE_TEXT and SHAPE_TEXT[shape] not in seen_chips:
        seen_chips.add(SHAPE_TEXT[shape])
        chips.append(SHAPE_TEXT[shape])
    chip_x, chip_y = MARGIN, 806
    for text in chips[:4]:
        text_w = draw.textlength(text, font=font_small)
        box_w = int(text_w) + 36
        draw.rounded_rectangle(
            (chip_x, chip_y, chip_x + box_w, chip_y + 44),
            radius=22,
            fill=_shade(bg, 0.05),
            outline=_mix(accent, (255, 255, 255), 0.4),
            width=2,
        )
        draw.text((chip_x + 18, chip_y + 9), text, font=font_small, fill=_shade(ink, -0.1))
        chip_x += box_w + 12
        if chip_x > width - MARGIN - 120:
            break

    # 脚注
    draw.text((MARGIN, 890), f"款式 id：{style.get('id') or '—'}", font=font_small, fill=muted)
    draw.text((MARGIN, 926), "占位图由标签自动生成，仅用于前端流程演示", font=font_small, fill=muted)
    return canvas


def build(
    styles: list[dict] | tuple[dict, ...],
    *,
    root: str | Path = ROOT,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """给缺图的款式生成占位图，返回统计（供 CLI / 测试共用）。"""
    base = Path(root)
    created: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for style in styles:
        style_id = str(style.get("id") or "unknown")
        image = (style.get("media") or {}).get("image") or style.get("image")
        if not image:
            failed.append(f"{style_id}: 没有 image 字段")
            continue
        target = base / str(image)
        if target.is_file() and not force:
            skipped.append(style_id)
            continue
        if dry_run:
            created.append(style_id)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            card = draw_card(style)
            card.save(target, format="JPEG", quality=88, optimize=True)
            created.append(style_id)
        except OSError as exc:
            failed.append(f"{style_id}: 写图片失败 {exc}")
    return {
        "total": len(styles),
        "created": len(created),
        "skipped": len(skipped),
        "failed": failed,
        "created_ids": created,
        "skipped_ids": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="给样例库生成占位示意图")
    parser.add_argument(
        "--styles",
        default=str(ROOT / "data" / "styles.sample.json"),
        help="款式库 JSON 路径（默认 data/styles.sample.json）",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的图片")
    parser.add_argument("--dry-run", action="store_true", help="只统计要生成哪些，不写文件")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    try:
        raw = json.loads(Path(args.styles).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"✗ 款式库文件不存在：{args.styles}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"✗ 款式库格式错误：{exc}")
        return 1
    styles = raw.get("styles") if isinstance(raw, dict) else raw

    result = build(styles, force=args.force, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"款式总数：{result['total']}")
        print(f"新生成：{result['created']}｜已存在跳过：{result['skipped']}")
        if result["failed"]:
            print(f"失败：{len(result['failed'])}")
            for item in result["failed"][:10]:
                print(f"  ✗ {item}")
        elif args.dry_run:
            print("（dry-run：以上数量为将要生成的文件数）")
        else:
            print("✓ 全部款式都有占位图")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
