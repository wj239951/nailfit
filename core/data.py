"""数据加载：taxonomy / rules / styles。

所有数据文件都在项目根目录的 data/ 下，改数据不需要改代码。
文件缺失、格式损坏、款式库为空都抛明确异常（core/errors.py），
而不是让 FileNotFoundError / JSONDecodeError 裸奔到接口层。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml

from .errors import DataFormatError, EmptyStyleLibraryError

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def _read_yaml(path: Path, label: str) -> dict:
    if not path.exists():
        raise DataFormatError(f"{label}不存在：{path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DataFormatError(f"{label}不是合法 YAML：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise DataFormatError(
            f"{label}格式错误：根节点应为映射（mapping），实际是 {type(data).__name__}"
        )
    return data


@lru_cache(maxsize=4)
def load_taxonomy(path: str | None = None) -> dict:
    p = Path(path) if path else DATA_DIR / "taxonomy.yaml"
    return _read_yaml(p, "taxonomy 数据文件")


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> dict:
    p = Path(path) if path else DATA_DIR / "rules.yaml"
    return _read_yaml(p, "rules 数据文件")


@lru_cache(maxsize=4)
def load_styles(path: str | None = None) -> tuple[dict, ...]:
    p = Path(path) if path else DATA_DIR / "styles.sample.json"
    if not p.exists():
        raise DataFormatError(f"款式库文件不存在：{p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataFormatError(f"款式库不是合法 JSON：{p}（{exc}）") from exc

    styles = data["styles"] if isinstance(data, dict) else data
    if not isinstance(styles, list):
        raise DataFormatError(
            "款式库格式错误：应为 list，或 {\"styles\": [...]} 形式的映射，"
            f"实际是 {type(styles).__name__}"
        )
    if not styles:
        raise EmptyStyleLibraryError(f"款式库为空：{p} 里没有款式，请先录入款式数据")
    return tuple(styles)


def clear_cache() -> None:
    """改完数据文件后，在长驻服务里调用一次。"""
    load_taxonomy.cache_clear()
    load_rules.cache_clear()
    load_styles.cache_clear()
