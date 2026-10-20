"""`pandas_csv` 阶段：`pandas.read_csv` -> `DataFrame.to_csv`。

**这是全项目唯一允许出现 pandas 的地方**（`plan/02` §一 红线 2、K1）。
它模仿"用户拿 pandas 转了一圈"这条最普遍的真实路径，因此**必须**保留 pandas 的默认行为：
默认 `keep_default_na=True`（`''` / `NULL` / `N/A` 塌缩为 NaN，F6）、默认 dtype 推断
（`02114` 会按字符串、`19.90` 会变 `19.9`，F6/F7）。这些正是要被检出的失真，
所以本文件**不得**为了"跑得干净"而加 `dtype=str` / `keep_default_na=False`。

`dtypes` 指纹记录的是**读入侧**推断结果（不是输出侧），它是"pandas 看见了什么"的证据。
"""

from __future__ import annotations

from tripwire.pipeline.errors import StageUnavailable
from tripwire.pipeline.model import ColumnMeta, RuntimeMeta, StageResult
from tripwire.pipeline.stages.common import rows_to_text

STAGE_NAME = "pandas_csv"


def _require_pandas():
    try:
        import pandas  # noqa: PLC0415 —— 函数内导入：缺 pandas 的机器仍能 import 本包
    except ImportError as error:  # pragma: no cover - 依赖缺失路径
        raise StageUnavailable(STAGE_NAME, "pandas 未安装（pip install tripwire 应自带）") from error
    return pandas


def run(text: str) -> StageResult:
    """执行一次 pandas 读写往返，返回**原始文本**（K1：不回传 DataFrame）。"""
    pandas = _require_pandas()

    import io

    frame = pandas.read_csv(io.StringIO(text, newline=""))

    # 读入侧 dtype 指纹：值一律转字符串，保证 JSON 可序列化且跨 pandas 版本稳定可比
    dtypes = {str(name): str(dtype) for name, dtype in frame.dtypes.items()}

    buffer = io.StringIO(newline="")
    frame.to_csv(buffer, index=False, lineterminator="\n")
    out_text = buffer.getvalue()

    columns = tuple(
        ColumnMeta(name=str(name), declared_type=dtypes.get(str(name))) for name in frame.columns
    )
    return StageResult(
        text=out_text,
        columns=columns,
        runtime=RuntimeMeta(pandas_version=str(pandas.__version__), dtypes=dtypes),
    )


def available() -> tuple[bool, str]:
    try:
        _require_pandas()
    except StageUnavailable as error:
        return False, error.reason
    return True, ""


__all__ = ["STAGE_NAME", "available", "run"]
