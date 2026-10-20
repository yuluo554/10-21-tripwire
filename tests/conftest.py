"""测试引导：把 `src/` 放进 `sys.path`，使测试无需安装包也能跑（`pip install -e .` 亦兼容）。"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
