"""预取参考图（M24）：按款式的文本描述检索图片，写进媒体缓存。

推荐请求（/api/recommend、Streamlit）只读缓存、绝不联网；联网抓图只发生在这里：

    python scripts/prefetch_media.py                              # 本地图入库（默认，不联网）
    python scripts/prefetch_media.py --check                      # 只检查覆盖率，不联网
    python scripts/prefetch_media.py --provider pexels            # 需 PEXELS_API_KEY
    python scripts/prefetch_media.py --provider pexels --limit 5  # 先小批量试跑
    python scripts/prefetch_media.py --provider search            # 需 DEEPSEEK_API_KEY

Openverse（免 Key CC 图源）的图片需要人工复核，因此不接入本脚本的自动缓存，
请用 scripts/openverse_candidates.py 先产出候选清单、复核后再入库。

输出 data/media_cache.json（可随项目分发，保证演示可复现）。
退出码：0 = 全部有图；1 = 有缺失 / Provider 不可用 / 抓取失败。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.media import (  # noqa: E402
    DEFAULT_CACHE_PATH,
    LocalProvider,
    MediaResolver,
    PexelsProvider,
    SearchProvider,
)
from core.styles import load_styles_json  # noqa: E402

PROVIDER_CHOICES = ("local", "pexels", "search")


def build_provider(name: str, resolver: MediaResolver):
    """按名字构造 Provider；缺 Key 时返回 None 并打印可操作提示。"""
    if name == "local":
        return LocalProvider(resolver.root)
    if name == "pexels":
        if not os.environ.get("PEXELS_API_KEY"):
            print("✗ 缺少 PEXELS_API_KEY：请先设置环境变量（Pexels 免费申请），或改用 --provider local")
            return None
        return PexelsProvider(
            timeout=resolver.timeout, refs_dir=resolver.refs_dir, root=resolver.root
        )
    if name == "search":
        if not os.environ.get("DEEPSEEK_API_KEY"):
            print("✗ 缺少 DEEPSEEK_API_KEY：请先设置环境变量，或改用 --provider local / pexels")
            return None
        return SearchProvider(
            timeout=resolver.timeout, refs_dir=resolver.refs_dir, root=resolver.root
        )
    print(f"✗ 未知 Provider：{name}")
    return None


def summarize(media_map: dict[str, dict]) -> dict:
    ok = sum(1 for media in media_map.values() if media.get("image"))
    providers: dict[str, int] = {}
    for media in media_map.values():
        key = str(media.get("provider") or "none")
        providers[key] = providers.get(key, 0) + 1
    missing = [style_id for style_id, media in media_map.items() if not media.get("image")]
    return {
        "total": len(media_map),
        "with_image": ok,
        "missing": len(missing),
        "missing_ids": missing,
        "provider_counts": providers,
    }


def _print_report(result: dict, *, check: bool) -> None:
    print(f"款式总数：{result['total']}")
    print(f"有参考图：{result['with_image']}")
    print(f"缺失参考图：{result['missing']}")
    if result["provider_counts"]:
        detail = "、".join(f"{name}={count}" for name, count in sorted(result["provider_counts"].items()))
        print(f"图片来源分布：{detail}")
    if result["missing_ids"]:
        preview = "、".join(result["missing_ids"][:10])
        print(f"缺失条目（前 10 条）：{preview}")
        print("提示：联网 Provider 可用时跑一次不带 --check 的预取；或把样式图片放到 static/ 下。")
    elif check:
        print("✓ 覆盖率 100%")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="预取款式参考图到媒体缓存")
    parser.add_argument(
        "--styles",
        default=str(ROOT / "data" / "styles.demo.json"),
        help="款式库 JSON 路径（默认 data/styles.demo.json）",
    )
    parser.add_argument(
        "--cache",
        default=str(DEFAULT_CACHE_PATH),
        help="媒体缓存路径（默认 data/media_cache.json）",
    )
    parser.add_argument("--provider", default="local", choices=PROVIDER_CHOICES, help="图片 Provider")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 条（试跑用）")
    parser.add_argument("--force", action="store_true", help="忽略缓存重新解析")
    parser.add_argument("--ttl-days", type=int, default=30, help="网络图片缓存有效期（天）")
    parser.add_argument("--check", action="store_true", help="只检查覆盖率，不联网、不写缓存")
    parser.add_argument("--dry-run", action="store_true", help="解析但不写缓存文件")
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

    resolver = MediaResolver(cache_path=args.cache, ttl_days=args.ttl_days)

    if args.check:
        media_map = {
            str(style.get("id")): resolver.resolve_style(style) for style in styles
        }
    else:
        provider = build_provider(args.provider, resolver)
        if provider is None:
            return 1
        chain = [provider] if provider.name == "local" else [provider, LocalProvider(resolver.root)]
        media_map = resolver.resolve_many(
            styles,
            providers=chain,
            allow_network=args.provider != "local",
            force=args.force,
            limit=args.limit,
        )
        if not args.dry_run:
            resolver.save_cache()

    result = summarize(media_map)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_report(result, check=args.check)
        if not args.check and not args.dry_run:
            print(f"缓存文件：{args.cache}")

    return 0 if result["missing"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
