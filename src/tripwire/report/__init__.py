"""报告层（M5）：`plan/02` §一 红线 4 —— **先算一次再渲染三次**。

```
model.py        RunResult + build_run_result()（唯一在内存中算结论的地方）
render_md.py    render(result) -> Markdown 文本
render_json.py  render(result) -> JSON 文本；payload(result) -> 机读载荷
render_sarif.py render(result) -> SARIF 2.1.0 文本；payload(result) -> SARIF 载荷
```

三个渲染器**只读 `RunResult`**（AST 守门见 `tests/test_report.py`）：不 import 差异层 /
规则层 / 门禁 / 管线，也不回头读 `runs/`。首屏三段的字面只在 `model.py` 拼一次。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from tripwire import serialization
from tripwire.report import render_json, render_md, render_sarif
from tripwire.report.errors import ReportError
from tripwire.report.model import (
    FORMATS,
    REPORT_FILENAMES,
    RunResult,
    build_run_result,
    load_expected,
    runtime_label,
)

__all__ = [
    "FORMATS",
    "REPORT_FILENAMES",
    "ReportError",
    "RunResult",
    "build_run_result",
    "load_expected",
    "render_json",
    "render_md",
    "render_sarif",
    "runtime_label",
    "write_reports",
]


def write_reports(
    result: RunResult,
    run_dir: str | Path,
    formats: Iterable[str] = FORMATS,
) -> list[Path]:
    """把选中格式落到 `runs/<run_id>/report.<fmt>`（`data/README` §6.5 的布局）。

    写盘单点（K11）：MD 走 `write_text`（LF + 结尾一个换行），JSON / SARIF 走 `write_json`
    ——三者都来自同一个 `RunResult`，所以"三格式同源"是结构保证而不是纪律。
    """
    target_dir = Path(run_dir)
    written: list[Path] = []
    for name in formats:
        path = target_dir / REPORT_FILENAMES[name]
        if name == "md":
            written.append(serialization.write_text(path, render_md.render(result)))
        elif name == "json":
            written.append(serialization.write_json(path, render_json.payload(result)))
        elif name == "sarif":
            written.append(serialization.write_json(path, render_sarif.payload(result)))
        else:  # pragma: no cover - 调用方已校验，这里只是不静默吞掉未知格式
            raise ReportError(f"未知报告格式: {name}（可用: {', '.join(FORMATS)}）")
    return written