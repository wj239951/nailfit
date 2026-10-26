"""输出 DeepSeek 搜索的文本来源（趋势 / 参考链接）：只做一次 Search，不下载图片。

背景（2026-10-26 实测）：DeepSeek 的 Fetch 只返回纯文本 Markdown，不含图片，
所以「从网络抓参考图」改由 Pexels / Unsplash 或本地图库承担；Search 用来补充
「当前流行什么 / 出处在哪里」的文本证据，面试演示时可展示来源可追溯。

用法：
    python scripts/web_sources.py --query "2026 美甲流行趋势"
    python scripts/web_sources.py --query "裸色美甲" --count 3 --json
    python scripts/web_sources.py --query "法式美甲" --query "猫眼美甲"

退出码：0 = 至少一条来源；1 = 缺 Key / 请求失败 / 无结果。
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

from core.media import ProviderError, SearchProvider  # noqa: E402


def format_sources(query: str, sources: list[dict]) -> str:
    lines = [f"查询：{query}", f"来源数：{len(sources)}"]
    if not sources:
        lines.append("未找到可用来源（可提高 --count 或换更具体的查询词）。")
        return "\n".join(lines)
    for index, source in enumerate(sources, start=1):
        meta = " · ".join(
            part for part in (source.get("site"), (source.get("date") or "")[:10]) if part
        )
        lines.append("")
        lines.append(f"{index}. {source['title']}")
        if meta:
            lines.append(f"   {meta}")
        lines.append(f"   {source['url']}")
        if source.get("summary"):
            lines.append(f"   摘要：{source['summary'][:140]}")
        lines.append(
            f"   相关度：{float(source.get('relevance') or 0):.2f} · 权威度：{source.get('authority', -1)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 DeepSeek Search 拉趋势/参考来源（文本）")
    parser.add_argument("--query", action="append", required=True, help="查询词，可重复")
    parser.add_argument("--count", type=int, default=5, help="每次查询返回多少条来源")
    parser.add_argument("--timeout", type=float, default=10.0, help="单次请求超时（秒）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("✗ 缺少 DEEPSEEK_API_KEY：请先设置环境变量（项目 .env 或系统环境变量）。")
        return 1

    provider = SearchProvider(timeout=args.timeout)
    payload: dict = {"queries": [], "sources": []}
    failed = False
    for query in args.query:
        try:
            sources = provider.search_sources(query, count=args.count)
        except ProviderError as exc:
            print(f"✗ {query}：{exc}")
            failed = True
            continue
        payload["queries"].append(query)
        payload["sources"].extend(sources)
        if not args.json:
            print(format_sources(query, sources))
            print()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failed or not payload["sources"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
