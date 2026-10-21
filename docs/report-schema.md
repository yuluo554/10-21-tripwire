# 报告格式（M5）

> **数值口径的唯一定义仍是 `data/README.md` §6.2–§6.5**（门禁三数 / 退出码 / fingerprint / `runs/` 布局）。
> 本文只定义**形状**：首屏三段的字面、三份产物的字段、SARIF 的映射，以及"什么情况不许产出报告"。
> 术语与 `plan/03` M5 同一套，不另立。

---

## 一、产物落点

| 文件 | 谁写 | 内容 | 写盘通道 |
|---|---|---|---|
| `runs/<run_id>/report.md` | `report` / `run --expected` | 人读：首屏三段 + 结论文禁 + 逐条归因 + 结构差异 + 逐段快照 | `serialization.write_text`（LF + 结尾一个换行） |
| `runs/<run_id>/report.json` | 同上 | 机读：`RunResult.to_json()` + `schema_version` / `generator` | `serialization.write_json` |
| `runs/<run_id>/report.sarif` | 同上 | SARIF 2.1.0：每条 finding 一个 `result` | `serialization.write_json` |

两条实现纪律：

1. **先算一次，再渲染三次**（`plan/02` §一 红线 4）：`report/model.py` 持有内存中的
   `RunResult`，三个渲染器只读它，**不各自重算**、也不回头读 `runs/`。判别 = "换一个格式，这一行的值会变吗？"
2. **写盘单点**（K11）：MD 走 `write_text`，JSON / SARIF 走 `write_json`。
   `render_json.render(result)` 与 `write_json(payload(result))` 产出**同一串字节**
   （两者都经 `serialization.dumps_json`），所以不存在第二份 JSON 规范。

**报告不写绝对路径、不含时间戳**：报告要能跨机器、跨 run 对账（fingerprint 的意义就在这里）。
`artifactLocation.uri` 只有快照文件名（`stage-<k>.csv`）。

---

## 二、首屏三段（顺序与字面固定）

`report` / `run --expected` 的 stdout **前三行**，MD 文件的**前三行**，JSON 的 `first_screen`
数组，SARIF 的 `runs[0].properties.firstScreen` —— 四处的字符串**完全同一串**
（由 `RunResult.first_screen()` 生成一次）。

```
VERDICT: LOSSY (37/1200 cells, 5 rules)
FIRST LOSS AT: stage 2 = excel_com_csv (Excel 16.0 Build 20326)
GATE: recall 1.00 precision 1.00 unclassified 0
```

| 段 | 字面 | 来源 |
|---|---|---|
| 第一段 | `VERDICT: {LOSSLESS\|LOSSY} ({差异单元格数}/{比较单元格数} cells, {命中规则数} rules)` | `RunResult.diffs` / `cells_compared` / `rules_used` |
| 第二段 | `FIRST LOSS AT: stage {k} = {stage_name} ({运行时指纹})` | `Attribution.first_seen_at` 的最小值 + 该阶段 `RuntimeMeta` |
| 第三段 | `GATE: recall {r} precision {p} unclassified {u}` | **`Gate.line()` 整行**，M4 的唯一实现 |

三条"不许自己拼"的约束：

- **第三段必须来自 `Gate`**：recall / precision / unclassified 的定义只在 `data/README.md` §6.2。
  三处渲染器各拼一份格式串，正是"三格式同源"要防的形态。
- **第二段的阶段名必须是 M1 的真实 stage 名**（`openpyxl_csv` 不得写成 `excel_csv`，K3）。
- **`unclassified` 不进"命中规则数"**：它不是规则，它单独计数（D4），在 `GATE:` 行与报告正文里各有一处。

### 单元格数与规则数

- `{差异单元格数}` = 本次上报的**单元格差异条数**（含 `unclassified` 的那些——它们也是损失）；
- `{比较单元格数}` = 对齐后逐格比较的**总格数**（结构差异不计入这个分母）；
- 结构差异单独在正文里列，**不折算**进单元格差异率（`plan/03` M2）。

---

## 三、`FIRST LOSS AT` 的三种合法形态

| 形态 | 何时出现 |
|---|---|
| `FIRST LOSS AT: none` | 无损（无单元格差异且无结构差异） |
| `FIRST LOSS AT: stage k = <stage_name> (<运行时指纹>)` | 有损失，且快照序列里能定位到"哪一步第一次变" |
| `FIRST LOSS AT: unknown (no snapshot stage carried the change)` | 有损失，但没有任何一步的快照承载了变化后的值（例如整行消失 / 只比了两份孤立文件） |

**三种形态都不省略整行**；括号里的运行时指纹按通道分族，拼不出任何一部分就写 `unknown`：

| stage | 写法 | 来源字段 |
|---|---|---|
| `excel_com_csv` | `Excel {excel_version} Build {excel_build}` | `excel_version` / `excel_build` |
| `pandas_csv` | `pandas {pandas_version}` | `pandas_version` |
| `openpyxl_csv` | `openpyxl {openpyxl_version}` | `openpyxl_version` |
| `json_sqlite_csv` | `SQLite {sqlite_version}` | `sqlite_version` |
| 其它（含 `input`） | `unknown` | —— |

> `excel_build` 经 COM 回来是浮点读数（`20326.0`）：**Build 号是整数**，所以显示时去掉 `.0`
> 尾巴；`excel_version`（`16.0`）是版本号，是另一个字段，**不动**。
> `stages.json` 里记录的仍是 COM 原样读数（K1：只改渲染，不改证物）。

---

## 四、退出码与"什么情况不产出报告"

判定口径见 `data/README.md` §6.3；这里只说**谁产出它、什么时候拒绝产出**。

| 码 | 条件 | 报告是否产出 |
|---|---|---|
| `0` | 无单元格差异、无结构差异，且门禁通过 | ✅ |
| `1` | 有差异（单元格或结构），且门禁通过 | ✅ |
| `2` | **门禁失败**（recall / precision / unclassified 任一不满足） | ✅（失败原因就是留档要看的） |
| `3` | 用法错误 / 拒绝运行（读不到 run、真值不可读、缺 `--key`、未知 `--format`） | ❌（拒绝运行不落产物） |

**判定必须有真值**：`report --expected` 是必填，`run` 不给 `--expected` 就只跑管线与快照、
**不产出任何判定**（exit 3，输出里明说"不产出有损/无损判定"与怎么补真值）。
没有 `expected.json` 就没有 recall/precision，报 0/1 等于把"没验过"写成"验过了"（D18）。

**"无损"必然是"空跑通过"**（值得记住的一条推论）：`expected.json` 只登记**会变的格**，
所以某阶段的期望集非空 ⇒ 该阶段至少有 1 条差异被上报 ⇒ 判定是 `LOSSY`。反过来
`LOSSLESS` ⇒ 该阶段期望集为空、上报为 0 ⇒ `Gate.vacuous == True`。
因此 `report` 在 `vacuous` 时**必须**在首屏之后多打一行：

```
NOTE: 本次 0 条差异 —— 门禁「通过」是空跑通过，不代表覆盖了任何样本。
```

---

## 五、三格式同源（G7）

finding 集合 = `Attribution` 列表（**含 `unclassified`**），按 `(row_key, col_index)` 有序。

| 格式 | finding 集合怎么读 | 是否同一集合 |
|---|---|---|
| MD | 逐条归因表的**首列**就是 `fingerprint`（16 位十六进制，反引号包裹，一 finding 一行） | ✅ |
| JSON | `findings[*].fingerprint` | ✅ |
| SARIF | `runs[0].results[*].partialFingerprints.primaryLocationLineHash` | ✅ |

`fingerprint = sha256(row_key ␟ col ␟ rule)[:16]`（K10；不含时间戳 / run_id / 路径 / 机器名），
所以同一输入在不同机器、不同 `run_id` 下的 fingerprint 集合相同 —— 报告可跨 run 对账。

`unclassified` 也是 finding：它进三份报告、有 `fingerprint`、在 SARIF 里 `ruleId = "unclassified"`
且 `tool.driver.rules` 里声明了它。**不塞进"其他"、不静默丢弃**（D4）。

---

## 六、`report.json`（机读）

```json
{
  "schema_version": 1,
  "generator": { "name": "tripwire", "version": "0.1.0" },
  "run_id": "…",
  "pipeline": "excel_com",
  "stage": { "index": 1, "name": "excel_com_csv", "artifact": "stage-1.csv", "runtime": "Excel 16.0 Build 20326" },
  "strategy": "key",
  "key": "id",
  "verdict": "LOSSY",
  "exit_code": 1,
  "first_screen": ["VERDICT: …", "FIRST LOSS AT: …", "GATE: …"],
  "counts": { "cell_diffs": 45, "cells_compared": 1600, "rows_compared": 200, "structures": 0, "rules": 3, "unclassified": 0 },
  "rules_used": ["decimal_trailing_zero_dropped", "…"],
  "first_loss_stage_index": 1,
  "gate": { "…": "Gate.to_json()（M4）" },
  "stages": [ "…每阶段元数据：stage_index / stage_name / columns / rows / cols / sha256 / runtime…" ],
  "findings": [ "…Attribution.to_json()（M3）：fingerprint / rule / row_key / col / first_seen_at / first_seen_stage / candidates / resolved_stage / evidence…" ],
  "structures": [ "…DiffResult.structures…" ]
}
```

`gate` 段**就是** `Gate.to_json()`（`passed` / `vacuous` / `counts` / `missing` / `unexpected` /
`wrong_rule` 都在里面）：失败明细三类分开列，不在报告层重新归类。

---

## 七、`report.sarif`（SARIF 2.1.0）

| 位置 | 值 |
|---|---|
| `version` | `"2.1.0"` |
| `$schema` | `https://json.schemastore.org/sarif-2.1.0.json` |
| `runs[0].tool.driver.name` / `version` | `tripwire` / 包版本（唯一来源 `__init__.__version__`） |
| `runs[0].tool.driver.rules[*].id` | 本次用到的规则名（含 `unclassified`），按名字排序 |
| `runs[0].results[*].ruleId` | **规则名**（`unclassified` 就是 `unclassified`） |
| `runs[0].results[*].level` | `warning` |
| `runs[0].results[*].partialFingerprints.primaryLocationLineHash` | `fingerprint`（K10） |
| `runs[0].results[*].locations[0].physicalLocation.artifactLocation.uri` | `stage-<k>.csv`（**相对文件名，不写绝对路径**） |
| `runs[0].artifacts[0].location.uri` | 同上；`properties` 里另有 `stageName` / `runtime` |
| `runs[0].invocations[0]` | `executionSuccessful = gate.passed`、`exitCode = RunResult.exit_code` |
| `runs[0].properties` | `verdict` / `firstScreen`（首屏三段）/ `gateLine` / `unclassified` / `rulesUsed` |

`results[*].properties` 另带上下文：`rowKey` / `col` / `colIndex` / `stageIndex` / `stageName` /
`firstSeenStageIndex` / `firstSeenStageName` / `resolvedStage` / `candidates` / `alsoMatched`。

> `artifactLocation.uri` 指向**本次判定阶段**的快照（"审的是哪份产物"）；
> "值第一次在哪一步变的"放在 `firstSeenStage*`。两者不同恰恰是最有信息量的情形，
> 所以不塞进一个字段（与 `plan/03` M3 的 `first_seen_stage` / `resolved_stage` 同一套口径）。

---

## 八、确定性纪律（K9）

- **渲染不读时钟、不读随机**：报告层（`report/*.py`）AST 里没有 `time` / `datetime` / `random`；
- **同一 `RunResult` 渲染两次逐字节相同**；
- **同输入两次 `run`（不同 `--out-dir`）的三个报告文件逐字节相同**（K2 的 `run_id` + 零时间戳）；
- 报告层**不 import** 差异层 / 规则层 / 门禁 / 管线，也不 `open()` / `read_text()` 读盘。

以上四条在 `tests/test_report.py` 里逐条有断言（不是文档承诺）。