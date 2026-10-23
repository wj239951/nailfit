"""把款式图片自动打成结构化标签，生成演示款式库。

- **颜色维度**（`hue` / `color_family` / `tone` / `value` / `saturation`）从图片主色计算；
- **形状 / 工艺 / 长度 / 场景 / 标签**从文件名关键词推测；
- 输出可直接被 `core.pipeline` 读取的 JSON，正式库仍建议人工复核。

用法：

    python scripts/autotag.py                       # static/demo → data/styles.demo.json
    python scripts/autotag.py --dry-run             # 只打印统计，不写文件
    python scripts/autotag.py --src static/demo --out data/styles.demo.json

人工修正：把想覆盖的字段写进 `data/demo_labels.json`（id → 字段），再用 `--overrides` 跑一遍。

    {
      "d001": {"shape": ["oval", "almond"], "scene": ["commute", "wedding"]}
    }
"""

from __future__ import annotations

import argparse
import colorsys
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

# 文件名关键词 → 色系（顺序敏感：更具体的放前面）
_FAMILY_HINTS: tuple[tuple[str, str], ...] = (
    ("berry", "berry"),
    ("plum", "berry"),
    ("mauve", "berry"),
    ("lilac", "berry"),
    ("sage", "blue_green"),
    ("olive", "blue_green"),
    ("green", "blue_green"),
    ("navy", "blue_green"),
    ("dusty", "blue_green"),
    ("blue", "blue_green"),
    ("metal", "metal"),
    ("chrome", "metal"),
    ("glitter", "glitter"),
    ("sparkle", "glitter"),
    ("red", "true_red"),
    ("brown", "orange_brown"),
    ("taupe", "orange_brown"),
    ("cream", "orange_brown"),
    ("gold", "orange_brown"),
    ("white", "mono"),
    ("black", "mono"),
    ("nude", "nude_pink"),
    ("beige", "nude_pink"),
    ("pink", "nude_pink"),
    ("pastel", "nude_pink"),
)

_STYLE_HINTS: tuple[tuple[str, str], ...] = (
    ("french", "french"),
    ("cateye", "cat_eye"),
    ("cat_eye", "cat_eye"),
    ("cat-eye", "cat_eye"),
    ("metal", "chrome"),
    ("chrome", "chrome"),
    ("glitter", "glitter"),
    ("star", "glitter"),
    ("sparkle", "glitter"),
    ("doodle", "drawing"),
    ("drawing", "drawing"),
    ("floral", "drawing"),
    ("flower", "drawing"),
    ("lace", "drawing"),
    ("cartoon", "drawing"),
    ("rhinestone", "rhinestone"),
    ("gradient", "gradient"),
    ("checker", "checker"),
    ("marble", "marble"),
    ("two_tone", "mixed"),
    ("two-tone", "mixed"),
    ("blue_white", "mixed"),
    ("polka", "drawing"),
    ("dots", "drawing"),
)

_SHAPE_HINTS: tuple[tuple[str, list[str]], ...] = (
    ("almond", ["almond", "oval"]),
    ("square", ["square", "squoval"]),
    ("round", ["round", "oval"]),
    ("oval", ["oval", "almond"]),
    ("squoval", ["squoval", "square"]),
)

_FAMILY_LABEL = {
    "nude_pink": "裸粉",
    "true_red": "正红",
    "berry": "浆果紫",
    "orange_brown": "暖棕",
    "blue_green": "蓝绿",
    "mono": "黑白",
    "metal": "金属",
    "glitter": "闪片",
}

_STYLE_LABEL = {
    "solid": "纯色",
    "french": "法式",
    "gradient": "渐变",
    "cat_eye": "猫眼",
    "chrome": "金属",
    "drawing": "手绘",
    "rhinestone": "钻饰",
    "checker": "棋盘格",
    "marble": "大理石",
    "mixed": "混搭",
    "glitter": "闪粉",
}

_SHAPE_LABEL = {
    "round": "短圆",
    "oval": "椭圆",
    "almond": "长杏仁",
    "square": "短方",
    "squoval": "方圆",
}


def _bg_rgb(img: Image.Image) -> tuple[int, int, int]:
    """用四角小块估计背景色（相册图常见：毛衣 / 桌面 / 黑底）。"""
    w, h = img.size
    patches = (
        (0, 0), (w - w // 8, 0), (0, h - h // 8), (w - w // 8, h - h // 8),
    )
    pixels: list[tuple[int, int, int]] = []
    for px, py in patches:
        for x in range(px, px + w // 8, 6):
            for y in range(py, py + h // 8, 6):
                pixels.append(img.getpixel((x, y)))
    pixels.sort()
    return pixels[len(pixels) // 2]


def _dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((int(x) - int(y)) ** 2 for x, y in zip(a, b)) ** 0.5


def dominant_rgb(path: str | Path) -> tuple[int, int, int]:
    """取图片中心区域的主色，尽量躲开背景与纯白/纯黑。"""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    bg = _bg_rgb(img)
    crop = img.crop((int(w * 0.20), int(h * 0.25), int(w * 0.80), int(h * 0.80)))
    quantized = crop.quantize(colors=8, method=Image.MEDIANCUT)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors() or [], reverse=True)
    best: tuple[int, int, int] | None = None
    for _count, index in counts:
        rgb = tuple(palette[index * 3:index * 3 + 3])
        hh, ss, vv = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        if vv > 0.95 and ss < 0.08:  # 纯白 / 高光
            continue
        if vv < 0.05:  # 纯黑
            continue
        if _dist(rgb, bg) < 40:  # 与背景太接近
            continue
        best = rgb
        break
    if best is None:
        best = tuple(palette[counts[0][1] * 3:counts[0][1] * 3 + 3])
    return best


def _classify_hue_family(hue: float, sat: float, val: float) -> str:
    if sat < 0.15:
        return "mono"
    if hue < 15 or hue >= 345:
        return "true_red"
    if hue < 75:
        return "orange_brown"
    if hue < 250:
        return "blue_green"
    return "berry"


def classify_color(name: str, rgb: tuple[int, int, int]) -> dict:
    """把主色 RGB + 文件名关键词 → 颜色维度标签。"""
    hh, ss, vv = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    hue = round(hh * 360, 1) % 360
    lower = name.lower()

    family = _classify_hue_family(hue, ss, vv)
    for keyword, value in _FAMILY_HINTS:
        if keyword in lower:
            family = value
            break

    if "cool" in lower:
        tone = "cool"
    elif "warm" in lower:
        tone = "warm"
    elif hue < 60 or hue >= 330:
        tone = "warm"
    elif 80 <= hue <= 300:
        tone = "cool"
    else:
        tone = "neutral"

    if vv >= 0.72:
        value = "light"
    elif vv <= 0.38:
        value = "deep"
    else:
        value = "mid"

    if ss <= 0.18:
        saturation = "low"
    elif ss >= 0.55:
        saturation = "high"
    else:
        saturation = "mid"

    return {
        "hue": hue,
        "color_family": family,
        "tone": tone,
        "value": value,
        "saturation": saturation,
    }


def shape_from_name(name: str) -> list[str]:
    lower = name.lower()
    for keyword, shapes in _SHAPE_HINTS:
        if keyword in lower:
            return shapes
    return ["oval", "squoval", "almond"]


def style_from_name(name: str) -> str:
    lower = name.lower()
    for keyword, style in _STYLE_HINTS:
        if keyword in lower:
            return style
    return "solid"


def length_from_name(name: str) -> str:
    lower = name.lower()
    if "long" in lower:
        return "long"
    if "short" in lower:
        return "short"
    return "mid"


def length_fit(name: str, shapes: list[str], style: str) -> str:
    """文件名没写长度时，按甲型/工艺给一个合理默认值。"""
    base = length_from_name(name)
    if base != "mid":
        return base
    if shapes[0] in {"square", "round"}:
        return "short"
    if shapes[0] in {"almond", "oval"} and style in {
        "glitter", "chrome", "rhinestone", "cat_eye", "mixed", "gradient",
    }:
        return "long"
    return "mid"


def _bed_fit(length: str, shapes: list[str]) -> list[str]:
    if length == "long":
        return ["standard", "slender"]
    if length == "short":
        return ["standard", "short_wide", "slender"]
    if "square" in shapes or "squoval" in shapes:
        return ["standard", "short_wide"]
    return ["standard", "slender"]


def _scenes(family: str, style: str, value: str) -> list[str]:
    scenes: list[str] = []
    if family in {"nude_pink", "orange_brown"} and style not in {"glitter", "chrome"}:
        scenes.append("commute")
    if style == "french" and value != "deep":
        scenes.append("wedding")
    if family in {"nude_pink", "berry"} or style in {"drawing", "rhinestone"}:
        scenes.append("date")
    if family in {"true_red", "glitter"} or style == "glitter":
        scenes.append("festival")
    if family in {"berry", "metal"} or (style == "cat_eye" and value == "deep"):
        scenes.append("cool")
    if family == "blue_green" or style in {"checker", "chrome", "mixed"} or "metal" in style:
        scenes.append("y2k")
    if not scenes:
        scenes.append("commute")
    # 去重保序，最多 3 个
    unique = list(dict.fromkeys(scenes))
    return unique[:3]


def _tags(family: str, style: str, value: str, scenes: list[str]) -> list[str]:
    tags: list[str] = []
    if family in {"nude_pink", "true_red"}:
        tags.append("显白")
    if family == "nude_pink" and value == "light":
        tags.append("温柔")
    if "commute" in scenes:
        tags.append("通勤")
    if family == "berry":
        tags.append("气质")
    if family == "blue_green":
        tags.append("清新")
    if "cool" in scenes:
        tags.append("酷感")
    if style in {"drawing", "rhinestone"}:
        tags.append("甜美")
    if family == "orange_brown" and style == "cat_eye":
        tags.append("显贵")
    if style == "glitter":
        tags.append("梦幻")
    return list(dict.fromkeys(tags))[:3] or ["百搭"]


def _name(family: str, style: str, shapes: list[str]) -> str:
    return f"{_FAMILY_LABEL.get(family, family)} · {_STYLE_LABEL.get(style, style)}{_SHAPE_LABEL.get(shapes[0], '')}"


def tag_image(path: Path, style_id: str) -> dict:
    rgb = dominant_rgb(path)
    color = classify_color(path.stem, rgb)
    shapes = shape_from_name(path.stem)
    style = style_from_name(path.stem)
    length = length_fit(path.stem, shapes, style)
    scenes = _scenes(color["color_family"], style, color["value"])
    return {
        "id": style_id,
        "name": _name(color["color_family"], style, shapes),
        "image": f"static/demo/{path.name}",
        "shape": shapes,
        "color_family": color["color_family"],
        "tone": color["tone"],
        "value": color["value"],
        "saturation": color["saturation"],
        "style": style,
        "length_fit": length,
        "nail_bed_fit": _bed_fit(length, shapes),
        "scene": scenes,
        "hue": color["hue"],
        "tags": _tags(color["color_family"], style, color["value"], scenes),
        "autotag": True,
    }


def build_library(
    src: str | Path = ROOT / "static" / "demo",
    overrides: dict | None = None,
) -> dict:
    """扫描目录下所有 jpg/png，生成演示款式库文档。"""
    folder = Path(src)
    files = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"} and not p.name.startswith("_")
    )
    if not files:
        raise ValueError(f"{folder} 里没有可处理的图片")

    styles: list[dict] = []
    for index, path in enumerate(files, start=1):
        style_id = f"d{index:03d}"
        entry = tag_image(path, style_id)
        if overrides and style_id in overrides:
            entry.update(overrides[style_id])
        styles.append(entry)

    return {
        "version": 1,
        "note": (
            "演示款式库：scripts/autotag.py 从 static/demo 自动生成，仅供工程演示；"
            "正式库请替换为自拍/可商用图片并人工复核标签。"
        ),
        "styles": styles,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自动打标签，生成演示款式库")
    parser.add_argument("--src", default=str(ROOT / "static" / "demo"), help="图片目录")
    parser.add_argument("--out", default=str(ROOT / "data" / "styles.demo.json"), help="输出 JSON")
    parser.add_argument("--overrides", default=None, help="人工修正 JSON（id → 字段）")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = parser.parse_args(argv)

    overrides = None
    if args.overrides:
        overrides = json.loads(Path(args.overrides).read_text(encoding="utf-8"))

    doc = build_library(args.src, overrides)
    if args.dry_run:
        families: dict[str, int] = {}
        styles: dict[str, int] = {}
        for entry in doc["styles"]:
            families[entry["color_family"]] = families.get(entry["color_family"], 0) + 1
            styles[entry["style"]] = styles.get(entry["style"], 0) + 1
        print(f"可处理图片：{len(doc['styles'])} 张")
        print("色系分布：", dict(sorted(families.items(), key=lambda kv: -kv[1])))
        print("工艺分布：", dict(sorted(styles.items(), key=lambda kv: -kv[1])))
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ 已生成 {out_path}（{len(doc['styles'])} 条）")
    print(f"下一步：python scripts/validate_styles.py --styles {out_path.name} --check-images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
