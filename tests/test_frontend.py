"""Streamlit 页面冒烟测试：没装 streamlit 时自动跳过（CI 核心测试不依赖前端依赖）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402


def _app() -> AppTest:
    assert APP.exists(), APP
    return AppTest.from_file(str(APP), default_timeout=60)


def test_app_loads() -> None:
    at = _app()
    at.run()
    assert not at.exception
    # 侧边栏：场景预设 + 7 项特征 + （可能存在的）款式库选择
    assert len(at.selectbox) >= 8
    assert len(at.button) >= 2


def test_app_runs_recommendation() -> None:
    at = _app()
    at.run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.metric) >= 3
    # 三张推荐卡 + 说明文字
    text = "\n".join(str(block.value) for block in at.markdown)
    assert "稳妥" in text or "亮点" in text or "大胆" in text


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
