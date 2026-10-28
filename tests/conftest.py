import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 演示图片被 .gitignore 排除（static/demo/），新克隆/CI 环境里没有；
# 依赖这些图片文件的测试统一打这个标记，缺图时跳过而不是报假失败
_DEMO_DIR = ROOT / "static" / "demo"
requires_demo_images = pytest.mark.skipif(
    not (_DEMO_DIR.is_dir() and any(_DEMO_DIR.glob("*.jp*g"))),
    reason="static/demo 演示图片不在仓库里，跳过依赖图片文件的测试",
)
