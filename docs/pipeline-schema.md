# 管线声明格式（`pipelines/*.json`）

> 本文只描述**声明形状与阶段命名规则**。数值口径（`run_id` 构造、`stages.json` 必填字段、
> 退出码）的唯一真相源是 `data/README.md` §6，此处只引用不复述。
> 代码侧单点 = `src/tripwire/pipeline/schema.py`（校验）与 `pipeline/runner.py`（执行）。

---

## 一、声明形状

```json
{
  "name": "excel_com",
  "input": "csv",
  "schema_version": 1,
  "stages": [
    { "stage_name": "excel_com_csv", "engine": "excel_com" }
  ]
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | string | ✅ | 非空；**同一份语义换文件名也算同一条管线**（`run_id` 只认语义，不认路径） |
| `input` | string | ✅ | 首期只允许 `"csv"` |
| `schema_version` | int | ✅ | 必须为 `1` |
| `stages` | array | ✅ | 非空；`stage_name` 在本声明内不得重复 |

未知字段被忽略（前向兼容），但**未知 `stage_name` / `engine` 是硬错误**。

---

## 二、阶段命名规则（`stage_name`）

| `stage_name` | `engine` | 实际做的事 | 依赖 |
|---|---|---|---|
| `pandas_csv` | `pandas` | `pandas.read_csv` → `DataFrame.to_csv` | `pandas` |
| `excel_com_csv` | `excel_com` | 真 Excel（COM）打开 CSV → `SaveAs` CSV | Windows + Excel + `pywin32` |
| `openpyxl_csv` | `openpyxl` | CSV → xlsx → 读回 → CSV | `openpyxl` |
| `json_sqlite_csv` | `json_sqlite` | CSV → JSON → SQLite 表 → `SELECT` → CSV | 标准库 |

四条硬规则：

1. **`stage_name` 与 `engine` 一一对应。** 把 `openpyxl` 的结果标成 `excel_com_csv`
   是本项目的**禁止项**（`test_validate_pipeline_rejects_engine_stage_mismatch` 会红）。
2. **`stage_name` 是用户可见标识**，出现在 `stages.json`、报告首屏 `FIRST LOSS AT`、
   SARIF 的 `artifactLocation.uri`（`stage-<k>.csv` 之外还有 `stage_name` 字段）。
   改名 = 破坏跨 run 可比性，因此**不做别名**（没有 `excel_csv`、没有 `csv_pandas`）。
3. **禁止混称 Excel。** `openpyxl` 不是 Excel：它写数字用 `%.16g`，而 Excel 走自己的
   数字模型（15 位有效数字截断）。两者对 `1125899906842624`（2^50）产出不同结果，
   所以报告、日志、文档里**不得**把 `openpyxl_csv` 简写成 "Excel" 或 "excel"。
4. **失败不回落。** 缺依赖时该阶段抛 `StageUnavailable` → 整条管线终止 → `exit 3`，
   **不得**自动改用 `openpyxl_csv` 顶上（那会把"没测成"伪装成"测过了"）。

---

## 三、阶段序号

`stages.json` 的 `stage_index` 与快照文件名一一对应：

```
stage-0.csv    输入原文副本（stage_name = "input"，不是通道）
stage-1.csv    第 1 个声明的阶段的输出
stage-<k>.csv  第 k 个声明的阶段的输出
```

`stage_index` 是 **1-based 的输出序号**：第一份输出就是 `stage 1`。
M3 的 `--explain` 日志里 `first_seen_at=stage <k>` 与这里**同一套编号**。

多阶段声明（例如先走 Excel 再走 SQLite）目前合法但未被任何样例使用：

```json
"stages": [
  { "stage_name": "excel_com_csv", "engine": "excel_com" },
  { "stage_name": "json_sqlite_csv", "engine": "json_sqlite" }
]
```

---

## 四、校验与失败路径

```bash
tripwire validate-pipeline pipelines/*.json      # 只校验，不执行；非法 -> exit 3
tripwire run --pipeline pipelines/pandas.json --input data.csv --key id
```

| 情形 | 行为 |
|---|---|
| 声明缺字段 / 未知 `stage_name` / 引擎与阶段不匹配 | 校验失败，`exit 3`，不执行任何阶段 |
| `--align key` 但没给 `--key` | `exit 3`，**不产出任何** run 目录 |
| 阶段缺依赖（无 pandas / 无 openpyxl / 无 Excel COM） | 该阶段记 `failed` 进 `stages.json` 后终止，`exit 3` |
| 输入不是合法 UTF-8 | `exit 3`（首期只承诺 UTF-8，不猜原编码） |
| 同 `run_id` 目录已存在且指纹一致 | 幂等复用，不重跑 |
| 同 `run_id` 目录已存在但指纹不一致 | 报冲突，`exit 3`（同 id 必须同内容） |

**M5 起 `run` 会判定——但只在给了真值的时候。** 0 = 无损、1 = 有损、2 = 门禁失败，
三者的定义里都带"门禁三数"，而门禁要有 `--expected`（recall / precision 的分母来自真值）：

| 命令 | 退出码 |
|---|---|
| `run --expected expected.json` | 0 / 1 / 2（`plan/01` §二 M5 的判定通道） |
| `report --run-id <id> --expected expected.json` | 0 / 1 / 2（重算同一批快照并出三格式报告） |
| `gate --run-id <id> --expected expected.json` | 0 / 1 / 2（M4 的第一条判定通道） |
| `run`（**无 `--expected`**）/ `diff` / `attribute` | **3**，并在输出里明确写"不产出有损/无损判定" |

**跑通 ≠ 判为无损**：没有真值就没有门禁三数，这几条命令宁可走用法通道 3 也不报 0/1
（D18；`docs/report-schema.md` §四 有完整对照表）。

---

## 五、`stages.json`（引用）

字段清单与含义以 `data/README.md` §6.5 为准，重点是两条：

- `runtime` 的六个键**永远齐**，不适用写 `null` 而不是省略（省略与"不适用"在 JSON 里无法区分）；
- `stages.json` **不含时间戳**：`data/README.md` §6.5 的字段表里没有时间类字段，
  而"同输入双跑逐字节一致"是硬承诺——加一个 `generated_at` 会让它只在同一天内成立。

`run_id` 的构造见 `data/README.md` §6.5 与 `plan/02` §五 K2：
`sha256(pipeline_name | input_sha256 | decl_sha256)[:16]`，其中 `decl_sha256` 只哈希
**语义字段**（`name` / `input` / `schema_version` / `stages`），不含文件路径与缩进。

---

## 六、已知未验证项

| 项 | 状态 | 说明 |
|---|---|---|
| `excel_com_csv` 在 Linux / macOS | ⬜ 不适用 | COM 仅 Windows；其他平台上该阶段 `exit 3` 并写明原因，**不算已验证** |
| `excel_com_csv` 在无 Excel 的 Windows | ⬜ 未测 | 预期：`DispatchEx` 失败 → `StageUnavailable` → `exit 3` |
| 多阶段声明（2 个以上阶段串联） | 🟡 结构支持、未经样例验证 | 执行器支持，`pipelines/` 里无样例；首期不承诺 |
