"""报告层错误（M5）：一律由 CLI 转成用法通道 exit 3。

为什么报告层要有自己的错误类型：`report` / `run --expected` 是**判定通道**（0/1/2），
所以"读不到 run / 快照形状不对 / 阶段序号不存在"绝不能被读成"门禁失败（2）"。
把这一类统一成 `ReportError`，CLI 只需接一次就把它们全部收进用法通道 3。
"""

from __future__ import annotations


class ReportError(Exception):
    """报告无法产出（读不到产物 / 阶段序号不存在 / 对齐拒绝运行）→ CLI exit 3。"""
