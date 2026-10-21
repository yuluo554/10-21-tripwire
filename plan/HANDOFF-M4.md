# HANDOFF-M4 → M5（真值夹具生成器 + 门禁三数）

> **续接方式**（用户侧）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `py -3.12 tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = M4（夹具与门禁），已完成；下一棒 = **M5（报告渲染 MD/JSON/SARIF + 首屏三段 + 退出码四条）**。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| `src/tripwire/fixtures.py`：`generate(seed, rows, out_dir)` 写 `orig.csv` + `expected.json` + `manifest.json` | ✅ | `py -3.12 -m pytest -q tests/test_fixture.py` → 34 passed |
| **自研 splitmix64**（K8）：不读时钟、不用全局 `random`、不依赖 `set` 迭代序 | ✅ | `test_splitmix64_known_sequence`（钉死 seed=0 首个输出 `0xE220A8397B1DCDAF`）+ AST 守门 `test_generator_does_not_read_clock_or_random` |
| 三组样本池：`canary-numeric` 60 / `canary-semantic` 80 / `control-lossless` 60（seed 42 / rows 200） | ✅ | `test_golden_expected_shape` / `test_golden_id_prefixes_and_counts` |
| `expected.json`：`{cell, orig, rule, p_after}`；**禁出现 `observed_*` / `actual_*`** | ✅ | `test_golden_expected_has_no_observed_fields` |
| 真值**不可与引擎同源**：`fixtures.py` 不 import 阶段实现 / pandas，`p_after` 由输入独立推导 | ✅ | AST 守门 `test_generator_does_not_import_stage_implementations` |
| `uncovered_rules` 点名"本 seed 无正例"的规则（**8 条**，不假装覆盖） | ✅ | `test_golden_expected_covers_every_rules_json_entry`（覆盖 ∪ 点名 == 18）+ `test_uncovered_rules_are_documented` |
| `fixtures/golden/` + `manifest.json`（生成器版本 + 参数 + 文件 sha256） | ✅ | `test_golden_manifest_sha256_matches` |
| **同 seed 逐字节一致（两层）**：① 冻结产物形态；② 重跑生成器 → `cmp` | ✅ | `test_same_seed_byte_identical` / `test_golden_matches_generator` |
| `control-lossless` 组 **0 差异**（precision 硬约束，D4） | ✅ | `test_control_lossless_zero_false_positive`（四条通道各一条，真机） |
| **门禁三数**：四条通道 recall 1.00 / precision 1.00 / unclassified 0 | ✅ | `test_gate_passes_on_real_channel`（参数化四条；Excel COM 不可用则显式 skip 并标注） |
| `compute_gate` 语义：`missing` / `unexpected` / `wrong_rule` 分开列；空跑标 `vacuous` | ✅ | `tests/test_gate.py` 八条单元 |
| 首屏三数（`GATE: recall 1.00 precision 1.00 unclassified 0`） | ✅ | `test_gate_line_is_frozen` / `test_gate_three_numbers_printed_on_first_screen` |
| **三数任一不满足 → exit 2** | ✅ | `test_gate_failure_exits_2` |
| `gate` 判定通道四条退出码 0/1/2/3 | ✅ | `test_cli_gate_exits_1_when_lossy_but_gate_passes` / `..._2_...` / `..._3_on_missing_truth_file` / `..._3_without_key` |
| `gen-fixture` CLI 接线；**部分运行不写 manifest** | ✅ | `test_cli_gen_fixture_writes_golden_shape` / `test_partial_run_writes_only_orig` / `test_partial_run_does_not_touch_existing_manifest` |
| `docs/fixture-pools.md`（三组样本池构造纪律 + 合法形态判据 + `uncovered_rules` 理由） | ✅ | `git ls-files docs/fixture-pools.md` |
| 全套测试 | ✅ | `py -3.12 -X utf8 -m pytest -q` → **177 passed**（M0 17 + M1 36 + M2 30 + M3 34 + M4 60） |
| 布局门 / 脱敏门 / 变异验证 | ✅ | 布局门全绿；脱敏门 0 命中（扫 74 份）；17 组变异 **14 红 / 3 SKIP / 0 未按预期** |
| sdist 自足 | ✅ | `python -m build --sdist` → 解包 → 两门全绿 + **177 passed**（`fixtures/golden/` 与 `docs/fixture-pools.md` 随包） |

**门禁在四条真实通道上的实测输出**（金样本 seed 42 / 200 行）：

| 通道 | expected | reported | matched | recall | precision | unclassified |
|---|---|---|---|---|---|---|
| `pandas_csv` | 65 | 65 | 65 | 1.00 | 1.00 | 0 |
| `json_sqlite_csv` | 45 | 45 | 45 | 1.00 | 1.00 | 0 |
| `openpyxl_csv` | 5 | 5 | 5 | 1.00 | 1.00 | 0 |
| `excel_com_csv` | 112 | 112 | 112 | 1.00 | 1.00 | 0 |

`openpyxl_csv` 的 expected 少，是**因为它真的少做**（xlsx 往返在 2^53 以内精确）——
不是被硬编码跳过。**别为了让四条通道"看起来一样"去给 openpyxl 编期望。**

**`uncovered_rules` 点名的 8 条**（`expected.json` 机器可读，理由见 `docs/fixture-pools.md` §六）：
`float_precision_truncated` / `null_token_collision` / `unicode_normalization_changed` /
`whitespace_collapsed` / `bom_prepended` / `encoding_mojibake` / `date_system_shift_1904` /
`number_format_dropped`。

**未发生的事（不许写成已完成）**：
- **`run` / `diff` / `attribute` 仍不返回 0/1**（D18）。判定通道只有两处出口：
  `gate`（0/1/2）与 `attribute --fail-on unclassified`（局部 → 2）。
  `test_exit_codes.py::test_run_does_not_claim_lossless_in_m1` **仍必须绿**——它挡的是
  "给 run 加个 `return LOSSLESS` 蒙过去"。M5 接线报告时要**显式改写**它，不许放宽断言。
- **没有跑过一次 CI**（无远端）。本地等价校验全绿 ≠ CI 绿。
- **M5–M6 未开工。**
- **首屏三段（`VERDICT:` / `FIRST LOSS AT:` / `GATE:`）尚未合到一个出口**：M4 只有 `gate`
  子命令打印 `GATE:` 一行；`VERDICT: LOSSY (n/N cells, k rules)` 与 `FIRST LOSS AT:` 在 M5 的报告里。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

1. **状态副本共 4 处**：`plan/00` 里程碑表、`plan/05` 状态表、`README.md` 状态表、
   `plan/00` 承诺-证据台账。翻任一里程碑必须在**同一提交**里改全 4 处。
2. **`plan/05` §三 出口门表首列刻意是 `E0`…`E6`**，不是里程碑号。改成 `| M5 |` → 假红。
3. **`plan/06` 缺口表**：「缺口号」「说明」两列的单元格里不许写已 ✅ 的里程碑号。关闭缺口只描述、不点名文件。
4. **版本号唯一来源 = `src/tripwire/__init__.py::__version__`**，`pyproject.toml` 用 `dynamic`。
5. **退出码单点 = `src/tripwire/exitcodes.py`**；口径 = `data/README.md` §6.3。
6. **写盘唯一入口 = `tripwire/serialization.py`**；`orig.csv` 走 `write_text_raw`（逐字节），
   `expected.json` / `manifest.json` 走 `write_json`（K11）。
7. **`csvio.read_text` 必须走 `open(..., newline="")`**：`Path.read_text(newline=)` 是 **3.13** 才有的参数。
8. **`pipeline/stages/*` 里依赖一律函数内导入**；`diff/*` 与 `rules/*` **完全不 import pandas**。
   **`fixtures.py` 也不 import pandas、不 import 任何阶段实现**（真值必须与引擎同源之外的独立侧）。
9. **Excel COM 收尾顺序是硬约束**（见 `excel_com_csv._close_excel()`），不要内联重写。
10. **`stages.json` / `attribute --json` / `expected.json` / `manifest.json` 都不含时间戳**（G9）。
11. **`stage_index` 是 1-based 输出序号**；`first_seen_at` 与它同一套编号。
12. **`rules.json` 已冻结 18 条**（id 1–18，四族 8/2/4/4）。M5 不得增删规则、不得改 `id`/`name`/`possible_stages`。
13. **`excel_com_csv` 与 `openpyxl_csv` 是两个 stage 名**，不得混称 Excel。
14. **`_not_implemented()` 只剩 `report` 一个分支**；`diff` / `attribute` / `gen-fixture` / `gate` 都已接线。
15. **`run` / `diff` / `attribute` 的 exit 3 都是刻意的**（`NO_VERDICT_NOTE` / `NO_GATE_NOTE` /
    `NO_GATE_NOTE_ATTRIBUTE`）。M5 接线判定通道时，`test_exit_codes.py::test_run_does_not_claim_lossless_in_m1`
    必须**显式改写**，不许放宽断言蒙过去。
16. **`attribute(diffs, run, key=..., strategy=...)` 的 `key` / `strategy` 必须与产出这批差异时同一套**。
17. **`Attribution.first_seen_stage` 与 `resolved_stage` 是两个字段**。日志括号写前者、`resolved to` 写后者。
18. **`Attribution.fingerprint` 是 property，不是字段**（K10）。
19. **`_first_seen()` 从序列第 1 项起比**：`stage-0` 是输入副本，是基线而不是"变了的那一步"。
20. **`float_precision_truncated` 必须要求原文带小数点**（否则纯整数会按 id 抢在 `excel_15_digit_truncation` 前）。
21. **`date_retyped_to_text` 必须排除"目标日期不存在"**（1900-02-29 → 1900/2/29 归 id 17）。
22. **数值比较一律经 `predicates.as_decimal()`（stdlib `Decimal`）**。
23. **`number_format_dropped` 拿不到 `stage_meta` 键就返回 `False`**（首期四条通道恒不命中）。
24. **`NULL_TOKENS` 只收跨引擎都算缺失的那 9 个**。
25. **`runner.load_run()` 只读产物**；形状不对/缺快照一律抛 `RunNotFound`。

### M4 新增的不变量（下一棒最容易踩到的）

26. **样本形态的合法判据 = "在四条通道上真的变了的集合 ⊆ 该规则的 `possible_stages`"**（D16）。
    越界会落 `unclassified`，门禁必失败。**M5 若要加样本，先跑 `.tmp/` 里的探针核一遍**
    （或看 `docs/fixture-pools.md` §五）。**不许为了让门禁变绿去改 `possible_stages` 或放宽谓词。**
27. **夹具表必须稠密**（D17）。列里一个空格就把整列推成 `float64`，控制组的 `94016` → `94016.0`（假差异）。
    `zip` 列的填充值必须是整数形（否则 `02114` 的前导零不被剥，规则 1 丢正例）。
28. **`gate` 是唯一产出 0/1 的地方**（D18）。`compute_gate(expected, attributions, stage_name=...)`：
    分母**只取 `p_after` 里有本阶段键的条目**（同一形态在不同阶段的期望不同）。
29. **`Gate.vacuous` = `reported == 0`**。空跑不许当"门禁通过且覆盖了样本"——M5 首屏要把它说清楚。
30. **`expected.json` 的 `p_after` 阶段键必须 ⊆ 四个真实 stage 名**（不得混称 Excel）。
31. **部分运行（`--pool`）不写 `expected.json` / `manifest.json`**，也**不改写**已存在的（`plan/04` §五.5）。
    `fixtures/out/` 已 gitignore；金样本固定在 `fixtures/golden/`。
32. **`fixtures.py::round_significant` 与 `predicates.py::round_significant` 是两份独立实现**，
    看起来一样但**不许"顺手统一"**——统一后真值与被测实现同源，规则 5 算错与真值算错会一起错、一起绿。
33. **`KNOWN_UNCOVERABLE` 是"为什么点不出来"的登记处**（`fixtures.py` 内常量）。改 `uncovered_rules`
    必须同步改它 + `docs/rules.md` §六 + `docs/fixture-pools.md` §六（`test_uncovered_rules_are_documented` 会查）。
34. **`tests/test_skeleton.py::test_unimplemented_commands_exit_3` 已移出 `gen-fixture`**：
    它一跑就往 `fixtures/out/` 落文件，测试带副作用。新增 CLI 测试一律用 `tmp_path`。

---

## 三、下一棒待办（M5）

- [ ] `src/tripwire/report/model.py`：`build_run_result(...) -> RunResult`（持有内存结果对象）
- [ ] `src/tripwire/report/render_md.py` / `render_json.py` / `render_sarif.py`：**只读 `RunResult`**，不各自重算
- [ ] **首屏三段（顺序与字面固定）**：
      `VERDICT: LOSSY (37/1200 cells, 5 rules)` / `FIRST LOSS AT: stage 2 = excel_com_csv (Excel 16.0 Build 20326)` /
      `GATE: recall 1.00 precision 1.00 unclassified 0`
- [ ] `report` 子命令接线（`--format md,json,sarif`）；产物落 `runs/<run_id>/report.{md,json,sarif}`
- [ ] SARIF：`version 2.1.0`、`ruleId` = 规则名、`partialFingerprints.primaryLocationLineHash` = fingerprint、
      `artifactLocation.uri = "stage-<k>.csv"`、**不写绝对路径**
- [ ] **退出码 0/1/2/3 各一条**（`tests/test_exit_codes.py`，走真实 CLI 入口）；
      **显式改写 `test_run_does_not_claim_lossless_in_m1`** 并删 `NO_VERDICT_NOTE`
- [ ] 零网络 AST 守门（`src/tripwire/**` 不 import `requests/urllib.request/http.client/socket`）
- [ ] 渲染**不读时钟**（两次渲染逐字节一致 + AST 扫描）
- [ ] `tests/test_report.py`（出口门 E5）
- [ ] 收尾：改 4 处状态副本 → 关 `plan/06` 的 G-5 → 写 `plan/HANDOFF-M5.md` → commit

> **M5 可直接复用的东西**：`gate.compute_gate()` 已给出 `Gate`（含 `line()` 与 `missing/unexpected/wrong_rule`）；
> `rules.engine.attribute()` 给出带 `rule`/`resolved_stage`/`fingerprint` 的归因；
> `runner.load_run()` 可从 `--run-id` 重建；`fixtures/golden/expected.json` 是首屏 `GATE:` 行的真值来源。

> **M5 的两个已知坑**：
> ① **首屏第三段的 `GATE:` 行必须来自 `Gate`**，别在三处渲染器里各拼一份格式串——那正是 K9
>    "三格式同源"要防的。判别 = "换一个格式，这一行会变吗？"
> ② **`FIRST LOSS AT` 的阶段名必须是真实 stage 名**（`openpyxl_csv` 不得写成 `excel_csv`）；
>    运行时指纹在该阶段 `runtime` 为空时写 `unknown`，**不省略整行**。

---

## 四、既定口径清单（K 编号，动了会打挂测试）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| K1 | 快照存原始文本，不存 DataFrame；落盘走 `write_text_raw` | `test_snapshot_is_raw_text_not_reserialized` 红 |
| K2 | `run_id` 由内容派生，不用时间戳 | `test_run_id_*` 红 |
| K3 | `excel_com_csv` ≠ `openpyxl_csv`，不混称、不回落 | `test_excel_stage_does_not_fall_back_to_openpyxl` 红 |
| K4 | 无 `--key` 且 `--align key` → exit 3 | `test_no_key_refuses_to_run` / `test_cli_gate_exits_3_without_key` 红 |
| K5 | 差异排序 `(row_key, col_index)` 稳定 | `test_diff_order_stable` 红 |
| K6 | 规则谓词纯函数；一差多命中按 `id` 升序取首条 | `test_also_matched_recorded` / `test_every_predicate_is_pure_function` 红 |
| K7 | `unclassified` 单独计数、可 `--fail-on` | `test_cli_attribute_fail_on_unclassified_exits_2` 红 |
| K8 | 生成器不读时钟/全局 random（自研 splitmix64） | `test_splitmix64_known_sequence` / `test_golden_matches_generator` 红 |
| K9 | 报告渲染不读时钟/随机；三格式同源 | M5 `test_three_formats_same_findings` 红 |
| K10 | `fingerprint = sha256(row_key \x1f col \x1f rule)[:16]` | `test_fingerprint_matches_documented_formula` 红 |
| K11 | 一切 JSON 落盘走 `serialization.write_json` | 产物字节漂移 |

### M4 新增的口径（D 编号）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| D16 | 样本形态合法 ⟺ "变了的通道集合 ⊆ 该规则的 `possible_stages`" | 越界通道落 unclassified → 门禁失败 |
| D17 | 夹具表稠密；`zip` 列填充必须整数形 | 控制组假差异 → precision 失守 |
| D18 | `gate` 是唯一产出 0/1 的地方 | `run`/`diff`/`attribute` 报 0/1 = 把"没验过"写成"验过了" |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

- `py -0p` → **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符。**一律 `py -3.12 -X utf8`**。
- 本机 3.12 通道：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2 / pywin32 312；Excel **16.0 Build 20326**（COM 可用）。
- **`Path.read_text(newline=)` 在 3.10–3.12 不存在**（3.13 才有）。一律 `open(..., newline="")` 或 `csvio.read_text()`。
- **Excel COM segfault**：先 `CoUninitialize` 再析构代理 → exit 139。已封进 `_close_excel()`。
- **Excel COM 写 CRLF**；其余三通道写 LF。这是真实差异，**不许归一**。
- `python -m tripwire` 需要 `src/` 在 `sys.path`：未 `pip install -e .` 时用 `PYTHONPATH=src`。
- 临时落点用仓库内 `.tmp/`（已 gitignore）。Git Bash 的 `/tmp` 与 Windows Python 不通。
- **整库 `pytest` 会跑 4 次 Excel COM（约 8–10 分钟）**：想在 600s 内跑完就分文件跑，
  或用 `run_in_background`。
- **`csv.writer(writerow(嵌套 list))` 会把列表当单元格文本**（M4 探针踩过）：
  写表头 + 行时逐行 `writerow([r[c] for c in COLUMNS])`，别把 `rows` 整体再包一层。
- **`Decimal` 坑**：`round_significant()` 用 `Decimal.quantize` 而不是 `float` 格式化。
- **`_INT_RE` 与 `_DEC_RE`**：`_DEC_RE` 也匹配纯整数，所以"必须是小数"这类判断要**另外显式要求有小数点**（不变量 20）。
- **Excel General 渲染取决于原文字面量是否有指数符号**（M4 实测，`fixtures.py::_excel_general`）：
  纯数字字串整数部分 ≤11 位不变、≥12 位走 `%.6g`；指数形式一律 `%.2E`。
  **别用"数值大小"一条判据**——`3500000000000000000000` → `3.5E+21`，
  但 `3.5e+21` → `3.50E+21`，数值相同字面量不同、输出不同。
- **SQLite `CAST AS TEXT` 走 `%!.15g`（alternate form）**：`1e-07` → `1.0e-07`（**强制补小数点**）。
  这让 `exponent_form_normalized` 的候选不含 sqlite 的取值必须**避开一位有效数字**（`1e+21` 越界，`3.5e+21` 合法）。

---

## 六、DoD 逐项 checklist（M4）

- [x] `gen-fixture` 三组样本池（60 / 80 / 60）+ `expected.json` + `manifest.json`
- [x] 自研 splitmix64；不读时钟 / 不用全局 random / 不依赖 set 迭代序
- [x] `expected.json` 只存输入与期望；无 `observed_*` / `actual_*`
- [x] 真值由输入独立推导（AST 守门：不 import 阶段实现 / pandas）
- [x] 同 seed 逐字节一致（**两层**：冻结产物形态 + 重跑生成器 `cmp`）
- [x] `control-lossless` 组零误报（四条通道）
- [x] 门禁三数在四条通道上全绿（recall 1.00 / precision 1.00 / unclassified 0）
- [x] 三数任一不满足 → exit 2；判定通道 0/1/2/3 各一条
- [x] 三数打印（`Gate.line()` 字面写死；首屏三段完整版在 M5）
- [x] `uncovered_rules` 点名 8 条 + 每条有登记理由（`KNOWN_UNCOVERABLE` / `docs/rules.md` / `docs/fixture-pools.md`）
- [x] `docs/fixture-pools.md` 落盘
- [x] 部分运行不写全集清单（两条测试）
- [x] `tests/test_fixture.py` 34 passed + `tests/test_gate.py` 26 passed
- [x] 全套 `pytest -q` → 177 passed
- [x] 布局门全绿 / 脱敏门 0 命中 / 17 组变异符合预期
- [x] sdist 解包后自足（两门 + 177 passed）
- [x] 4 处状态副本一致（M0–M4 ✅ / M5–M6 ⬜）
- [x] `plan/06` 缺口 G-4 关闭；提交面表三条 M4 项翻 ✅（另补"门禁三数"一条）
- [ ] CI 首跑 —— **不适用本轮**（无远端）。写"CI 待首推验证"，不写"CI 绿"

---

## 七、关键命令速查

```bash
# 门（第一动作）
py -3.12 tools/check_sprint_layout.py
py -3.12 tools/check_desensitized.py
py -3.12 tools/verify_gate_mutations.py

# 测试（M4 出口门 E4 = 第一条）
py -3.12 -m pytest -q tests/test_fixture.py tests/test_gate.py
py -3.12 -m pytest -q

# 夹具
PYTHONPATH=src py -3.12 -X utf8 -m tripwire gen-fixture --seed 42 --rows 200 --out-dir fixtures/golden
PYTHONPATH=src py -3.12 -X utf8 -m tripwire gen-fixture --seed 42 --rows 60 --out-dir .tmp/partial --pool numeric

# 全链路：跑管线 → 判门禁（四条通道各一遍）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/excel_com.json --input fixtures/golden/orig.csv --key id
PYTHONPATH=src py -3.12 -X utf8 -m tripwire gate --run-id <run_id> --expected fixtures/golden/expected.json --key id
PYTHONPATH=src py -3.12 -X utf8 -m tripwire attribute --run-id <run_id> --key id --explain

# 规则表 / 通道可用性
PYTHONPATH=src py -3.12 -X utf8 -m tripwire rules --count      # 18
PYTHONPATH=src py -3.12 -X utf8 -m tripwire selftest

# sdist 自足复核
python -m build --sdist --outdir .tmp/sdist
tar -xzf .tmp/sdist/*.tar.gz -C .tmp/unpack && cd .tmp/unpack/tripwire-* && python -m pytest -q
```

> 本机（Windows）把 `python` 换成 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。
> **整库 pytest 含 4 次 Excel COM，约 8–10 分钟**——别用默认 120s 超时。