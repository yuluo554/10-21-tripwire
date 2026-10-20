# HANDOFF-M2 → M3（单元格级差异引擎 + 对齐三策略）

> **续接方式**（用户侧）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `py -3.12 tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = M2（差异引擎），已完成；下一棒 = **M3（归因规则引擎，18 条谓词 + 快照序列筛选）**。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| 对齐三策略 `key` / `position` / `lcs` | ✅ | `tests/test_diff_engine.py` → 30 passed（本机含 Excel 真机那条） |
| 原型 14 单元格 / 9 条差异复现 | ✅ | `test_prototype_nine_diffs`：`cells_compared == 14`、`len(diffs) == 9` |
| 同一样本**真机** Excel 通道复现 9 差异 | ✅ 本机实跑 | `test_prototype_nine_diffs_on_real_excel`（Excel 16.0 Build 20326，未 skip） |
| 逐条钉住差异内容（不只数条数） | ✅ | `test_prototype_diffs_are_the_expected_cells`：9 组 `(row_key, col) → (orig, got)` 全等 |
| 四项结构差异各自独立成记录 | ✅ | `test_structure_changes_reported_separately`：`kinds == [row_count, col_count, col_order, header]` |
| 结构差异不折算进单元格差异 | ✅ | `test_structure_kinds_do_not_duplicate_into_cell_diffs`（整行消失 → 0 条单元格差异） |
| 无主键拒绝运行（K4 / G3） | ✅ | `test_no_key_refuses_to_run` + CLI 层 `test_cli_diff_without_key_refuses_and_writes_nothing`（不落 `--json`） |
| 主键重复拒绝运行 | ✅ | `test_duplicate_key_refuses_to_run` / `test_duplicate_key_on_got_side_also_refuses` |
| `--key` 列不存在 → 报列名 | ✅ | `test_missing_key_column_names_the_column` |
| `--batch N` 产 `dtype_drift` | ✅ | `test_batch_reports_dtype_drift`（`types == {int, text}`）；不给 batch 则无此记录 |
| 缺格 vs 空串可区分（M3 谓词 9 的证据面） | ✅ | `test_missing_cell_differs_from_empty_cell`：`orig_missing=True` / `got_missing=False` |
| 差异排序 `(row_key, col_index)` 稳定（K5） | ✅ | `test_diffs_sorted_by_row_key_then_col_index`、`test_diff_order_stable`（双跑 `--json` 逐字节一致） |
| 不依赖字典插入序 | ✅ | `test_diff_does_not_depend_on_dict_order` |
| `position` 的插行雪崩**可见** | ✅ | `test_position_alignment_reports_insertion_avalanche`（≥4 条 vs key 的 0 条） |
| `lcs` 锚点+空隙语义 | ✅ | `test_lcs_absorbs_insertion_without_cell_diffs` / `test_lcs_reports_modified_row_as_cell_diff` |
| CLI 接线 `diff` | ✅ | `test_cli_diff_prints_nine_and_refuses_verdict`（报 `diffs 9`，仍 exit 3） |
| `docs/diff-schema.md` | ✅ | `git ls-files docs/diff-schema.md` |
| 全套测试 | ✅ | `py -3.12 -X utf8 -m pytest -q` → **83 passed**（M0 17 + M1 36 + M2 30） |
| 布局门 / 脱敏门 | ✅ | 布局门 10 条全绿；脱敏门 0 命中（扫 62 份） |
| 门自身变异验证 | ✅ | `py -3.12 tools/verify_gate_mutations.py` → 17 组：红 14 / 允许 SKIP 3 / 未按预期 0 |
| sdist 自足 | ✅ | `python -m build --sdist` → 解包 → 两门全绿 + **83 passed**（`docs/diff-schema.md` 与 `src/tripwire/diff/` 均随包） |

**未发生的事（不许写成已完成）**：
- **`diff` 不返回 0/1**：`0`/`1` 的定义里都带"门禁通过"，而门禁在 M4。M2 一律 exit 3 并打印
  `NO_GATE_NOTE`。**算出了 9 条差异 ≠ 判为有损**。
- **没有跑过一次 CI**（无远端）。CI 结论只能写"本地等价校验"。
- **`lcs` 的上限是显式拒绝**：`LCS_MAX_CELLS = 25_000_000`（行对格数）。超过就抛
  `UnknownStrategy`（exit 3），**不降级成近似对齐**——近似会让"精确 LCS"这条承诺在数据量一大就悄悄失效。
  这个上限**没有在真实大数据上压测过**（首期只承诺 200 行合成样本）。
- M3–M6 未开工。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

1. **状态副本共 4 处**：`plan/00` 里程碑表、`plan/05` 状态表、`README.md` 状态表、
   `plan/00` 承诺-证据台账。翻任一里程碑必须在**同一提交**里改全 4 处，否则 `LAYOUT.STATUS` / `LAYOUT.LEDGER` 变红。
2. **`plan/05` §三 出口门表首列刻意是 `E0`…`E6`**，不是里程碑号。改成 `| M2 |` 会被布局门误采成第二份状态行 → 假红。
3. **`plan/06` 缺口表**：「目标里程碑」列不参与扫描，但**「缺口号」「说明」两列的单元格里不许写已 ✅ 的里程碑号**
   （文件名里的 `M6` 也会中招）。关闭缺口时只描述、不点名文件。
4. **版本号唯一来源 = `src/tripwire/__init__.py::__version__`**；`pyproject.toml` 用 `dynamic = ["version"]`。永不写第二份字面量。
5. **退出码单点 = `src/tripwire/exitcodes.py`**；口径 = `data/README.md` §6.3。
6. **写盘唯一入口 = `tripwire/serialization.py`**。M2 的 `--json` 走 `write_json`（K11）。
   **快照仍走 `write_text_raw`**，别改成 `write_text`（K1）。
7. **`csvio.read_text` 必须走 `open(..., newline="")`**：`Path.read_text(newline=)` 是 **3.13** 才有的参数，本包承诺 3.10+。
8. **`pipeline/stages/*` 里依赖一律函数内导入**（缺 pandas 的机器仍能 `import tripwire`）。
   **`diff/*` 则完全不 import pandas**——`--batch` 的推断用 `pipeline/stages/common.cell_kind`（纯 stdlib 正则）。
   别为了"更准"把 pandas 拉进差异层：那会让差异层在没有 pandas 的机器上跑不了，而"阶段缺依赖才失败"是 `plan/02` §三的约定。
9. **Excel COM 收尾顺序是硬约束**：关文档 → `app.Quit()` → 放代理 → `gc.collect()` → `CoUninitialize()`。
   已封进 `excel_com_csv._close_excel()`，**不要内联重写**。
10. **`stages.json` 不含任何时间戳 / 耗时**；`diff` 的 JSON 产物同样不含（G9）。
11. **`stage_index` 是 1-based 输出序号**：`stage-0` = 输入副本，`stage-1` = 第一份输出。
    M3 的 `--explain` 里 `first_seen_at=stage <k>` 必须与这套编号一致；`diff --stage-index k` 也用它。
12. **`rules.json` 已冻结 18 条**（id 1–18，四族 8/2/4/4）。M3 只新增谓词函数，不得增删规则、不得改 `id`/`name`/`possible_stages`。
13. **`excel_com_csv` 与 `openpyxl_csv` 是两个 stage 名**，`schema.py` 硬校验 stage_name↔engine 一一对应。
14. **`_not_implemented()` 只剩 `attribute` / `gen-fixture` / `report` 三个分支**；`diff` 已接线。
    M3 落地 `attribute` 时同样要**删掉**旧分支并补测试，而不是在旧分支上加判断。
15. **`run` 与 `diff` 的 exit 3 都是刻意的**（`NO_VERDICT_NOTE` / `NO_GATE_NOTE`）。M5 接线判定通道时，
    `tests/test_exit_codes.py::test_run_does_not_claim_lossless_in_m1` 必须**显式改写**，不许放宽断言蒙过去。

### M2 新增的不变量（下一棒最容易踩到的）

16. **`CsvTable` 多了一个 `text` 字段**（原文），`parse_csv_text` / `read_csv` 都会带上。
    用它做 `--batch` 或未来的分块读取；**不要**从 `rows` 重新序列化（那等于在比较前先归一一次）。
    默认值是 `None`，手工构造 `CsvTable(header=..., rows=...)` 仍然合法。
17. **`DiffRecord` 排序键的第二段是 `col_index` 而不是 `col`**。按列名排序会随 `col_order` 变化而漂移，
    两次运行就不再逐字节一致（K5）。
18. **整行消失/新增不产单元格差异**，只进 `row_count` 的 `missing_rows` / `extra_rows`。
    这是"同一问题不重复计数"的落法，改它会让 `test_structure_kinds_do_not_duplicate_into_cell_diffs` 红。
19. **`col_order` 只比两侧都有的列的相对顺序**。`c`→`d` 是 `header` 事实，同时报 `col_order` 是把一件事报两遍。
20. **`lcs` 的锚点之间按位置补配**。只靠精确指纹锚点的话，配上的行逐字节相同，`lcs` 永远报不出单元格差异
    （等于这条策略只报行增删）。补配不做任何内容比较，**不是相似度**。
21. **`--batch` 的 chunk 标签只有 `int` / `float` / `text`**，出现非数字文本就整块落回 `text`（贴 pandas 的 `object` 回退）。
    不做多数表决——多数表决会造出 pandas 不会产出的标签，那条结构记录就不再对应真实引擎行为。
22. **`align()` 返回纯位置对** `(orig_index|None, got_index|None)`，不返回 `row_key`。
    `row_key` 由 `engine._row_key()` 从对子 + 策略推出；M3 的 fingerprint 复用 `record.row_key`，不要自己再造一个。
23. **`row_fingerprint(row)` = `sha256("\x1f".join(row))[:16]`**，不含行号/表头/时间。
    `lcs` 下"只在往返后出现"的行加 `~` 前缀，以免看起来像一条原表行。
24. **`duplicate_key` 的检查在两侧都做**（原表侧与往返后侧）。只查一侧会漏掉"往返后多出重复行"这种真形态。
25. **`DiffRecord` 带 `orig_missing` / `got_missing`**：区分"缺格"（行短于表头）与"空串"。
    两者文本都是 `""`，没有这两个标记，M3 的 `empty_vs_null_vs_missing` 永远不命中。
    `plan/02` §二 的 IR 表已同步这一行。

---

## 三、下一棒待办（M3）

- [ ] `src/tripwire/rules/engine.py`：`attribute(diffs, run_stages) -> list[Attribution]`
- [ ] `predicates.py`：把 18 个 `_not_implemented` 换成真谓词，签名 `(orig, got, declared_type, stage_meta) -> bool`
- [ ] 一差多命中按 `id` 升序取首条，其余写 `evidence.also_matched`（K6，不静默丢弃）
- [ ] **快照序列筛候选**：从 `stage-0` 起逐阶段比较该单元格文本，找首次出现 `got_text` 的相邻阶段；
      阶段名 ∈ `candidates` → `resolved_stage`；无交集 → `rule` 降级 `unclassified`（宁可 unclassified，不伪造归因）
- [ ] `unclassified` 单独计数 + `--fail-on unclassified`（K7）
- [ ] `--explain` 日志格式写死：`rule=<name>, first_seen_at=stage 2 (excel_com_csv), candidates=[...] -> resolved to excel_com_csv`
- [ ] `docs/rules.md`：18 条人类可读表（含证据要求 + 反例）
- [ ] `tests/test_rules.py`（出口门 E3）：9/9 命中、`unclassified == 0`、每条归因有证据、
      "同规则不同环节"两例 `resolved_stage` 不同、`test_also_matched_recorded`
- [ ] 收尾：改 4 处状态副本 → 关 `plan/06` 的 G-3 → 写 `plan/HANDOFF-M3.md` → commit

> **M3 可直接复用的东西**：`diff_tables()` 已给出排好序的 `DiffRecord`（含 `row_key`/`col`/`orig_text`/`got_text`/`stage_index`）；
> `runner.run_pipeline()` 的 `RunStages.stages[k]` 有 `stage_name` 与 `out_dir`，快照文件是 `stage-<k>.csv`；
> `common.cell_kind()` 可直接用于谓词里的"是不是数字形"判断。

> **M3 的验收基线是 M2 的真机产物，不是冻结字符串**：`test_prototype_nine_diffs_on_real_excel`
> 已经证明 9 条差异能在本机从真 Excel 复现。M3 的 `test_nine_of_nine_classified` 应当跑同一条真机管线，
> 而不是拿 `PROTO_AFTER_EXCEL` 硬编码。

---

## 四、既定口径清单（K 编号，动了会打挂测试）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| K1 | 快照存原始文本，不存 DataFrame；落盘走 `write_text_raw` | `test_snapshot_is_raw_text_not_reserialized` 红 |
| K2 | `run_id` 由内容派生，不用时间戳 | `test_run_id_*` / `test_same_input_same_run_id` 红 |
| K3 | `excel_com_csv` ≠ `openpyxl_csv`，不混称、不回落 | `test_validate_pipeline_rejects_engine_stage_mismatch` / `test_excel_stage_does_not_fall_back_to_openpyxl` 红 |
| K4 | 无 `--key` 且 `--align key` → exit 3 | `test_no_key_refuses_to_run` / `test_cli_diff_without_key_refuses_and_writes_nothing` 红 |
| K5 | 差异排序 `(row_key, col_index)` 稳定 | `test_diffs_sorted_by_row_key_then_col_index` / `test_diff_order_stable` 红 |
| K6 | 规则谓词纯函数；一差多命中按 `id` 升序取首条 | M3 `test_also_matched_recorded` 红 |
| K7 | `unclassified` 单独计数、可 `--fail-on` | M3/M4 门禁失去意义 |
| K8 | 生成器不读时钟/全局 random（自研 splitmix64） | M4 同 seed 逐字节测试红 |
| K9 | 报告渲染不读时钟/随机；三格式同源 | M5 `test_three_formats_same_findings` 红 |
| K10 | `fingerprint = sha256(row_key \x1f col \x1f rule)[:16]` | M5 跨 run diff 失效 |
| K11 | 一切 JSON 落盘走 `serialization.write_json` | 产物字节漂移 |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

- `py -0p` → **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符。**一律 `py -3.12 -X utf8`**。
- 本机 3.12 通道：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2 / pywin32 312；Excel **16.0 Build 20326**（COM 可用）。
- **`Path.read_text(newline=)` 在 3.10–3.12 不存在**（3.13 才有）。一律用 `open(..., newline="")` 或 `csvio.read_text()`。
- **Excel COM segfault**：先 `CoUninitialize` 再析构 COM 代理 → 进程 exit 139。修法见不变量 9。
- **Excel COM 会写 CRLF**（`SaveAs FileFormat=6`）；openpyxl / pandas / sqlite 通道写 LF。这是四条通道的真实差异，**不许归一**。
- `python -m tripwire` 需要 `src/` 在 `sys.path`：未 `pip install -e .` 时用 `PYTHONPATH=src`。
- 临时落点用仓库内 `.tmp/`（已 gitignore；脱敏门也跳过它）。Git Bash 的 `/tmp` 与 Windows Python 不通。
- **`csv.reader` 的 `newline=""` 是必需的**：`io.StringIO(text)` 默认做通用换行翻译，会让 CRLF 快照里的 `\r` 混进单元格。
  `csvio.parse_csv_text` 已写对；自己另起解析器时别漏。

---

## 六、DoD 逐项 checklist（M2）

- [x] `align()` 三策略落地；`key` 缺 `--key` → `NoKeyForAlign`（exit 3）
- [x] `diff_tables()` 产出 `DiffResult(diffs, structures, rows_compared, cells_compared)`
- [x] 四项结构差异 `row_count` / `col_count` / `col_order` / `header` 各自独立成记录
- [x] `--batch N` 产 `dtype_drift`；不给则不产
- [x] `row_key` 三策略语义（主键文本 / `#<row_index>` / 原行指纹）
- [x] `DiffRecord` 带缺格标记（`orig_missing` / `got_missing`），空值三态可区分
- [x] 差异排序 `(row_key, col_index)`；双跑 `--json` 逐字节一致
- [x] 主键重复 → exit 3（两侧都查）；`--key` 列不存在 → exit 3 并报列名
- [x] 原型 14 单元格 / 9 差异（冻结产物**与**真机 Excel 两条路径都复现）
- [x] `tests/test_diff_engine.py` 30 passed
- [x] 全套 `pytest -q` → 83 passed
- [x] 布局门全绿 / 脱敏门 0 命中
- [x] sdist 解包后自足（两门 + 83 passed）
- [x] `docs/diff-schema.md` 落盘；`plan/03` M2 增补 `lcs` 锚点口径；`plan/02` IR 表补 `DiffRecord` 新字段
- [x] 4 处状态副本一致（M0–M2 ✅ / M3–M6 ⬜）
- [x] `plan/06` 缺口 G-2 关闭（只描述，不点名文件）
- [ ] CI 首跑 —— **不适用本轮**（无远端）。写"CI 待首推验证"，不写"CI 绿"

---

## 七、关键命令速查

```bash
# 门（第一动作）
py -3.12 tools/check_sprint_layout.py
py -3.12 tools/check_desensitized.py
py -3.12 tools/verify_gate_mutations.py      # 门自身的变异验证

# 测试（M2 出口门 E2 = 第一条）
py -3.12 -m pytest -q tests/test_diff_engine.py
py -3.12 -m pytest -q

# 跑管线（四条通道）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/pandas.json     --input sample.csv --key id
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/json_sqlite.json --input sample.csv --key id
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/openpyxl.json   --input sample.csv --key id
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/excel_com.json  --input sample.csv --key id

# 对管线产物直接做差异
PYTHONPATH=src py -3.12 -X utf8 -m tripwire diff \
  --orig runs/<run_id>/stage-0.csv --got runs/<run_id>/stage-1.csv --key id --stage-index 1

# 无主键必须被拒绝（exit 3）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire diff --orig a.csv --got b.csv

# 通道可用性（不可用的会显式写 UNAVAILABLE，别当成"已验证"）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire selftest

# 校验声明 / 规则条数
PYTHONPATH=src py -3.12 -X utf8 -m tripwire validate-pipeline pipelines/*.json
PYTHONPATH=src py -3.12 -X utf8 -m tripwire rules --count
```

> 本机（Windows）把 `python` 换成 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。
