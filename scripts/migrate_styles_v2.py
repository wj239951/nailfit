"""把款式库升级到 schema v2（brand / description / search_query / media）。

v2 的核心变化：本地库只存「结构化文本描述」，图片是展示层的东西——
运行时由 core/media.py 解析到参考图（缓存或样式自带图），失败就降级为纯文字卡。
这样 200 条正式库不必先准备 200 张图，也保住了「推荐只从库里挑」的契约。

    python scripts/migrate_styles_v2.py                    # 迁移演示库（默认）
    python scripts/migrate_styles_v2.py --styles data/styles.sample.json
    python scripts/migrate_styles_v2.py --dry-run          # 只看会改什么

幂等：已有字段一律保留（不覆盖人工填写的 brand / search_query / description）。
退出码：0 = 成功，1 = 文件或数据有问题。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 中文标签：只用于生成 description / search_query，正式库可人工改写
COLOR_LABELS = {
    "nude_pink": "裸粉奶茶",
    "true_red": "正红",
    "berry": "浆果紫",
    "orange_brown": "橘棕",
    "blue_green": "蓝绿",
    "mono": "黑白灰",
    "metal": "金属",
    "glitter": "亮片",
}
STYLE_LABELS = {
    "solid": "纯色",
    "french": "法式",
    "gradient": "渐变",
    "cat_eye": "猫眼",
    "chrome": "镜面",
    "drawing": "手绘",
    "rhinestone": "钻饰",
    "checker": "棋盘格",
    "marble": "大理石",
    "mixed": "混搭",
    "glitter": "亮片",
}
SHAPE_LABELS = {
    "round": "圆甲",
    "square": "方甲",
    "oval": "椭圆甲",
    "almond": "杏仁甲",
    "squoval": "方圆形甲",
}
SCENE_LABELS = {
    "commute": "通勤",
    "date": "约会",
    "wedding": "婚礼",
    "festival": "节日",
    "cool": "酷感",
    "y2k": "Y2K",
}
LENGTH_LABELS = {"short": "短甲", "mid": "中长甲", "long": "长甲"}

DEFAULT_BRAND = {"demo": "演示素材", "sample": "样例占位"}


def _labels(values, mapping: dict[str, str]) -> list[str]:
    return [mapping[str(v)] for v in (values or []) if str(v) in mapping]


def _description(style: dict) -> str:
    """用结构化标签生成一段可展示的款式描述（2 句）。"""
    name = str(style.get("name") or style.get("id") or "未命名款式")
    color = COLOR_LABELS.get(str(style.get("color_family")), str(style.get("color_family") or ""))
    style_label = STYLE_LABELS.get(str(style.get("style")), str(style.get("style") or ""))
    shapes = "、".join(_labels(style.get("shape"), SHAPE_LABELS))
    scenes = "、".join(_labels(style.get("scene"), SCENE_LABELS))
    tags = "、".join(str(t) for t in (style.get("tags") or [])[:3])
    length = LENGTH_LABELS.get(str(style.get("length_fit")), "")
    parts = [f"{color}{style_label}" if color or style_label else name]
    if shapes:
        parts.append(f"适配{shapes}")
    if length:
        parts.append(f"{length}可做")
    if scenes:
        parts.append(f"适合{scenes}场景")
    tail = "；".join(parts[1:])
    extra = f" 关键词：{tags}。" if tags else ""
    return f"{name}：{tail}。{extra}".strip()


def _search_query(style: dict) -> str:
    """人工可改的检索词：色系 + 款式 + 甲型 + 甲长 + 场景 + 标签，最后加「美甲」。"""
    tokens: list[str] = []
    color = COLOR_LABELS.get(str(style.get("color_family")))
    style_label = STYLE_LABELS.get(str(style.get("style")))
    if color:
        tokens.append(color)
    if style_label:
        tokens.append(style_label)
    tokens.extend(_labels(style.get("shape")[:2], SHAPE_LABELS))
    length = LENGTH_LABELS.get(str(style.get("length_fit")))
    if length:
        tokens.append(length)
    tokens.extend(_labels(style.get("scene")[:2], SCENE_LABELS))
    tokens.extend(str(t) for t in (style.get("tags") or [])[:2])
    tokens.append("美甲")
    # 去重但保留顺序
    seen: set[str] = set()
    unique = [t for t in tokens if not (t in seen or seen.add(t))]
    return " ".join(unique)


def _media(style: dict, kind: str) -> dict:
    image = style.get("image")
    local = str(image).startswith("static/") if image else False
    return {
        "image": image if local else None,
        "source_url": None,
        "license": "demo" if kind == "demo" else "placeholder",
        "provider": "local" if local else "none",
        "relevance": 5 if kind == "demo" else None,
        "fetched_at": "2026-10-26",
        "verified": kind == "demo",
        "note": (
            "演示截图素材，仅工程演示，非本手模拟效果"
            if kind == "demo"
            else "占位数据，尚无参考图"
        ),
    }


def migrate_style(style: dict, *, kind: str, fetched_at: str) -> bool:
    """就地补齐 v2 字段；返回是否有改动。"""
    changed = False
    if not style.get("brand"):
        style["brand"] = DEFAULT_BRAND.get(kind, "未标注来源")
        changed = True
    if not style.get("description"):
        style["description"] = _description(style)
        changed = True
    if not style.get("search_query"):
        style["search_query"] = _search_query(style)
        changed = True
    if not isinstance(style.get("media"), dict):
        media = _media(style, kind)
        media["fetched_at"] = fetched_at
        style["media"] = media
        changed = True
    return changed


def migrate_file(path: str | Path, *, dry_run: bool = False, fetched_at: str = "2026-10-26") -> dict:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        styles = data["styles"]
        root = data
    else:
        styles = data
        root = None

    kind = "demo" if "demo" in p.stem else "sample"
    changed = sum(1 for style in styles if migrate_style(style, kind=kind, fetched_at=fetched_at))

    if isinstance(root, dict):
        root["version"] = 2
        if not root.get("schema_note"):
            root["schema_note"] = (
                "schema v2：本地库存结构化文本描述（brand/description/search_query），"
                "图片由 core/media.py 在展示层解析，失败降级为纯文字卡。"
            )
    if changed and not dry_run:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"file": str(p), "styles": len(styles), "changed": changed, "dry_run": dry_run}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="款式库升级到 schema v2")
    parser.add_argument(
        "--styles",
        default=str(ROOT / "data" / "styles.demo.json"),
        help="款式库 JSON 路径（默认 data/styles.demo.json）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = parser.parse_args(argv)

    try:
        result = migrate_file(args.styles, dry_run=args.dry_run)
    except FileNotFoundError:
        print(f"✗ 款式库文件不存在：{args.styles}")
        return 1
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"✗ 款式库格式错误：{exc}")
        return 1

    print(f"款式库：{result['file']}")
    print(f"款式总数：{result['styles']}")
    print(f"本次补齐条目：{result['changed']}")
    if result["dry_run"]:
        print("（dry-run：未写入文件）")
    else:
        print("✓ schema v2 字段已写入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
