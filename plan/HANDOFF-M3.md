# HANDOFF-M3 → M4（18 条归因规则 + 快照序列筛环节）

> **续接方式**（用户侧）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `py -3.12 tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = M3（归因规则引擎），已完成；下一棒 = **M4（真值夹具生成器 + 门禁三数）**。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| 18 条谓词全部实现、全部纯函数 | ✅ | `tests/test_rules.py` → 34 passed；`test_every_predicate_is_pure_function`（AST 扫时钟/随机/网络） |
| 谓词签名统一 `(orig, got, declared_type, stage_meta)` | ✅ | `test_predicate_signature_is_the_documented_one` |
| `rules.json` 的 13 条可机读反例**真的不命中** | ✅ | `test_every_rule_counterexample_holds` + 边界两条（#4 的 2^53−1、#17 的 serial 59） |
| 原型 **9/9 命中、`unclassified == 0`** | ✅ 本机真机 | `test_nine_of_nine_classified`（真跑 `excel_com_csv`，非冻结字符串） |
| 每条归因有证据 + 环节是真跑过的阶段名 | ✅ | `test_every_attribution_has_evidence` |
| `first_seen_at` 用 1-based 输出序号 | ✅ | `test_first_seen_at_is_one_based_output_index` |
| `--explain` 日志格式写死 | ✅ | `test_explain_log_format_is_frozen` |
| **同规则不同环节 → `resolved_stage` 不同** | ✅ | `test_first_seen_stage_from_snapshot_sequence`（pandas_csv vs json_sqlite_csv） |
| 候选不在本次 run → 降级 `unclassified`（D1） | ✅ | `test_candidate_stage_not_in_run_degrades_to_unclassified`（openpyxl 的 16 位科学计数法不得归因 Excel 15 位） |
| 候选在本次 run 但非首个观察到者 → 按运行顺序回退 | ✅ | `test_candidate_not_first_observed_falls_back_in_run_order` |
| 无快照序列 → 不编造环节 | ✅ | `test_no_stage_sequence_does_not_invent_stage` |
| 一差多命中按 `id` 升序取首条，其余进 `also_matched`（K6） | ✅ | `test_also_matched_recorded` / `test_first_hit_is_lowest_id_not_alphabetical` |
| `unclassified` 单独计数、不丢（K7） | ✅ | `test_unclassified_is_counted_not_silently_dropped` |
| `--fail-on unclassified` → exit 2；**无 unclassified 时不触发** | ✅ | 成对两条：`test_cli_attribute_fail_on_unclassified_exits_2` / `..._is_silent_when_all_classified` |
| `fingerprint` = `sha256(row_key \x1f col \x1f rule)[:16]`（K10） | ✅ | `test_fingerprint_matches_documented_formula`（逐字对 `data/README` §6.4） |
| fingerprint 跨 run 稳定 / 改规则即变 | ✅ | `test_fingerprint_is_stable_across_runs` / `test_fingerprint_changes_when_rule_changes` |
| CLI `attribute` 接线（`--explain` / `--fail-on` / `--json` / `--stage-index`） | ✅ | `test_cli_attribute_*` 五条 |
| `runner.load_run()` 只读产物重建，不重跑 | ✅ | `test_load_run_rebuilds_without_rerunning`（比对前后字节） |
| 缺快照 / 缺 `stages.json` / 形状不对 → `RunNotFound` | ✅ | 三条 `test_load_run_rejects_*` |
| `docs/rules.md` | ✅ | `git ls-files docs/rules.md` |
| 全套测试 | ✅ | `py -3.12 -X utf8 -m pytest -q` → **117 passed**（M0 17 + M1 36 + M2 30 + M3 34） |
| 布局门 / 脱敏门 | ✅ | 布局门全绿；脱敏门 0 命中（扫 65 份） |
| sdist 自足 | ✅ | `python -m build --sdist` → 解包 → 两门 + `pytest` 全绿（`docs/rules.md` 随包） |

**真实四条通道上的 `unclassified` 分布（如实登记，不掩饰）**：

| 通道 | 差异数 | unclassified | 说明 |
|---|---|---|---|
| `excel_com_csv` | 9 | **0** | 9/9 全部命中并解析到 `excel_com_csv`（M3 的验收基线） |
| `json_sqlite_csv` | 6 | 2 | `1e-7`→`1.0e-07`（尾随零 + 指数双改动）、`1E5`→`100000`（变定点整数，不在任何规则的形态里） |
| `pandas_csv` | 5 | 2 | `1e-7`→`1e-07`、`1E5`→`100000.0` |
| `openpyxl_csv` | 4 | 3 | 那条 20 位整数 → `1.234567890123457e+19`（有效位 16，**不是** Excel 的 15 位行为 → 正确落 unclassified） |

**这些 unclassified 是本轮最有价值的输出**：它们精确指出了现有 18 条规则覆盖不到的三类形态
（指数尾随零、定点化、非 15 位截断）。M4 的门禁会拿 `control-lossless` 组卡 precision，
**不要为了压掉它们去放宽规则**（D4：误报比 unclassified 更糟）。

**未发生的事（不许写成已完成）**：
- **`attribute` 不返回 0/1**（门禁三数在 M4）。唯一的判定通道出口是 `--fail-on unclassified` → 2。
- **没有跑过一次 CI**（无远端）。
- **规则 18 `number_format_dropped` 在首期真实管线上恒为 `False`**：四条 CSV 通道都不产出
  单元格级 `number_format`，谓词拿不到证据就不归因（D1）。已写进 `docs/rules.md`，
  **不假装它覆盖了**。
- **规则 16 `date_system_shift_1904` 在原型样本里没有正例**：靠单测构造验证。
  `expected.json` 的 `uncovered_rules`（M4）会把这个事实变成可复算的结论。
- M4–M6 未开工。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

1. **状态副本共 4 处**：`plan/00` 里程碑表、`plan/05` 状态表、`README.md` 状态表、
   `plan/00` 承诺-证据台账。翻任一里程碑必须在**同一提交**里改全 4 处。
2. **`plan/05` §三 出口门表首列刻意是 `E0`…`E6`**，不是里程碑号。改成 `| M3 |` → 假红。
3. **`plan/06` 缺口表**：「缺口号」「说明」两列的单元格里不许写已 ✅ 的里程碑号。关闭缺口只描述、不点名文件。
4. **版本号唯一来源 = `src/tripwire/__init__.py::__version__`**，`pyproject.toml` 用 `dynamic`。
5. **退出码单点 = `src/tripwire/exitcodes.py`**；口径 = `data/README.md` §6.3。
6. **写盘唯一入口 = `tripwire/serialization.py`**；快照仍走 `write_text_raw`（K1）。
7. **`csvio.read_text` 必须走 `open(..., newline="")`**：`Path.read_text(newline=)` 是 **3.13** 才有的参数。
8. **`pipeline/stages/*` 里依赖一律函数内导入**；`diff/*` 与 `rules/*` **完全不 import pandas**。
   `predicates.py` 的日期解析用 stdlib `datetime`（只构造对象，不读当前时间）。
   别把 pandas 拉进归因层：那会让归因在没装 pandas 的机器上跑不了，而 `plan/02` §三只允许**阶段**因缺依赖失败。
9. **Excel COM 收尾顺序是硬约束**（见 `excel_com_csv._close_excel()`），不要内联重写。
10. **`stages.json` 与 `attribute --json` 产物都不含时间戳**（G9）。
11. **`stage_index` 是 1-based 输出序号**；`first_seen_at` 与它同一套编号。
12. **`rules.json` 已冻结 18 条**（id 1–18，四族 8/2/4/4）。M4/M5 不得增删规则、不得改 `id`/`name`/`possible_stages`。
13. **`excel_com_csv` 与 `openpyxl_csv` 是两个 stage 名**，不得混称 Excel。
14. **`_not_implemented()` 只剩 `gen-fixture` / `report` 两个分支**；`diff` 与 `attribute` 都已接线。
15. **`run` / `diff` / `attribute` 的 exit 3 都是刻意的**（`NO_VERDICT_NOTE` / `NO_GATE_NOTE` /
    `NO_GATE_NOTE_ATTRIBUTE`）。M5 接线判定通道时，`test_exit_codes.py::test_run_does_not_claim_lossless_in_m1`
    必须**显式改写**，不许放宽断言蒙过去。

### M3 新增的不变量（下一棒最容易踩到的）

16. **`attribute(diffs, run, key=..., strategy=...)` 的 `key` / `strategy` 必须与产出这批差异时同一套**。
    `row_key` 是定位行的唯一线索（主键值 / `#<index>` / 行指纹）；拿错策略会静默退回
    `first_seen_at = None`——那不是"没有序列"，是"找错了"。**别为了省参数在 engine 里猜策略。**
17. **`Attribution.first_seen_stage` 与 `resolved_stage` 是两个字段**。前者 = 实际首次观察到变化的阶段；
    后者 = 规则候选里选中的那个。日志括号写前者、`resolved to` 写后者。合成一个字段就说不清"到底哪一步"。
18. **`Attribution.fingerprint` 是 property，不是字段**。存成字段就有两份口径的风险；
    它必须永远是 `(row_key, col, rule)` 的纯函数（K10）。
19. **`_first_seen()` 从序列第 1 项起比**：`stage-0` 是输入副本，它是基线而不是"变了的那一步"。
20. **`float_precision_truncated` 必须要求原文带小数点**。若不要求，`12345678901234567890`（纯整数）
    会按 id 3 抢在 id 5 的 `excel_15_digit_truncation` 前面，而 id 3 的候选不含 `excel_com_csv`
    → 一次真实的 Excel 截断随后被降级成 unclassified。**测试 `test_nine_of_nine_classified` 会红。**
21. **`date_retyped_to_text` 必须排除"目标日期不存在"**（1900-02-29 → 1900/2/29）：
    id 15 会抢在 id 17 前面。幽灵日期归 `serial_60_phantom_date`（`parse_date()` 对 2 月 29 日返回 `None` 是刻意的）。
22. **数值比较一律经 `predicates.as_decimal()`（stdlib `Decimal`）**。用 `float` 会把"丢了位"读成
    "相等"（`float('12345678901234567890') == float('1.23457E+19')` 是 True），谓词 4/5 就永远不命中。
23. **`number_format_dropped` 拿不到 `stage_meta` 键就返回 `False`**。首期四条通道恒不命中；
    二期接入 xlsx 读回时把格式塞进 `stage_meta` 即可生效，**不需要改谓词**。
24. **`NULL_TOKENS` 只收跨引擎都算缺失的那 9 个**，不用 pandas 的 19 项完整列表：
    "是不是 null token"不该取决于某个引擎的实现细节。
25. **`runner.load_run()` 只读产物**（M3 新增）：`attribute --run-id` 靠它重建状态。
    形状不对/缺快照一律抛 `RunNotFound`（与写入侧的 `RunIdCollision` 分开）。

---

## 三、下一棒待办（M4）

- [ ] `src/tripwire/fixtures.py`：`generate(seed, rows, out_dir) -> FixtureResult`，写 `orig.csv` + `expected.json`
- [ ] **自研 splitmix64**（K8）：不读时钟、不用全局 `random`、不依赖 `set` 迭代序
- [ ] 三组样本池：`canary-numeric` 60 / `canary-semantic` 80 / `control-lossless` 60（seed 42 / rows 200）
- [ ] `expected.json`：`{cell, orig, rule, p_after}`；**禁出现 `observed_*` / `actual_*`**（出现即测试红）
- [ ] `uncovered_rules` 列表：某 seed 下没有正例的规则**点名**，不假装覆盖（`docs/rules.md` 第三行据此回填）
- [ ] `fixtures/golden/`（seed 42 / rows 200）+ `manifest.json`（生成器版本 + 参数 + 文件 sha256）
- [ ] `src/tripwire/gate.py`：`compute_gate(expected, attributions) -> Gate`（**只实现不复述** `data/README` §6.2）
- [ ] `control-lossless` 组 **0 差异**（precision 硬约束，D4）
- [ ] `gen-fixture` CLI 接线；**部分运行（如 `--pool numeric`）不写 `manifest.json`**（`plan/04` §五.5）
- [ ] `docs/fixture-pools.md`（三组样本池构造纪律）
- [ ] `tests/test_fixture.py` + `tests/test_gate.py`（出口门 E4）：同 seed 逐字节一致（**两层**）、
      control 零误报、三数打印首屏、三数任一不满足 → exit 2、golden 与重生成逐字节一致
- [ ] 收尾：改 4 处状态副本 → 关 `plan/06` 的 G-4 → 写 `plan/HANDOFF-M4.md` → commit

> **M4 可直接复用的东西**：`rules.engine.attribute()` 已给出带 `rule` / `resolved_stage` /
> `fingerprint` 的归因列表，门禁只需要拿 `expected.json` 与它对照；`runner.load_run()` 可从
> `--run-id` 重建状态；`common.cell_kind()` 判数字形。

> **M4 的 precision 风险点已经知道在哪**：把 `git log` 里 M3 那轮的 unclassified 分布
> （指数尾随零 / 定点化 / 非 15 位截断）拿来做 `control-lossless` 的设计输入——
> 控制组必须避开这些形态，否则一开跑就 precision 失败。**但不要为了让门禁变绿去改谓词**（D4）。

---

## 四、既定口径清单（K 编号，动了会打挂测试）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| K1 | 快照存原始文本，不存 DataFrame；落盘走 `write_text_raw` | `test_snapshot_is_raw_text_not_reserialized` 红 |
| K2 | `run_id` 由内容派生，不用时间戳 | `test_run_id_*` 红 |
| K3 | `excel_com_csv` ≠ `openpyxl_csv`，不混称、不回落 | `test_excel_stage_does_not_fall_back_to_openpyxl` 红 |
| K4 | 无 `--key` 且 `--align key` → exit 3 | `test_no_key_refuses_to_run` / `test_cli_attribute_requires_key_for_key_alignment` 红 |
| K5 | 差异排序 `(row_key, col_index)` 稳定 | `test_diff_order_stable` 红 |
| K6 | 规则谓词纯函数；一差多命中按 `id` 升序取首条 | `test_also_matched_recorded` / `test_every_predicate_is_pure_function` 红 |
| K7 | `unclassified` 单独计数、可 `--fail-on` | `test_cli_attribute_fail_on_unclassified_exits_2` 红 |
| K8 | 生成器不读时钟/全局 random（自研 splitmix64） | M4 同 seed 逐字节测试红 |
| K9 | 报告渲染不读时钟/随机；三格式同源 | M5 `test_three_formats_same_findings` 红 |
| K10 | `fingerprint = sha256(row_key \x1f col \x1f rule)[:16]` | `test_fingerprint_matches_documented_formula` 红 |
| K11 | 一切 JSON 落盘走 `serialization.write_json` | 产物字节漂移 |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

- `py -0p` → **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符。**一律 `py -3.12 -X utf8`**。
- 本机 3.12 通道：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2 / pywin32 312；Excel **16.0 Build 20326**（COM 可用）。
- **`Path.read_text(newline=)` 在 3.10–3.12 不存在**（3.13 才有）。一律 `open(..., newline="")` 或 `csvio.read_text()`。
- **Excel COM segfault**：先 `CoUninitialize` 再析构代理 → exit 139。已封进 `_close_excel()`。
- **Excel COM 写 CRLF**；其余三通道写 LF。这是真实差异，**不许归一**。
- `python -m tripwire` 需要 `src/` 在 `sys.path`：未 `pip install -e .` 时用 `PYTHONPATH=src`。
- 临时落点用仓库内 `.tmp/`（已 gitignore）。Git Bash 的 `/tmp` 与 Windows Python 不通。
- **`csv.reader` 的 `newline=""` 是必需的**；`csvio.parse_csv_text` 已写对。
- **本轮实测到的 `Decimal` 坑**：`round_significant()` 用 `Decimal.quantize` 而不是 `float` 格式化——
  `format(v, '.15g')` 会走二进制浮点，20 位整数在那里已经被毁了，等于拿一个失真过的数去比另一个失真过的数。
- **`_INT_RE` 与 `_DEC_RE` 的区别要记住**：`_DEC_RE` 也匹配纯整数（`\d+` 是 `\d+(\.\d*)?` 的子集），
  所以"必须是小数"这类判断要**另外显式要求有小数点**（不变量 20）。

---

## 六、DoD 逐项 checklist（M3）

- [x] 18 条谓词全部实现、签名统一、全部纯函数（AST 守门）
- [x] `T1` 归因流程：`id` 升序取首条 + `also_matched` 不丢
- [x] 快照序列筛候选：`first_seen_at` + `resolved_stage`；候选无交集 → `unclassified`
- [x] `unclassified` 单独计数 + `--fail-on unclassified` → exit 2
- [x] `--explain` 日志格式写死并通过测试
- [x] 原型 9/9 命中、`unclassified == 0`（真机 Excel 管线）
- [x] "同规则不同环节" `resolved_stage` 不同
- [x] `openpyxl_csv` 的形似差异不归因到 `excel_15_digit_truncation`（D1）
- [x] `fingerprint` 公式逐字对齐 `data/README` §6.4；跨 run 稳定
- [x] `docs/rules.md` 落盘（18 条 + 反例 + 覆盖情况如实登记）
- [x] `tests/test_rules.py` 34 passed
- [x] 全套 `pytest -q` → 117 passed
- [x] 布局门全绿 / 脱敏门 0 命中
- [x] sdist 解包后自足（两门 + 全绿）
- [x] 4 处状态副本一致（M0–M3 ✅ / M4–M6 ⬜）
- [x] `plan/06` 缺口 G-3 关闭；提交面表两条 M3 项翻 ✅
- [ ] CI 首跑 —— **不适用本轮**（无远端）。写"CI 待首推验证"，不写"CI 绿"

---

## 七、关键命令速查

```bash
# 门（第一动作）
py -3.12 tools/check_sprint_layout.py
py -3.12 tools/check_desensitized.py
py -3.12 tools/verify_gate_mutations.py

# 测试（M3 出口门 E3 = 第一条）
py -3.12 -m pytest -q tests/test_rules.py
py -3.12 -m pytest -q

# 全链路：跑管线 → 看差异 → 归因（四条通道各一遍）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/excel_com.json --input sample.csv --key id
PYTHONPATH=src py -3.12 -X utf8 -m tripwire attribute --run-id <run_id> --key id --explain
PYTHONPATH=src py -3.12 -X utf8 -m tripwire attribute --run-id <run_id> --key id --fail-on unclassified

# 只比两份快照（不给序列，resolved_stage 会是 null —— 这是刻意的）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire diff --orig a.csv --got b.csv --key id

# 规则表
PYTHONPATH=src py -3.12 -X utf8 -m tripwire rules --count      # 18
PYTHONPATH=src py -3.12 -X utf8 -m tripwire rules

# 通道可用性
PYTHONPATH=src py -3.12 -X utf8 -m tripwire selftest

# sdist 自足复核
python -m build --sdist --outdir .tmp/sdist
tar -xzf .tmp/sdist/*.tar.gz -C .tmp/unpack && cd .tmp/unpack/tripwire-* && python -m pytest -q
```

> 本机（Windows）把 `python` 换成 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。