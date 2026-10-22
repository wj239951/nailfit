"""数据加载：taxonomy / rules / styles。

所有数据文件都在项目根目录的 data/ 下，改数据不需要改代码。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


@lru_cache(maxsize=4)
def load_taxonomy(path: str | None = None) -> dict:
    p = Path(path) if path else DATA_DIR / "taxonomy.yaml"
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> dict:
    p = Path(path) if path else DATA_DIR / "rules.yaml"
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=4)
def load_styles(path: str | None = None) -> tuple[dict, ...]:
    p = Path(path) if path else DATA_DIR / "styles.sample.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    styles = data["styles"] if isinstance(data, dict) else data
    return tuple(styles)


def clear_cache() -> None:
    """改完数据文件后，在长驻服务里调用一次。"""
    load_taxonomy.cache_clear()
    load_rules.cache_clear()
    load_styles.cache_clear()
