# data/README — 依据查证记录、数据源可获取性、合成与口径纪律

> **本文件是本题「数值口径」的唯一真相源**。代码、文档、报告只可引用，不得复述第二份。
> **基准日**：2026-10-20（本机本地时间 UTC+8）。**代理实际检索窗口**：**2026-10-19T18:35Z–18:57Z**（UTC 仍在 10-19）。
> **实测环境**：Python 3.12.10 · pandas 3.0.6 · openpyxl 3.1.5 · **Microsoft Excel 16.0 Build 20326（COM 可用）** · Node.js 可用 · Windows（本机）。

---

## 一、三态图例与检索边界

| 标记 | 含义 |
|---|---|
| ✅ | 已核对：官方文档原文可直连，或本机实测可复现（附命令/版本） |
| 🟡 | 部分核对：文档可直连但本机未实测，或反之 |
| ⬜ | 待核对 / 未获取（登记获取路径与阻断原因），**不得用确定语气** |

**检索边界（如实登记）**：

- **Reddit 不可达**：本轮检索 Reddit 超时/403，**无 Reddit 原话**。本题需求证据全部来自 Hacker News 原话（逐条可直连）与 GitHub issue，**不含 Reddit 引用**。
- 开源空白检索用 `gh api` 搜索接口，`total_count` 为**检索当日快照**，属**软论据**（无结果不等于不存在，可能只是命名不重合）。
- 星数为检索当日快照，同样属软论据。
- 代理检索窗口 **2026-10-19T18:35Z–18:57Z**（22 分钟）；本机实测在 2026-10-20 本地时间（UTC+8）进行。

---

## 二、事实核验台账（逐条：事实 → 来源 → 核实方式）

> 每条都写"来源"与"核实方式"。**官方文档只给规格，实测只给行为**——两者不互相替代。

| # | 事实 | 来源 | 核实方式 | 状态 |
|---|---|---|---|---|
| F1 | **Excel 数值精度 = 15 位有效数字** | MS 官方规格 "Excel specifications and limits"，行 `Number precision` = `15 digits`：https://support.microsoft.com/en-us/office/excel-specifications-and-limits-1672b34d-7043-467e-8e27-269d656771c3 | 官方原文 ✅ + COM 实测：`123456789012345`（15 位）保留；`1234567890123456`（16 位）→ `1234567890123450`；**`1125899906842624`（=2^50，可被 double 精确表示）→ `1125899906842620`** | ✅ |
| F1a | **推论：这是"录入路径按 15 位截断"，不是浮点表示能力不足** | 由 F1 实测推得（2^50 可精确表示却仍被置零） | 同上实测；比网上常见说法更精确，作证据锚点 | ✅ |
| F2 | **Excel 1900 闰年 bug 真实存在**（serial 60 = 不存在的 `1900-02-29`） | MS Learn："Excel incorrectly assumes that the year 1900 is a leap year"：https://learn.microsoft.com/en-us/office/troubleshoot/excel/wrongly-assumes-1900-is-leap-year | 官方原文 ✅ + 实测 serial 59/60/61 → `1900-02-28` / **`1900-02-29`** / `1900-03-01`；键入字符串 `"1900-02-29"` 得 `Value2 = 60` | ✅ |
| F3 | **1900 与 1904 日期系统相差 1462 天** | MS："The difference between the two date systems is 1,462 days"：https://support.microsoft.com/en-us/office/date-systems-in-excel-e7fe7167-48a9-4b96-bb53-5612a800b487 | 官方原文 ✅ + 实测 `2024-01-02` 在 1900 系统 = 45293；切 `Date1904=true` 后 = 43831；切换后旧单元格 45293 显示成 `2028-01-03` | ✅ |
| F4 | **Excel 没有 -0** | MS 浮点运算文章原文："IEEE has a concept of -0, and Excel doesn't" | 官方原文 ✅ + 实测键入 `-0` → `Value2 = 0`；`1/` 返回 `#DIV/0!` 错误码 | ✅ |
| F5 | **openpyxl 写数字用 `%.16g`** | openpyxl 3.1.5 源码 `openpyxl/compat/strings.py:18` | 源码 ✅ + 实测：20 万随机 double 回环失败率 **45.36%**；`%.15g` 为 **93.92%**（该组是 **极端位模式样本**，用于说明"格式化即损失"，**不代表常规数据**，**不得写进代码或报告默认输出**） | ✅ |
| F6 | **pandas 默认把一批字面量当 NaN**（`''`、`NULL`、`N/A`、`NaN`、`None`、`#N/A` 等） | pandas 3.0.6 运行时 `pandas._libs.parsers.STR_NA_VALUES` | 实测：共 **19 项**；`''` / `NULL` / 缺格 三者在默认 `read_csv` 后**塌缩为一**（均为 NaN） | ✅ |
| F7 | **pandas `low_memory` 可能混合类型推断** | pandas 文档原文 "possibly mixed type inference" | 文档原文 ✅ + 实测：同列 6 个 chunk 里 1 个推断为 `str`，其余为数值型 | ✅ |
| F8 | **SQLite 类型亲和会吞前导零，但 affinity NONE 的列保文本** | SQLite 类型亲和规则（官方 datatype3 文档） | 实测：NUMERIC 列 `'02114'→2114`（integer）、`'19.90'→19.9`（real）；**affinity NONE 的列保持文本原样**（反例成立 → "全怪 SQLite"是错的，必须归因到**具体列声明**） | ✅ |
| F9 | **openpyxl 写公式不写缓存值** | openpyxl 3.1.5 行为 | 实测：写 `=1+1` 后，同一文件三种读取得 `'=1+1'`（默认）/ `None`（`data_only=True`）/ `2`（Excel 打开另存后） | ✅ |
| F10 | **合并单元格只有左上角有值** | openpyxl 3.1.5 行为 | 实测：`B2:C2` 合并后 B2 有值，C2 为 `MergedCell`、`value is None` | ✅ |
| F11 | **隐藏行数据在 XML 里完好，读取库照读** | openpyxl 3.1.5 行为 | 实测：隐藏行在 openpyxl / calamine 中可读出 → 下游拿到"Excel 里看不见"的数据 | ✅ |
| F12 | **文本型数字与格式即语义** | openpyxl 3.1.5 行为 | 实测：`'0123'` 带 `number_format='@'`、`0.15` 带 `'0%'` —— 值都是数字，语义在 `number_format` 里；只比值会判成同一个 | ✅ |
| F13 | **真 Excel 打开-另存为 CSV 会改值**（本题核心证据） | Excel 16.0 Build 20326 COM | 实测：5 列 CSV、4 行数据，另存后 **9 个单元格被改**：`12345678901234567890`→`1.23457E+19`；`02114`→`2114`；`19.90`→`19.9`；`1e-7`→`1.00E-07`；`1234567890123456`→`1.23457E+15`；`2024-01-02`→`2024/1/2` 等 | ✅ |
| F14 | **pandas pyarrow 引擎即使 `dtype=str` 也剥前导零** | pandas issue #57666（2024-02-28）：https://github.com/pandas-dev/pandas/issues/57666 | issue 原文 ✅（未在本机复现 pyarrow 路径） | ✅（文档）/⬜（本机未复现） |
| F15 | **pandas `to_numeric` 前导零导致转换不一致** | pandas issue #64184（2026-02-17），修复 PR #66201 于 2026-07-07 合入：https://github.com/pandas-dev/pandas/issues/64184 | issue 原文 ✅ | ✅ |
| F16 | **csvkit 把带前导零的列误判为 INTEGER** | csvkit issue #977（2018-08-07）：https://github.com/wireservice/csvkit/issues/977 | issue 原文 ✅ | ✅ |
| F17 | **OpenRefine number→text 会加尾随 `.0`** | OpenRefine issue #1228：https://github.com/OpenRefine/OpenRefine/issues/1228 | issue 原文 ✅ | ✅ |
| F18 | **frictionless 2026-10 连开三个往返缺陷** | #1846（2026-10-14 默认 writer 丢微秒）、#1838（2026-10-13 Integer 字段大数 crash）、#1853（JSON geopoints 无法往返 Decimal 坐标） | issue 原文 ✅ | ✅ |

**明确不在本台账的东西**（防止被当已核验）：LibreOffice、Google Sheets、WPS 的往返行为——**未实测**，见第五节。

---

## 三、需求证据（HN 原话，逐条可直连）

| # | 原话 | 链接 | 状态 |
|---|---|---|---|
| H1 | "these ids will have been converted into scientific notation by Excel with the resulting loss of precision rendering the ids useless. We now do a cleaning step … `id_` is prepended" | https://news.ycombinator.com/item?id=49182691 | ✅ |
| H2 | "I often work with CSV files that contain 17 digit IDs … `01233998742021925` which Excel will convert lossily into scientific notation rather than leaving it as a string" | https://news.ycombinator.com/item?id=28225209 | ✅ |
| H3 | "some UPCs start with 0. Worst is when Excel saves the scientific notation back to the CSV, overwriting the correct number." | https://news.ycombinator.com/item?id=39827143 | ✅ |
| H4 | "A CSV with zip codes, Excel drops the leading zero: Boston, 02114. A CSV with text ranges: 1-10, 11-20 … becomes 10-Jan and 20-Nov!" | https://news.ycombinator.com/item?id=24070749 | ✅ |
| H5 | "Even just opening and accidentally saving … will step the leading zeros off in a CSV" | https://news.ycombinator.com/item?id=32863855 | ✅ |
| H6 | "Excel performs type-inference and coerces it into a numeric type and writes a truncated precision version of numeric fields in CSV, which is an abominable sin" | https://news.ycombinator.com/item?id=16997730 | ✅ |
| H7 | "never open this file in excel … scientific notation ISBNs, dates that were in one form … barcodes losing zeros" | https://news.ycombinator.com/item?id=24696089 | ✅ |
| H8 | "a CSV had a postal code field be interpreted as an integer by pandas, which of course results in stripping any leading 0s" | https://news.ycombinator.com/item?id=48607840 | ✅ |

**Reddit**：⬜ 未获取（本轮超时/403）。**如实说明：本题不含任何 Reddit 原话引用。**

---

## 四、数据源可获取性记录

| 数据源 | 获取方式 | 状态 | 阻断原因 / 备注 |
|---|---|---|---|
| 外部数据集（真实业务 CSV / Excel） | — | **不依赖** | 本题**零外部数据依赖**：输入全部来自合成样本池或用户本地文件 |
| 合成样本池（canary-numeric / canary-semantic / control-lossless） | `tripwire gen-fixture` 程序化生成 | ✅ 可生成 | 全程序化，`--seed` 决定全部选择 |
| Microsoft Excel（COM 通道） | 本机安装 | ✅ 本机可用 | Excel 16.0 Build 20326；**仅 Windows**，Linux CI 不可用（见 D1） |
| openpyxl | PyPI | ✅ 已安装 | 3.1.5，跨平台 |
| pandas | PyPI | ✅ 已安装 | 3.0.6 |
| SQLite | Python 标准库 | ✅ 可用 | 版本随 Python 3.12.10 |
| **LibreOffice 通道** | 本机未安装 | ⬜ **未实测** | 仅登记为二期候选，**不得声称已验证** |
| **Google Sheets 通道** | 需网络/账号 | ⬜ **未实测** | 与"零网络"红线冲突，仅记录为不可行/二期评估 |
| **WPS 通道** | 本机未安装 | ⬜ **未实测** | 同上，不得声称已验证 |
| Hacker News 原话 | 网页可直连 | ✅ 已获取 8 条 | 见第三节 |
| GitHub issue / 仓库数据 | `gh api` / 网页 | ✅ 已获取 | 检索窗口见第一节 |
| Reddit 讨论 | — | ⬜ **不可获取** | 超时/403，无原话 |

---

## 五、合成数据纪律

1. **全部程序化生成**：三组样本池（`canary-numeric` / `canary-semantic` / `control-lossless`）由 `gen-fixture --seed N --rows M` 生成，**不使用任何真实数据**。
2. **确定性**：同一 `--seed` 与 `--rows` 必须生成**逐字节一致**的 `orig.csv` 与 `expected.json`。生成器**不得**读系统时间、不得依赖 `random` 全局状态、不得依赖字典插入顺序以外的隐式顺序。
3. **白名单约定（假值登记）**：
   - 邮编样例统一用 `02114`（HN 原话中的 Boston 示例）与 `00123`，**不对应任何真实地址**；
   - 标识符样例统一用明显假的数值区间（如 `12345678901234567890`、`01233998742021925`），**源自 HN 原话示例**，不来自真实单据；
   - 文本范围样例 `1-10` / `11-20` 直接取自 HN 原话；
   - 日期样例 `2024-01-02`、`1900-02-29` 为公开讨论中的通用示例；
   - **不生成**身份证号、手机号、真实姓名、真实邮箱、真实地址、真实银行账号。
4. **禁入真实数据的兜底**：`runs/` 与 `fixtures/out/` 在 `.gitignore` 中被排除（前者可能含用户真实数据，后者是每次运行的临时落点）；入库的金样本固定在 **`fixtures/golden/`**（`--seed 42 --rows 200` 的生成留档），提交前须用 `gen-fixture` 重跑核对逐字节一致。
5. **规模诚实**：`--rows 200` 是仓库留档的默认规模；报告与文档**不得**把它描述为"大规模压测"。

---

## 六、数值口径纪律（**本题唯一数值真相源**）

### 6.1 18 条规则的谓词定义（代码只引用，不复述）

规则名的**权威清单与谓词**定义在 `src/tripwire/rules/rules.json`；本文件只定义**口径原则**，不复制第二份数值：

- 每条规则 = `{id, family, name, predicate, possible_stages}`；
- `predicate` 为纯函数（`orig_text, got_text, declared_type, stage_meta -> bool`），**禁止**网络、时钟、随机；
- 一条差异命中多条规则时，按 `id` 升序取首条，其余命中写进 `evidence.also_matched`（**不静默丢弃**）；
- 规则不得"为减少 unclassified 而放宽"：`control-lossless` 组的 precision 是硬约束。

| 族 | 规则数 | 规则名 |
|---|---|---|
| 数值 | 8 | `leading_zero_lost`、`scientific_notation_coercion`、`float_precision_truncated`、`int53_overflow`、`excel_15_digit_truncation`、`negative_zero_sign_lost`、`decimal_trailing_zero_dropped`、`exponent_form_normalized` |
| 空值 | 2 | `empty_vs_null_vs_missing`、`null_token_collision` |
| 文本 | 4 | `unicode_normalization_changed`、`whitespace_collapsed`、`bom_prepended`、`encoding_mojibake`（**只检出不修复**） |
| 时间语义 | 4 | `date_retyped_to_text`、`date_system_shift_1904`、`serial_60_phantom_date`、`number_format_dropped` |
| **合计** | **18** | — |

### 6.2 门禁三数（唯一定义）

```
GATE = (recall == 1.0) AND (precision == 1.0) AND (unclassified == 0)
```

- `recall = 命中且规则正确的差异 / expected.json 中的全部差异`；
- `precision = 命中且规则正确的差异 / 全部上报差异`；
- `unclassified` = 上报但无规则命中的差异**条数**（不是比例）；
- 三者**同时**打印在报告首屏 `GATE:` 行；任一不满足 → **exit 2**。
- `control-lossless` 组必须产出 **0 条差异**；出现任何差异即 precision 判失败。

### 6.3 退出码（唯一定义）

| 码 | 语义 |
|---|---|
| `0` | 无损（无差异且门禁通过） |
| `1` | 有损（存在差异，门禁通过） |
| `2` | **门禁失败**（recall/precision/unclassified 任一不满足） |
| `3` | 用法错误 / 拒绝运行（未声明主键、管线声明非法、缺依赖） |

> 判定通道 = 0/1/2；用法通道 = 3。**3 不计入"有损/无损"判定。**

### 6.4 fingerprint 构造（唯一定义）

```
fingerprint = sha256(f"{row_key}\x1f{col}\x1f{rule}").hexdigest()[:16]
```

- 必须**不含**时间戳、run_id、文件路径、机器名；
- 目的：同一输入在不同机器、不同 `run_id` 下产生**相同** fingerprint，使报告可跨 run diff；
- 规则名变更即 fingerprint 变更——这是**期望行为**（规则改名应当被看见）。

### 6.5 `runs/` 布局与 `stages.json` 必填字段（唯一定义）

```
runs/<run_id>/
  stage-0.csv            # 输入原文（副本，不改源文件）
  stage-<k>.csv          # 第 k 阶段输出，原始文本
  stages.json
  report.md / report.json / report.sarif
```

`stages.json` 每阶段必填：`stage_index`、`stage_name`、`columns`（名 + 声明类型）、`rows`、`cols`、`sha256`、`runtime`（`pandas_version` / `dtypes` / `excel_version` / `excel_build` / `openpyxl_version` / `sqlite_version`，不适用的字段写 `null` 而非省略）。

### 6.6 原型验证记录（✅）

原型用 14 个单元格的合成样本跑通三族管线，产出 **9 条差异**，**9 条全部命中命名规则，`unclassified = 0`**。该记录是 M3 的验收基线；原型实现不进首期代码（首期为重写）。

### 6.7 样本性质标注纪律

`data/` 与本文件出现的失败率类数字（如 openpyxl 回环失败率）**必须同时标注样本性质**（"极端位模式样本"），且**不得进入代码默认输出或报告首屏**。常规数据上的损失率依赖真实数据分布，**本题不作任何常规数据损失率承诺**。
