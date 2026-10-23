# 00 · README 总览 — 10-21-tripwire（结构化数据往返保真审计器）

> 方法论：`ai-tool-project-sprint`（装订 2026-10-21）｜布局门：`python tools/check_sprint_layout.py`｜续接对话第一件事 = 跑它

- **性质**：不参赛项目题 · 发布 GitHub **公开仓库** · 署名 yuluo554
- **产出**：仓库 `10-21-tripwire`，CLI 入口 `tripwire`；**纯本地 Python CLI，零网络**
- **状态**：**M0–M6 全部 ✅，项目完结**（公开仓库 + `v0.1.0` + Release 附件 + 发布留档）。里程碑状态以 §六 表为准；发布状态以 Release 页为准
- **定位宣言**："一份数据经过 CSV→Excel→JSON→SQLite 转一圈，哪些值悄悄变了？本工具给逐单元格差异 + 归因规则名 + 证据 + 出问题的环节。" 现有工具要么只做两文件单元格差异但不解释原因，要么只做单文件体检但不做往返对照。
- **基准日**：2026-10-20（代理实际检索窗口 **2026-10-19T18:35Z–18:57Z**，UTC 仍在 10-19）

---

## 一、文档索引表

| 文档 | 内容 | 状态 |
|---|---|---|
| `plan/00-README总览.md` | 本文档：索引 / 决策记录 / 弃选项 / 承诺-证据台账 / 招牌动词表 / 提交材料实物表 / 里程碑 | ✅ v1（骨架期） |
| `plan/01-题目文档.md` | 十段式题目定稿（头部/介绍/任务/提交材料/评分/锚点/边界） | ✅ v1 |
| `data/README.md` | 依据查证三态 + 事实核验台账 + 数据源可获取性 + 合成数据纪律 + **数值口径单一定义** | ✅ v1 |
| `plan/02-架构与技术选型.md` | 分层架构 / IR / 依赖 / 退出码 / 确定性纪律 | ✅ v1（M0） |
| `plan/03-模块详设.md` | M1–M5 接口与测试点 + 跨模块门禁清单（K 编号） | ✅ v1（M0） |
| `plan/04-数据计划.md` | 三组样本池 / 真值覆盖口径 / 夹具 schema | ✅ v1（M0） |
| `plan/05-里程碑与发布.md` | M0–M6 DoD / 出口门 / 依赖图 | ✅ v1（M0） |
| `plan/06-交付对标与决策.md` | 提交材料对照 / 评分对照 / 风险登记 / 缺口表 | ✅ v1（M0） |
| `plan/HANDOFF-M0.md` … `plan/HANDOFF-M6.md` | M0–M6 各棒收尾交接单（七节；续接入口 = 最新一份） | ✅（M0–M6） |
| `plan/RELEASE-M6.md` | 发布留档（§一 tag 前事实 / §二 tag 后追加 / §三 阶段 7 覆盖对账） | ✅（M6） |
| `AGENTS.md` | 方法论锚点 + 布局门命令 + 强制布局清单 | ✅（M0） |
| `README.md`（仓库根） | 用户向：定位 / 快速开始 / 退出码 / 隐私 | ✅ v1（M5 补全用法与报告三格式） |
| `docs/pipeline-schema.md` | 管线声明格式（阶段命名规则、禁止混称 Excel） | ✅（M1） |
| `docs/diff-schema.md` | 差异记录格式（对齐三策略语义 + `DiffRecord` / `StructureRecord` 形状） | ✅（M2） |
| `docs/rules.md` | 18 条规则人类可读表（含证据要求与反例） | ✅（M3） |
| `docs/fixture-pools.md` | 三组样本池构造纪律 | ✅（M4） |
| `docs/report-schema.md` | 报告三格式形状（首屏三段字面、SARIF 映射、退出码与拒绝判定） | ✅（M5） |

> 状态图例：✅ 已落盘 · 🟡 进行中 · ⬜ 待做。**状态列必须与里程碑同步翻转**（同一提交里改）。

---

## 二、决策记录表

| 日期 | 决策 | 结论与理由 |
|---|---|---|
| **2026-10-20** | **D1·Excel 通道拆成两个 stage 名**：`excel_com_csv`（真 Excel COM）与 `openpyxl_csv`（openpyxl） | **Excel COM 只在 Windows 有** → Linux CI 必须有 fallback。但 fallback（openpyxl）写数字用 `%.16g`，**不是** Excel 的 15 位有效数字截断行为，两者会产生**假阴性**（CI 上"无差异"，真机上有差异）。故 MVP 起就把两条通道分成两个不同 stage 名，报告只写实际跑的那个，**绝不混称"Excel"**。规则 `excel_15_digit_truncation` 的 `possible_stages` 只含 `excel_com_csv`，openpyxl 通道跑出的同类差异不会归因到该规则（而是落 `float_precision_truncated` 或 `unclassified`）——**宁可 unclassified，不伪造归因**。 |
| **2026-10-20** | **D2·归因上限是"环节"，不是"代码行"** | 工具能证明"值在 stage 2 变成这样"，不能证明"是 openpyxl 的 `%.16g` 那一行"。写"代码行"是无法兑现的承诺；写入 README 与 `docs/rules.md` 的固定句。 |
| **2026-10-20** | **D3·主键必须显式声明，无主键宁可拒绝运行** | 位置对齐遇插入行会雪崩式误报（daff / csvdiff 类工具的经典坑），而工具仍会报一个漂亮的差异数。故默认 `--align key`，未给 `--key` 即 exit 3，**不产出"0 差异"结论**。`position`/`lcs` 必须显式指定，且报告中标注所用策略。 |
| **2026-10-20** | **D4·`unclassified` 是产品特性，不是缺陷** | 归因规则永远追不上所有失真形态；把它做成"一等公民 + `--fail-on unclassified`"可让 CI 主动拦新形态。**同时防"为清零而放宽规则导致误报"**：`control-lossless` 组是硬约束，precision 恒须 1.0（M4 门禁三数含 precision==1.0）。 |
| **2026-10-20** | **D5·`tripwire` 可能与既有安全产品重名，发布前须查 PyPI 与 GitHub 同名仓库** | 已知有同名安全产品（Tripwire 是企业文件完整性监控产品）。**发布前必须核对 PyPI `tripwire` 与 GitHub 同名仓库**；若占用，发布名改为 `tripwire-audit` 或加前缀，并把改名决策记入本表（含新包名与旧名映射）。✅ 已执行（M6）：PyPI `tripwire` 与 `tripwire-audit` 均 404、GitHub `yuluo554/10-21-tripwire` 404 → 原名可用，未改名。 |
| 2026-10-20 | **D6·快照存原始文本，不存 DataFrame** | 存 DataFrame 就等于在落盘时先做一次格式转换，比较前已经丢过一次信息——这会让审计器自己成为失真源。`stage-<k>.csv` 一律写原始文本，`stages.json` 只存元数据与哈希。 |
| 2026-10-20 | **D7·`run_id` 由内容派生，不用时间戳** | `run_id = f(管线名, 输入哈希, 声明哈希)`，同输入重跑同 id，报告可跨机对账；`runs/` 被 `.gitignore` 排除，但 id 可复算。 |
| 2026-10-20 | **D8·首期三族管线，四类数据通道** | CSV / XLSX（经 Excel 或 openpyxl）/ JSON / SQLite。**不含 YAML/TOML 配置通道**（避开配置 diff 题域），也不含 MessagePack（二期）。 |
| 2026-10-20 | **D9·18 条规则首期定稿，规则表机器可读** | 放 `src/tripwire/rules/rules.json`，代码只引用不复述；`docs/rules.md` 为人类可读副本但**数值口径仍以 `data/README.md` 第六节为唯一真相源**。 |
| 2026-10-20 | **D10·不写会漂移的硬数字** | plan/01 只写规则口径与门槛来源；"20 万随机 double 回环失败率 45.36%/93.92%"属**极端位模式样本**，**不写进代码、不进报告默认输出**，只作 `data/README.md` 的核验记录并显式标注样本性质。 |

### M4 新增决策

| 日期 | 决策 | 结论与理由 |
|---|---|---|
| 2026-10-21 | **D16·样本形态的合法判据 = "变了的通道集合 ⊆ 该规则的 `possible_stages`"** | `rules.json` 的 `possible_stages` 是归因候选；D1 会把"变化发生在候选外"降级成 `unclassified`。于是**某些形态无论怎么挑都会被降级**——那不是规则错，是样本不该长那样。`rules.json` 已冻结（M4 不得改候选），所以 M4 只能靠**挑形态**让门禁成立，挑不出来的**如实点名**进 `uncovered_rules`（8 条，理由见 `docs/fixture-pools.md` §六）。**禁止为了让它们变绿去放宽谓词**（D4）。 |
| 2026-10-21 | **D17·夹具表必须稠密（每行每列都有值）** | pandas 的 dtype 推断按列：列里一个空格就把整列推成 `float64`，控制组的 `94016` 被写成 `94016.0`（假差异），precision 当场失败。M4 实测稀疏表得 59 条控制组差异。判别 = "这一列的 dtype，是我决定的还是被某个空格决定的？" |
| 2026-10-21 | **D18·`gate` 是第一条真正的判定通道；`run`/`diff`/`attribute` 维持 exit 3** | 0/1 的语义里带"门禁通过"，只有 `gate` 同时拿到 expected 与 attributions。`run` 连差异都没算、`diff` 算了但没有真值、`attribute` 有规则名但没有 recall/precision——它们报 0/1 就是"把没验过写成验过了"（D13 的延伸）。`attribute --fail-on unclassified` 仍是**门禁失败的局部形态**，不构成完整判定。 |

### M5 新增决策

| 日期 | 决策 | 结论与理由 |
|---|---|---|
| 2026-10-21 | **D19·判定通道 M5 起有三条并列：`run --expected` / `report` / `gate`；"没真值"仍是 exit 3** | D18 说的是"0/1 必须真算过门禁"，M5 把它落到出口上：`plan/02` §一 本就把"编排层 run 串起 M1→M2→M3→M5"写进架构，而首屏第三段就是门禁三数——所以 `run` 给 `--expected` 就一路走到报告并返回 0/1/2，不给就只跑管线与快照、**拒绝判定**（exit 3，输出里明说怎么补真值）。`report` 是"对已存在的 run 重算并出报告"的出口，`--expected` 必填。**这不是放宽 D18**：三条出口都调 `compute_gate`，码都来自门禁。 |
| 2026-10-21 | **D20·"无损"必然是"空跑通过"（`LOSSLESS` ⇒ `Gate.vacuous`）** | `expected.json` 只登记**会变的格**：某阶段期望集非空 ⇒ 至少上报 1 条差异 ⇒ `LOSSY`。反过来 `LOSSLESS` ⇒ 期望集空且上报 0 ⇒ `vacuous == True`。所以报告在 `vacuous` 时**必须**多打一行"空跑通过不代表覆盖了任何样本"，否则"全绿"可以只是"什么都没查"（M4 不变量 29 的 M5 落地）。 |

### 弃选项（写题期评估后不采用）

| 弃选项 | 为什么弃 |
|---|---|
| **C2·"类型推断漂移"独立成题** | 与 C1（本题）**共用 90% 引擎**（同一套管线执行器 + 同一套对齐 + 同一套差异记录），拆成两题等于同一份代码换标签；且"推断类型"这件事已被 qsv / xsv / csvkit / visidata / frictionless / pandera **做满**，无空白。→ **并入 M2 的 `--batch` 模式**（按 chunk 记录 dtype，冲突落结构记录）。 |
| **C4·"Excel 特有语义"独立成题** | 它就是 C1 的 XLSX 环节，独立成题会出现两个仓库共享同一批规则；且 `spreadsheet-auditor`（10★，2026 新）已**正面占据**"单工作簿缺陷审计"这个位置。→ **1904/1900/合并单元格/隐藏行/公式缓存/格式语义全部并入 M3 规则与 M1 阶段指纹**。 |
| **C3·"序列化协议往返"（protobuf/Avro/MessagePack）独立成题** | 与"配置 diff"题域重叠（都是 schema 驱动）；证据痛感弱于 CSV/Excel（HN 上几乎无人讨论 protobuf 往返丢值）；依赖多、规约多、真值有争议（同一消息多种合法编码）。→ **二期只接 MessagePack 作为数据通道**，且不承诺字节级等价。 |
| **弃·编码修复功能** | 与既有"编码/乱码"类需求重叠；且"猜原编码"本质是启发式，会破坏确定性纪律。→ 只做 `encoding_mojibake` **检出**，不修复。 |
| **弃·文档去重 / 相似度对齐** | 需阈值与聚类，属模糊判定；且与本题"确定性可评测"定位冲突。→ `--align lcs` 只做**内容指纹的精确 LCS**，不做相似度。 |
| **弃·自动修复 / 写回源文件** | 审计器一旦写回就失去"第三方可复核"的立场，且容易把误判变成数据破坏。→ 只读输入、只写 `runs/`。 |
| **弃·LLM 辅助归因** | 归因必须是**可复算的纯函数谓词**；LLM 归因不可复现、不可做 precision/recall 门禁。→ 全规则化。 |

---

## 三、承诺-证据台账（全项目唯一一份）

> 规则：**只此一份**，其他文档只引用不复述；状态列必须与里程碑同步翻转。状态：✅ 已达 · 🟡 进行中 · ⬜ 待做。

| 承诺项 | 素材来源 | 交付物内可达性 | 核验方式 | 状态 |
|---|---|---|---|---|
| 三族往返管线可跑通（`pandas_csv` / `excel_com_csv`+`openpyxl_csv` / `json_sqlite_csv`） | 本机实测（Python 3.12.10 / pandas 3.0.6 / openpyxl 3.1.5 / Excel 16.0 Build 20326 COM） | 纯本地依赖，无外部服务 | `tripwire run` 三份声明各跑一次，`stages.json` 阶段数正确 | ✅ M1 |
| 逐段快照存原始文本 + 内容哈希 | 设计决策 D6 | 落 `runs/<run_id>/stage-<k>.csv` | 对快照做 `sha256` 复算，与 `stages.json` 一致 | ✅ M1 |
| 运行时指纹（pandas/openpyxl/Excel Build/SQLite 版本 + dtype） | ✅ 本机可读 | 随 `stages.json` 落盘 | 快照元数据字段齐全性测试 | ✅ M1 |
| 单元格级差异 + 四项结构差异 | 真 Excel 复现 9 单元格（✅） | 纯本地 | 原型 14 单元格 / 9 差异复现 | ✅ M2 |
| 无主键拒绝运行（exit 3） | 决策 D3 | 纯本地 | 退出码测试 | ✅ M2 |
| 18 条归因规则 | 官方文档 4 条 + 本机实测 13 条（见 data/README 台账） | 规则表随包 | 原型 9/9 命中，unclassified=0 | ✅ M3 |
| 归因由快照序列筛选（非硬编码顺序） | 设计 | 纯本地 | 构造"同规则不同环节"用例，`resolved_stage` 应不同 | ✅ M3 |
| `unclassified` 一等公民 + `--fail-on` | 决策 D4 | CLI 开关 | 退出码与计数测试 | ✅ M3 |
| 三组样本池 + `expected.json` | 全程序化合成 | 随包生成器 | 同 seed 逐字节复现 | ✅ M4 |
| 门禁三数（recall/precision/unclassified） | 决策 D4 | 报告首屏 | `control-lossless` 组零误报 | ✅ M4 |
| MD/JSON/SARIF 同源 + 首屏三段 | 设计 | 纯本地 | `tests/test_report.py::test_three_formats_same_findings`（按 fingerprint 相等）+ `test_first_screen_three_lines` | ✅ M5 |
| 退出码 0/1/2/3 | 设计 | CLI 契约 | `tests/test_exit_codes.py` 四条各一条（`main` 与真实进程各一遍） | ✅ M5 |
| stable fingerprint 跨 run diff | 设计 | 报告 JSON | `tests/test_report.py::test_fingerprint_stable_across_runs`（同输入两份独立 run 的 fingerprint 集合相等） | ✅ M5 |
| 纯本地零网络 | 红线 | 无网络客户端依赖 | `tools/check_desensitized.py` 0 命中 + `tests/test_report.py::test_no_network_imports`（AST 扫描） | ✅ M5 |
| 发布：tag + Release 附产物 + 发布留档三件套 | 发布纪律 | 公开仓库 | `tools/check_desensitized.py` 0 命中；`plan/RELEASE-M6.md` §覆盖对账无空项 | ✅ M6 |
| 方法论装订（AGENTS + 布局门 + plan/00 顶部行） | `ai-tool-project-sprint` 硬约束③ | 纯本地脚本 | `python tools/check_sprint_layout.py` 全绿；`python tools/verify_gate_mutations.py` 17 组按预期（M6 后 17 红 / 0 SKIP / 0 未按预期；M6 前形态 14 红 / 3 SKIP） | ✅ M0 |
| 脱敏门（本机路径 / 用户名 / 回环代理） | 发布纪律 | 纯本地脚本 | `python tools/check_desensitized.py` 0 命中且 4 组注入变异全红 | ✅ M0 |
| 可运行骨架（CLI + 写盘单点 + 声明校验） | 设计 D11–D14 | 纯本地 | `tripwire --version` / `validate-pipeline` / `rules --count`；未实现子命令 exit 3 | ✅ M0 |

**台账外的"永不进判定路径"项**（写清以免被当欠债）：LibreOffice / Google Sheets / WPS 通道 ⬜ 未实测，**只登记为二期候选**；YAML/TOML/MessagePack 通道 ⬜ 二期。

---

## 四、招牌动词表（能力名词 → 交付态命令 → 断言基准）

| 能力名词 | 哪条交付态命令产出它 | 哪条基准/测试断言它 |
|---|---|---|
| 往返管线执行 | `tripwire run --pipeline pipelines/excel_com.json --key id` | `tests/test_pipeline_stages.py::test_three_families_produce_stages` |
| 逐段快照 | `tripwire run` 的 `runs/<run_id>/stage-<k>.csv` + `stages.json` | `tests/test_snapshots.py::test_stage_text_sha256_matches` |
| 运行时指纹 | `tripwire run` 的 `stages.json[*].runtime` | `tests/test_snapshots.py::test_runtime_fingerprint_fields` |
| 逐单元格差异 | `tripwire diff` 的 `DiffRecord[]` | `tests/test_diff_engine.py::test_prototype_nine_diffs` |
| 结构差异（行列/列序/表头） | `tripwire diff` 的 `structure[]` | `tests/test_diff_engine.py::test_structure_changes_reported_separately` |
| 归因规则名 | `tripwire attribute` 的 `Attribution.rule` | `tests/test_rules.py::test_nine_of_nine_classified` |
| 证据 | `Attribution.evidence`（orig/got/stage 指纹三元组） | `tests/test_rules.py::test_every_attribution_has_evidence` |
| 出问题的环节 | `Attribution.resolved_stage` + `--explain` 日志 `first_seen_at=...` | `tests/test_rules.py::test_first_seen_stage_from_snapshot_sequence` |
| `unclassified` 计数 | 报告首屏 `GATE` 行 + `--fail-on unclassified` 退出码 | `tests/test_rules.py::test_cli_attribute_fail_on_unclassified_exits_2`（归因入口）+ `tests/test_gate.py::test_gate_fails_on_unclassified`（门禁口径） |
| 真值夹具与门禁三数 | `tripwire gen-fixture --seed 42 --rows 200` + `tripwire gate` | `tests/test_fixture.py::test_same_seed_byte_identical`、`tests/test_gate.py::test_control_lossless_zero_false_positive` |
| 三格式报告 | `tripwire report --format md,json,sarif` | `tests/test_report.py::test_three_formats_same_findings` |

> 任一格填不出 → 该词从标题、定位宣言、README 首段、输出 schema 四处同时删除，或标"roadmap，不进首期"。**当前无空格。**

---

## 五、提交材料实物表（承诺 → 文件路径 → 里程碑 → 核对命令）

| 承诺项 | 应存在的文件路径 | 由哪个里程碑产出 | 用哪条命令核对 |
|---|---|---|---|
| CLI 可运行入口 | `pyproject.toml`（`[project.scripts] tripwire`）+ `src/tripwire/cli.py` | M5 | `git ls-files pyproject.toml src/tripwire/cli.py`；`tripwire --help` |
| 交付态退出码测试 | `tests/test_exit_codes.py` | M5 | `git ls-files tests/test_exit_codes.py`；`pytest -q tests/test_exit_codes.py` |
| 管线声明格式文档 | `docs/pipeline-schema.md` | M1 | `git ls-files docs/pipeline-schema.md` |
| 管线声明样例三份 | `pipelines/pandas.json`、`pipelines/excel_com.json`、`pipelines/json_sqlite.json` | M1 | `git ls-files pipelines/`；`tripwire validate-pipeline pipelines/*.json` |
| 18 条规则（机器可读） | `src/tripwire/rules/rules.json` | M3 | `git ls-files src/tripwire/rules/rules.json`；`tripwire rules --count` 输出 18 |
| 18 条规则（人类可读） | `docs/rules.md` | M3 | `git ls-files docs/rules.md` |
| 夹具生成器 | `src/tripwire/fixtures.py` | M4 | `git ls-files src/tripwire/fixtures.py` |
| 夹具金样本（seed 42 / 200 行） | `fixtures/golden/orig.csv`、`fixtures/golden/expected.json`、`fixtures/golden/manifest.json` | M4 | `git ls-files fixtures/golden/` |
| 样本池构造纪律 | `docs/fixture-pools.md` | M4 | `git ls-files docs/fixture-pools.md` |
| 门禁三数实现 | `src/tripwire/gate.py` | M4 | `git ls-files src/tripwire/gate.py`；`tripwire gate --help` |
| 报告渲染器（三格式同源） | `src/tripwire/report/model.py`、`render_md.py`、`render_json.py`、`render_sarif.py` | M5 | `git ls-files src/tripwire/report/`；`tripwire report --help` |
| 报告测试（出口门 E5） | `tests/test_report.py` | M5 | `git ls-files tests/test_report.py`；`pytest -q tests/test_report.py tests/test_exit_codes.py` |
| 报告格式文档 | `docs/report-schema.md` | M5 | `git ls-files docs/report-schema.md` |
| 发布留档 | `plan/RELEASE-M6.md` | M6 | `git cat-file -e <tag>:plan/RELEASE-M6.md` |

> **每一项都必须指得到一个文件**；指不出的现在就删，不留到评分表里变成无主承诺。

---

## 六、里程碑初稿

| 里程碑 | 内容 | DoD（完成判据） | 状态 |
|---|---|---|---|
| **M0 · 计划与装订** | `plan/00–06` + `data/README` + `AGENTS.md` + 布局门 + 脱敏门 + 可运行骨架（CLI / 写盘单点 / 管线声明校验）+ 冒烟测试 | 布局门全绿且 13 组变异全红（V1–V13）；脱敏门 0 命中且 4 组变异全红（D1–D4）；`tripwire --help/--version/validate-pipeline/rules --count` 可运行；未实现子命令 exit 3；`pytest -q` 绿 | ✅ |
| **M1 · 数据先行** | 三族管线执行器 + `stages.json` + 逐段文本快照 + 运行时指纹。**先做 Excel COM 通道真机验证**（Windows），再补 `openpyxl_csv` 作为可跑的 fallback 通道（**两个不同 stage 名**） | 三条管线各跑通一次；`stages.json` 含每阶段列类型/行列数/内容哈希；`stage-<k>.csv` 为原始文本且哈希可复算；缺依赖时显式失败 | ✅ |
| **M2 · 差异引擎** | 对齐三策略（`key` 默认 / `position` / `lcs`）+ 四项结构差异 + `--batch` dtype 漂移吸收 | 未给主键 exit 3；原型 9 差异可复现；差异排序稳定（两次运行逐字节一致） | ✅ |
| **M3 · 归因规则** | 18 条四族规则 + 快照序列筛选 + `unclassified` 一等公民 + `--fail-on` | 原型 9/9 命中、unclassified=0；构造"同规则不同环节"用例 `resolved_stage` 不同；`--explain` 日志格式符合 `data/README` 口径 | ✅ |
| **M4 · 夹具与门禁** | `gen-fixture` 三组样本池 + `expected.json` + 门禁三数 | 同 seed 逐字节一致（两层）；`control-lossless` 组零误报；三数任一不满足 exit 2；三数打印在报告首屏 | ✅ |
| **M5 · 报告与 CI 出口** | MD/JSON/SARIF 同源 + 首屏三段 + 退出码 0/1/2/3 + stable fingerprint + 零网络 AST 守门 | 三格式差异集合一致（按 fingerprint）；四条退出码各一条测试（`main` 与真实进程一致）；同输入两次 run 的 fingerprint 集合相等且报告逐字节一致；`tripwire report --help` / `--help` 可运行 | ✅ |
| **M6 · 脱敏与发布** | 公开仓库发布 | **`git tag` + GitHub Release（附产物：sdist + wheel + `SHA256SUMS`）+ 发布留档 `plan/RELEASE-M6.md`（在 tag 之前落盘进 tag 树，两栏 + 阶段 7 覆盖对账）**；`python tools/check_desensitized.py` 0 命中 | ✅ |

> **DoD 产物口径**：选 **A) Release 附产物**（sdist + wheel + `SHA256SUMS`，由 CI 生成并上传）。该口径自首提交起不得降级。
> **tag 时点口径**：`plan/RELEASE-M6.md` 必须在 tag 之前写好并进 tag 树；tag 后才产生的事实（CI run id / 附件 sha256 / 真下载复核）作为追加提交，在留档里分"tag 时点事实 / tag 后追加事实"两栏写。
