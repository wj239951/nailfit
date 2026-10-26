"""Openverse 候选图清单（M26）：免 Key 的 CC 图源，只产出候选，不自动入库。

为什么单独一个脚本、而不是直接进图片链：
- Openverse 标题相关性不稳定，搜索结果需要人工看一眼再决定用哪张；
- 正式库改图要能追溯来源与许可，候选清单里带 title/creator/license/landing URL；
- 默认推荐链路（/api/recommend、Streamlit）仍然只读本地/缓存，不联网。

用法（本机访问 Openverse 需要代理）：

    python scripts/openverse_candidates.py                          # 演示库前 5 条，每条最多 2 张
    python scripts/openverse_candidates.py --limit 10 --per-style 3
    python scripts/openverse_candidates.py --proxy http://127.0.0.1:10090
    python scripts/openverse_candidates.py --json

产物：
- 候选图：.cache/openverse/<style_id>/<rank>.jpg（或 --out 指定目录，不进 git）
- 清单：.cache/openverse/candidates.json（含许可/作者/来源链接/相关性/复核状态）

退出码：0 = 至少拿到 1 张候选；1 = 没有候选 / 参数错误 / 全部检索失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.media import (  # noqa: E402
    OPENVERSE_LICENSES,
    OPENVERSE_MIN_EDGE,
    OpenverseProvider,
    ProviderError,
)
from core.styles import load_styles_json  # noqa: E402

DEFAULT_OUT = ROOT / ".cache" / "openverse"
MANIFEST_NAME = "candidates.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_manifest(
    *,
    styles_path: str,
    out_dir: Path,
    candidates: list[dict],
    searched: int,
    total: int,
    proxy: str | None,
) -> dict:
    """把候选记录整理成可人工复核、可追溯来源的清单文件。"""
    return {
        "generated_at": _now(),
        "provider": "openverse",
        "source": "https://api.openverse.org/v1/images/",
        "licenses": list(OPENVERSE_LICENSES),
        "min_edge": OPENVERSE_MIN_EDGE,
        "styles_path": styles_path,
        "styles_total": total,
        "styles_searched": searched,
        "candidate_count": len(candidates),
        "proxy": proxy or "",
        "out_dir": str(out_dir),
        "review_note": "候选图需人工复核：确认款式、清晰度、无水印后再写入款式库（media.image / license）",
        "candidates": candidates,
    }


def collect_candidates(
    styles: list[dict],
    *,
    out_dir: Path,
    per_style: int,
    limit: int | None,
    provider: OpenverseProvider,
    logger=print,
) -> tuple[list[dict], int]:
    """逐条款式检索并下载候选图；返回 (候选记录, 实际检索的款式数)。"""
    searched = 0
    seen_urls: set[str] = set()
    results: list[dict] = []
    for style in styles:
        if limit is not None and searched >= limit:
            break
        style_id = str(style.get("id") or "unknown")
        style_name = str(style.get("name") or "")
        searched += 1
        try:
            found = provider.candidates(style, limit=per_style, out_dir=out_dir)
        except ProviderError as exc:
            logger(f"  ✗ {style_id} 检索失败：{exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - 单条失败不影响整体
            logger(f"  ✗ {style_id} 处理失败：{exc}")
            continue
        kept = 0
        for item in found:
            image_url = str(item.get("image_url") or "")
            if image_url and image_url in seen_urls:
                continue
            if image_url:
                seen_urls.add(image_url)
            record = dict(item)
            record["style_id"] = style_id
            record["style_name"] = style_name
            record["review"] = {"status": "pending", "note": "人工复核后才可写入款式库"}
            results.append(record)
            kept += 1
        logger(f"  {style_id} {style_name}：候选 {kept} 张")
    return results, searched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取 Openverse 候选参考图（只产出候选清单）")
    parser.add_argument("--styles", default=str(ROOT / "data" / "styles.demo.json"), help="款式库 JSON")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="候选图输出目录（默认 .cache/openverse）")
    parser.add_argument("--per-style", type=int, default=2, help="每条款式最多保留几张候选（默认 2）")
    parser.add_argument("--limit", type=int, default=5, help="只处理前 N 条款式（默认 5）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数（默认 15）")
    parser.add_argument("--proxy", default=None, help="HTTP 代理，如 http://127.0.0.1:10090")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    try:
        styles = list(load_styles_json(args.styles))
    except FileNotFoundError:
        print(f"✗ 款式库文件不存在：{args.styles}")
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"✗ 款式库格式错误：{exc}")
        return 1

    out_dir = Path(args.out)
    provider = OpenverseProvider(
        timeout=args.timeout,
        proxy=args.proxy,
        root=ROOT,
    )

    print(f"Openverse 候选抓取：{args.styles}，最多 {args.limit} 条款式，每条 ≤{args.per_style} 张")
    if args.proxy:
        print(f"使用代理：{args.proxy}")
    candidates, searched = collect_candidates(
        styles,
        out_dir=out_dir,
        per_style=args.per_style,
        limit=args.limit,
        provider=provider,
    )

    manifest = build_manifest(
        styles_path=args.styles,
        out_dir=out_dir,
        candidates=candidates,
        searched=searched,
        total=len(styles),
        proxy=args.proxy,
    )
    manifest_path = out_dir / MANIFEST_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"检索款式：{searched} 条｜候选图：{len(candidates)} 张")
        print(f"候选清单：{manifest_path}")
        if candidates:
            print("下一步：打开清单，挑出款式/清晰度都合适的图，再人工写入款式库（media.image + license）。")
        else:
            print("提示：没拿到候选。换关键词或确认代理可用后重试；Openverse 搜索对查询词敏感。")
    return 0 if candidates else 1


if __name__ == "__main__":
    raise SystemExit(main())
