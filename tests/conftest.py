"""测试引导：把 `src/` 放进 `sys.path`，使测试无需安装包也能跑（`pip install -e .` 亦兼容）。

外加一个**跨文件共用**的夹具：`control_only_csv`（`control-lossless` 组单独成表）。
它在四条通道上都是 0 差异，是 `VERDICT: LOSSLESS`（exit 0）的唯一真实来源，
`tests/test_report.py` 与 `tests/test_exit_codes.py` 都要用，所以放这里而不是各写一份。
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "fixtures" / "golden"


@pytest.fixture()
def control_only_csv(tmp_path: Path) -> Path:
    """把金样本里的 `ctl-*` 行单独成表（seed 42 / rows 200 → 恰好 60 行）。"""
    rows = list(csv.reader((GOLDEN / "orig.csv").open(encoding="utf-8", newline="")))
    header, body = rows[0], rows[1:]
    control = [row for row in body if row[0].startswith("ctl-")]
    assert len(control) == 60, "控制组行数应为 60（seed 42 / rows 200）"
    path = tmp_path / "control.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(control)
    return path