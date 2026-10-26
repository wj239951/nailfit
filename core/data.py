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

# 可选款式库：sample = 15 款样例（随仓库提交占位图），demo = 43 款演示库
LIBRARIES: dict[str, Path] = {
    "sample": DATA_DIR / "styles.sample.json",
    "demo": DATA_DIR / "styles.demo.json",
}
DEFAULT_LIBRARY = "sample"


def library_path(name: str) -> Path:
    """款式库名字 → 文件路径；未知名字抛 ValueError（接口层映射 422）。"""
    try:
        return LIBRARIES[name]
    except KeyError:
        raise ValueError(
            f"未知款式库：{name}（可选：{', '.join(sorted(LIBRARIES))}）"
        ) from None


def _resolve(path: str | Path) -> Path:
    """相对路径按项目根目录解析，保证从任意工作目录调用都能找到数据。

    之前直接 `Path(path)`：从项目外层目录调用（README 的
    `python -m api.main`、UI 传 `data/styles.demo.json`）时会按 CWD 找文件，
    报“款式库文件不存在”，属于环境相关的隐蔽 bug。
    """
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


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
    p = _resolve(path) if path else DATA_DIR / "taxonomy.yaml"
    return _read_yaml(p, "taxonomy 数据文件")


@lru_cache(maxsize=4)
def load_rules(path: str | None = None) -> dict:
    p = _resolve(path) if path else DATA_DIR / "rules.yaml"
    return _read_yaml(p, "rules 数据文件")


@lru_cache(maxsize=4)
def load_styles(path: str | None = None) -> tuple[dict, ...]:
    p = _resolve(path) if path else DATA_DIR / "styles.sample.json"
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

    # 逐条做最小校验：坏条目直接报 DataFormatError（API 映射 503），
    # 而不是等到规则引擎里 KeyError → 500。
    seen_ids: set[str] = set()
    for index, style in enumerate(styles, start=1):
        if not isinstance(style, dict):
            raise DataFormatError(
                f"款式库格式错误：第 {index} 条不是对象（{p}）"
            )
        style_id = style.get("id")
        if not isinstance(style_id, str) or not style_id.strip():
            raise DataFormatError(
                f"款式库格式错误：第 {index} 条缺少非空字符串 id（{p}）"
            )
        if style_id in seen_ids:
            raise DataFormatError(f"款式库 id 重复：{style_id}（{p}）")
        seen_ids.add(style_id)
    return tuple(styles)


def clear_cache() -> None:
    """改完数据文件后，在长驻服务里调用一次。"""
    load_taxonomy.cache_clear()
    load_rules.cache_clear()
    load_styles.cache_clear()
