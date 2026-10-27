"""网络参考图（M32）：推荐卡下方的 CC 授权参考图。

设计取舍：
- 参考图**不替换**主图，也不进入推荐契约（style_id 仍来自款式库）；
- 清单走 `data/references.json`（预取缓存），运行时只读本地文件，**离线可用**；
- 图片放在 `static/refs/<style_id>/`，体积大不进 git（.gitignore），清单进 git；
- 运行时会校验图片文件是否真实存在，缺图自动跳过（新克隆的仓库不会出现破图）。

清单格式（scripts/prefetch_references.py 生成）：

    {
      "version": 1,
      "generated_at": "2026-10-27T10:00:00+08:00",
      "entries": {
        "d003": [
          {
            "image": "static/refs/d003/01.jpg",
            "title": "French manicure",
            "author": "someone",
            "license": "cc0",
            "source_url": "https://...",
            "provider": "openverse"
          }
        ]
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REFERENCES_PATH = ROOT / "data" / "references.json"

#: Openverse license code -> 展示名。只收可商用的宽松许可。
LICENSE_LABELS: dict[str, str] = {
    "cc0": "CC0",
    "pdm": "Public Domain",
    "by": "CC BY",
    "by-sa": "CC BY-SA",
}
REFERENCE_LICENSES: tuple[str, ...] = tuple(LICENSE_LABELS)


def _entry_view(entry: dict[str, Any]) -> dict[str, Any] | None:
    """校验并规范化一条参考图；不合规（许可/路径/缺文件）返回 None。"""
    image = str(entry.get("image") or "").strip()
    if not image.startswith("static/"):
        return None
    license_code = str(entry.get("license") or "").strip().lower()
    if license_code not in LICENSE_LABELS:
        return None
    if not (ROOT / image).is_file():
        return None
    return {
        "image": image,
        "title": str(entry.get("title") or "").strip() or None,
        "author": str(entry.get("author") or "").strip() or None,
        "license": license_code,
        "license_label": LICENSE_LABELS[license_code],
        "source_url": str(entry.get("source_url") or "").strip() or None,
        "provider": str(entry.get("provider") or "openverse"),
    }


def load_references(path: str | Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """读取参考图清单；文件缺失/损坏返回空字典（不抛异常，保证推荐可用）。"""
    file = Path(path) if path else REFERENCES_PATH
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    catalog: dict[str, list[dict[str, Any]]] = {}
    for style_id, items in entries.items():
        if not isinstance(items, list):
            continue
        views = [view for view in (_entry_view(item) for item in items if isinstance(item, dict)) if view]
        if views:
            catalog[str(style_id)] = views
    return catalog


def references_for(
    style_id: str, *, limit: int = 3, path: str | Path | None = None
) -> list[dict[str, Any]]:
    """取某款式的参考图视图列表（最多 limit 张）。"""
    if limit <= 0:
        return []
    return load_references(path).get(str(style_id), [])[:limit]


def attach_references(
    payload: dict[str, Any], *, limit: int = 3, path: str | Path | None = None
) -> dict[str, Any]:
    """给推荐响应挂上参考图（原地修改并返回）；无清单时挂空列表。"""
    catalog = load_references(path)
    for card in payload.get("recommendations") or []:
        if not isinstance(card, dict):
            continue
        style_id = str(card.get("style_id") or "")
        card["references"] = (catalog.get(style_id) or [])[: max(limit, 0)]
    return payload
