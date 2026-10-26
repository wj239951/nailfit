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


def test_vision_mode_renders_controls() -> None:
    """手照模式要有：场景/款式库下拉、上传框、自由描述、LLM 开关。"""
    at = _app()
    at.run()
    at.radio[0].set_value("手照识别").run()

    assert not at.exception
    labels = [s.label for s in at.selectbox]
    assert "使用场景" in labels
    assert "款式库" in labels
    assert len(at.get("file_uploader")) == 1
    assert any(c.label.startswith("用大模型") for c in at.checkbox)
    assert any(t.label.startswith("自由描述") for t in at.text_input)


def test_landing_shows_style_gallery() -> None:
    """首页空状态要有款式库图廊（或明确的缺图提示），不能只留一行灰字。"""
    at = _app()
    at.run()
    assert not at.exception
    assert any(block.value == "先看看款式库" for block in at.subheader)
    captions = "\n".join(str(block.value) for block in at.caption)
    assert "这里先展示" in captions or "没有可展示的图片" in captions


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
