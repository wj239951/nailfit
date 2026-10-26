"""校验 schema v2 的媒体字段：brand / description / search_query / media。

    python scripts/validate_media.py --check-images     # 校验演示库（含图片存在性）
    python scripts/validate_media.py --styles data/styles.json --json

规则（比 validate_styles.py 更关注「展示层能拿到什么」）：
- brand / description / search_query 必须有值（文本才是可校验的契约层）；
- media.license 必须在允许集合内；
- 非本地授权（pexels / unsplash / unknown）必须提供 source_url；
- media.image 必须是 static/... 相对路径，--check-images 时检查文件存在；
- license=placeholder 允许没有图片。

退出码：0 = 通过，1 = 有问题。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.media import LICENSES  # noqa: E402
from core.styles import load_styles_json  # noqa: E402

REQUIRED_TEXT_FIELDS = ("brand", "description", "search_query")
# 联网来源必须带 source_url 才能追溯；openverse 是 CC 许可，人工复核后入库
WEB_LICENSES = ("pexels", "unsplash", "openverse", "unknown")


def validate_media_styles(
    styles: list[dict] | tuple[dict, ...],
    *,
    check_images: bool = False,
    root: str | Path = ROOT,
) -> tuple[list[str], dict]:
    """返回 (错误列表, 统计信息)。"""
    errors: list[str] = []
    stats = {"total": len(styles), "with_image": 0, "without_image": 0, "licenses": {}, "providers": {}}
    base = Path(root)

    for style in styles:
        sid = str(style.get("id") or "<无 id>")
        for field in REQUIRED_TEXT_FIELDS:
            value = style.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{sid}: 缺少 {field}（schema v2 必填）")

        media = style.get("media")
        if not isinstance(media, dict):
            errors.append(f"{sid}: 缺少 media 对象（schema v2 必填）")
            continue

        license_name = str(media.get("license") or "")
        if license_name not in LICENSES:
            errors.append(f"{sid}: media.license 非法取值 {license_name!r}（可选 {list(LICENSES)}）")
        stats["licenses"][license_name] = stats["licenses"].get(license_name, 0) + 1
        provider = str(media.get("provider") or "none")
        stats["providers"][provider] = stats["providers"].get(provider, 0) + 1

        relevance = media.get("relevance")
        if relevance is not None:
            if isinstance(relevance, bool) or not isinstance(relevance, (int, float)):
                errors.append(f"{sid}: media.relevance 必须是数字")
            elif not 0 <= float(relevance) <= 5:
                errors.append(f"{sid}: media.relevance 必须在 0-5 之间")

        image = media.get("image")
        if image:
            if not str(image).startswith("static/"):
                errors.append(f"{sid}: media.image 应使用 static/... 相对路径，当前 {image!r}")
            elif check_images and not (base / str(image)).is_file():
                errors.append(f"{sid}: media.image 文件不存在 {image}")
            else:
                stats["with_image"] += 1
        else:
            stats["without_image"] += 1
            if license_name != "placeholder":
                errors.append(f"{sid}: 没有参考图但 license={license_name!r}（无图时应为 placeholder）")

        if license_name in WEB_LICENSES and not media.get("source_url"):
            errors.append(f"{sid}: license={license_name!r} 必须提供 source_url（可追溯来源）")

    return errors, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验款式库的 schema v2 媒体字段")
    parser.add_argument(
        "--styles",
        default=str(ROOT / "data" / "styles.demo.json"),
        help="款式库 JSON 路径（默认 data/styles.demo.json）",
    )
    parser.add_argument("--check-images", action="store_true", help="检查参考图文件是否存在")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    try:
        styles = load_styles_json(args.styles)
    except FileNotFoundError:
        print(f"✗ 款式库文件不存在：{args.styles}")
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"✗ 款式库格式错误：{exc}")
        return 1

    errors, stats = validate_media_styles(styles, check_images=args.check_images)
    payload = {"file": args.styles, "ok": not errors, "errors": errors, **stats}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"款式库：{args.styles}")
        print(f"款式总数：{stats['total']}｜有参考图：{stats['with_image']}｜无图：{stats['without_image']}")
        print("授权分布：" + "、".join(f"{k}={v}" for k, v in sorted(stats["licenses"].items())))
        if errors:
            print(f"\n发现 {len(errors)} 个问题：")
            for item in errors[:30]:
                print(f"  ✗ {item}")
            if len(errors) > 30:
                print(f"  … 其余 {len(errors) - 30} 条略")
        else:
            print("\n✓ 全部通过")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
