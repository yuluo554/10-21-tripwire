"""`excel_com_csv` 阶段：真 Excel COM 开 CSV -> `SaveAs` CSV。

**不是 openpyxl 阶段，也不许被当成 openpyxl**（D1 / K3）。这条通道倒不是照抄 openpyxl
的读法（openpyxl 走的是 `%.16g`），它会把值读成真正的 Excel 数字，再按 Excel 规则丢掉多余有效位；
用 `1125899906842624`（=2^50，double 可精确表示）做对照：Excel COM 输出 `1.1259E+15`，
openpyxl 保留原值。两者产出的差异形态不同，混称即制造假阴性。

实现要点（**都是本机实测踩出来的**，别"优化"掉）：
1. `CoInitialize` 每进程一次即可；**释放 COM 代理后再 `CoUninitialize`**。
   先 `CoUninitialize` 再让 `win32com` 对象析构 → 进程 **segfault（exit 139）**，
   本机实测：同一进程内连续两次"init → DispatchEx → Quit → uninit"必崩。
2. `Open` 用最小参数（只给 `Filename`）。给 `Local=True` 等参数会改变日期类字面量的解析路径。
3. `SaveAs(..., FileFormat=6)` = `xlCSV`；输出 **CRLF**（Excel 行为，不归一，K1）。
4. `DispatchEx` 而非 `Dispatch`：不复用用户已开着的 Excel 实例，避免弹窗/文件占用。
"""

from __future__ import annotations

import gc
import shutil
import sys
import tempfile
from pathlib import Path

from tripwire.csvio import parse_csv_text
from tripwire.pipeline.errors import StageFailed, StageUnavailable
from tripwire.pipeline.model import RuntimeMeta, StageResult
from tripwire.pipeline.stages.common import columns_from_header

STAGE_NAME = "excel_com_csv"

#: `xlCSV`
XL_CSV = 6


def _require_com():
    """Windows + pywin32 缺一即 `StageUnavailable`（**不回落 openpyxl**）。"""
    if sys.platform != "win32":  # pragma: no cover - 非 Windows 路径
        raise StageUnavailable(STAGE_NAME, "Excel COM 仅在 Windows 可用（Linux 请用 openpyxl 通道）")
    try:
        import pythoncom  # noqa: PLC0415 —— 可选依赖，必须函数内导入
        import win32com.client  # noqa: PLC0415
    except ImportError as error:
        raise StageUnavailable(
            STAGE_NAME, "pywin32 未安装（pip install \"tripwire[windows]\"）"
        ) from error
    return pythoncom, win32com.client


def _close_excel(pythoncom, app, workbook) -> None:
    """按**固定顺序**收尾：关文档 -> 退应用 -> 放代理 -> gc -> 反初始化。

    顺序反了（先 `CoUninitialize` 再析构）本机实测 segfault；每步单独吞异常，
    是为了不让"收尾失败"覆盖掉真正的阶段错误。
    """
    try:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
    except Exception:
        pass
    try:
        if app is not None:
            app.Quit()
    except Exception:
        pass
    workbook = None
    app = None
    gc.collect()  # 让 COM 代理在反初始化之前确实被释放
    try:
        pythoncom.CoUninitialize()
    except Exception:
        pass


def run(text: str) -> StageResult:
    """在真 Excel 里开一次 CSV 再另存为 CSV，返回 Excel 写出的**原始文本**（CRLF 保留）。"""
    pythoncom, win32com_client = _require_com()

    workdir = Path(tempfile.mkdtemp(prefix="tripwire-excel-"))
    src = workdir / "in.csv"
    dst = workdir / "out.csv"
    try:
        with open(src, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)  # 原样交给 Excel：行尾不归一

        version = build = None
        app = workbook = None
        try:
            pythoncom.CoInitialize()
            try:
                app = win32com_client.DispatchEx("Excel.Application")
            except Exception as error:  # COM 类未注册 / Excel 未装
                raise StageUnavailable(STAGE_NAME, f"无法启动 Excel COM: {error}") from error
            app.Visible = False
            app.DisplayAlerts = False
            version = str(app.Version)
            build = str(app.Build)
            try:
                workbook = app.Workbooks.Open(str(src))
                workbook.SaveAs(str(dst), FileFormat=XL_CSV)
            except Exception as error:
                raise StageFailed(STAGE_NAME, f"Excel 打开/另存失败: {error}") from error
        finally:
            _close_excel(pythoncom, app, workbook)

        if not dst.is_file():
            raise StageFailed(STAGE_NAME, "Excel 未写出目标文件")
        with open(dst, "r", encoding="utf-8", newline="") as handle:
            raw = handle.read()  # CRLF 原样读回（K1）
        table = parse_csv_text(raw)
        return StageResult(
            text=raw,
            columns=columns_from_header(table.header),
            runtime=RuntimeMeta(excel_version=version, excel_build=build),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def available() -> tuple[bool, str]:
    """探针：本机能否跑本阶段（供 `selftest` / 测试决定"跳过并标注"还是断言）。"""
    try:
        _require_com()
    except StageUnavailable as error:
        return False, error.reason
    return True, ""


__all__ = ["STAGE_NAME", "available", "run"]
