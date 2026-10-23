"""数据加载层单测：路径解析 + 款式库最小校验（全面审计回归）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.data import load_styles
from core.errors import DataFormatError

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "tests" / "_tmp_data"


def _write(name: str, payload: object) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_styles_resolves_relative_path_from_any_cwd(monkeypatch) -> None:
    """从项目外层目录（CWD 不是项目根）也要能加载相对路径，之前会报文件不存在。"""
    monkeypatch.chdir(ROOT / "tests")
    styles = load_styles("data/styles.sample.json")
    assert len(styles) >= 10


def test_load_styles_rejects_entry_without_id() -> None:
    try:
        path = _write("no_id.json", {"styles": [{"name": "缺 id"}]})
        with pytest.raises(DataFormatError, match="id"):
            load_styles(path)
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)


def test_load_styles_rejects_duplicate_ids() -> None:
    try:
        path = _write("dup.json", {"styles": [{"id": "s1"}, {"id": "s1"}]})
        with pytest.raises(DataFormatError, match="重复"):
            load_styles(path)
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)


def test_load_styles_rejects_non_dict_entry() -> None:
    try:
        path = _write("non_dict.json", {"styles": ["oops"]})
        with pytest.raises(DataFormatError, match="对象"):
            load_styles(path)
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)
