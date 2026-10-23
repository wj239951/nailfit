"""校验款式库数据（字段 / 枚举 / 去重 / 图片存在性）。

    python scripts/validate_styles.py                    # 只校验结构
    python scripts/validate_styles.py --check-images     # 同时检查图片文件
    python scripts/validate_styles.py --styles data/styles.json
    python scripts/validate_styles.py --json

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

from core.data import load_taxonomy  # noqa: E402
from core.styles import check_images, load_styles_json, validate_styles  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 NailFit 款式库数据")
    parser.add_argument(
        "--styles",
        default=str(ROOT / "data" / "styles.sample.json"),
        help="款式库 JSON 路径（默认 data/styles.sample.json）",
    )
    parser.add_argument("--check-images", action="store_true", help="检查 image 文件是否存在")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    styles = load_styles_json(args.styles)
    errors = validate_styles(styles, load_taxonomy())
    if args.check_images:
        errors.extend(check_images(styles, ROOT))

    if args.json:
        print(
            json.dumps(
                {"file": args.styles, "styles": len(styles), "ok": not errors, "errors": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"款式库：{args.styles}")
        print(f"款式总数：{len(styles)}")
        if errors:
            print(f"\n发现 {len(errors)} 个问题：")
            for item in errors:
                print(f"  ✗ {item}")
            if args.check_images and "sample" in Path(args.styles).stem:
                print("\n提示：占位数据本身没有图片，这里报缺失是正常的。")
        else:
            print("\n✓ 全部通过")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
