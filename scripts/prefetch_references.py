"""预取网络参考图（M32）：Openverse CC 图源 → static/refs/ + data/references.json。

用法（需要能访问 Openverse；本机通常要开代理）：

    # 演示库全部 43 款，每款 3 张（体积较大，首次会慢）
    python scripts/prefetch_references.py --library demo

    # 先小范围试跑（只跑 5 款、每款 2 张）
    python scripts/prefetch_references.py --library demo --limit 5 --per-style 2

    # 走代理 + 只检索不下载
    python scripts/prefetch_references.py --library demo --limit 3 --dry-run \
        --proxy http://127.0.0.1:10090

    # 覆盖已有清单
    python scripts/prefetch_references.py --library demo --replace

规则：只收 CC0 / PDM / CC BY / CC BY-SA；长边 ≥ --min-edge；标题或标签必须出现
美甲相关词（core/media.py 的三道过滤）。产物分两处：
- 图片：static/refs/<style_id>/01.jpg…（.gitignore，不进仓库）
- 清单：data/references.json（进仓库；API 运行时只读它，缺图自动跳过）

参考图只做展示，不进入推荐契约，也不修改款式库。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data import LIBRARIES, library_path, load_styles, load_taxonomy  # noqa: E402
from core.errors import DataFormatError, EmptyStyleLibraryError  # noqa: E402
from core.media import ProviderError, OpenverseProvider  # noqa: E402

DEFAULT_MANIFEST = ROOT / "data" / "references.json"
DEFAULT_REFS = ROOT / "static" / "refs"
MANIFEST_VERSION = 1


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": MANIFEST_VERSION, "entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"version": MANIFEST_VERSION, "entries": {}}
    data.setdefault("version", MANIFEST_VERSION)
    return data


def save_manifest(path: Path, entries: dict[str, list[dict]], *, provider: str) -> None:
    payload = {
        "version": MANIFEST_VERSION,
        "generated_at": _now_iso(),
        "provider": provider,
        "entries": {key: entries[key] for key in sorted(entries)},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def to_manifest_entry(candidate: dict) -> dict:
    return {
        "image": candidate.get("local_image"),
        "title": candidate.get("title") or None,
        "author": candidate.get("creator") or None,
        "license": candidate.get("license"),
        "license_version": candidate.get("license_version") or None,
        "source_url": candidate.get("foreign_landing_url") or None,
        "provider": "openverse",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预取 Openverse CC 参考图 → data/references.json")
    parser.add_argument(
        "--library",
        choices=sorted(LIBRARIES),
        default="demo",
        help="款式库（默认 demo；与 --styles 二选一）",
    )
    parser.add_argument("--styles", help="直接指定款式 JSON 路径（优先于 --library）")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="清单输出路径")
    parser.add_argument("--refs-dir", default=str(DEFAULT_REFS), help="图片输出目录")
    parser.add_argument("--per-style", type=int, default=3, help="每款最多几张参考图（默认 3）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个款式（0=全部）")
    parser.add_argument("--min-edge", type=int, default=600, help="图片长边下限（px）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时秒数")
    parser.add_argument("--proxy", default=None, help="代理，如 http://127.0.0.1:10090")
    parser.add_argument("--replace", action="store_true", help="覆盖已有参考图（默认保留已有）")
    parser.add_argument("--dry-run", action="store_true", help="只检索，不下载/不写清单")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 摘要")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    styles_path = Path(args.styles) if args.styles else library_path(args.library)
    try:
        styles = load_styles(str(styles_path))
        load_taxonomy()
    except (EmptyStyleLibraryError, DataFormatError, ValueError) as exc:
        print(f"✗ 款式库不可用：{exc}", file=sys.stderr)
        return 2

    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    entries: dict[str, list[dict]] = {
        str(k): list(v) for k, v in manifest.get("entries", {}).items() if isinstance(v, list)
    }
    if args.replace:
        entries = {}

    targets = [style for style in styles if args.replace or not entries.get(str(style["id"]))]
    if args.limit > 0:
        targets = targets[: args.limit]
    if not targets:
        print("✓ 无需处理：已有清单覆盖全部款式（用 --replace 覆盖）")
        return 0

    provider = OpenverseProvider(
        timeout=args.timeout,
        min_edge=args.min_edge,
        proxy=args.proxy,
        refs_dir=args.refs_dir,
    )
    summary: list[dict] = []
    failures = 0
    for index, style in enumerate(targets, start=1):
        style_id = str(style["id"])
        label = style.get("name") or style_id
        if args.dry_run:
            try:
                candidates = provider.search(style, limit=args.per_style)
            except ProviderError as exc:
                failures += 1
                print(f"  [{index}/{len(targets)}] {label} ✗ {exc}", file=sys.stderr)
                summary.append({"style_id": style_id, "found": 0, "error": str(exc)})
                continue
            print(f"  [{index}/{len(targets)}] {label} 检索到 {len(candidates)} 张（dry-run）")
            summary.append(
                {
                    "style_id": style_id,
                    "found": len(candidates),
                    "items": [
                        {"title": c["title"], "license": c["license"], "url": c["foreign_landing_url"]}
                        for c in candidates
                    ],
                }
            )
            continue
        try:
            candidates = provider.candidates(style, limit=args.per_style, out_dir=args.refs_dir)
        except ProviderError as exc:
            failures += 1
            print(f"  [{index}/{len(targets)}] {label} ✗ {exc}", file=sys.stderr)
            summary.append({"style_id": style_id, "found": 0, "error": str(exc)})
            time.sleep(0.3)
            continue
        records = [to_manifest_entry(c) for c in candidates]
        entries[style_id] = records
        print(f"  [{index}/{len(targets)}] {label} 下载 {len(records)} 张")
        summary.append({"style_id": style_id, "found": len(records)})
        if not args.dry_run:
            save_manifest(manifest_path, entries, provider="openverse")
        time.sleep(0.3)

    saved = sum(1 for v in entries.values() if v)
    if args.dry_run:
        print(f"\n[dry-run] 扫描 {len(targets)} 款，未写文件")
    else:
        print(f"\n✓ 清单：{manifest_path}（{saved} 款有参考图）")
    if args.json:
        print(
            json.dumps(
                {
                    "manifest": str(manifest_path),
                    "targets": len(targets),
                    "saved": saved,
                    "failures": failures,
                    "results": summary,
                },
                ensure_ascii=False,
            )
        )
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
