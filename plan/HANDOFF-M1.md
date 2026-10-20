# HANDOFF-M1 → M2（往返管线执行器 + 逐段快照）

> **续接方式**（用户侧）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `python tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = M1（管线执行器 + 逐段快照），已完成；下一棒 = **M2（单元格级差异引擎 + 对齐三策略）**。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| 四条通道全部真跑通 | ✅ | `py -3.12 -X utf8 -m pytest tests/test_pipeline_stages.py -q` → 11 passed（本机 Excel COM 可用，**无 skip**） |
| `excel_com_csv` 真机验证 | ✅ **本机实跑** | Excel `16.0` Build `20326.0`；`stages.json[*].runtime.excel_version/excel_build` 有值 |
| `openpyxl_csv` fallback 通道 | ✅ | 同上测试；`runtime.openpyxl_version = 3.1.5` |
| 逐段快照为原始文本（K1） | ✅ | `tests/test_snapshots.py::test_snapshot_is_raw_text_not_reserialized`：Excel 输出的 `\r\n` 在 `stage-1.csv` 里**原样保留** |
| sha256 可独立复算（G2） | ✅ | `test_stage_text_sha256_matches`：从字节重算，四条通道全部一致 |
| `stages.json` 字段齐全 | ✅ | `test_required_stages_json_fields` + `test_runtime_fingerprint_fields`（`runtime` 六键恒在，不适用为 `null`） |
| `run_id` 内容派生（K2） | ✅ | `test_same_input_same_run_id` / `test_run_id_ignores_timestamp_and_path` / `test_run_id_stable_across_processes` |
| 同输入双跑逐字节一致（G9 的 M1 部分） | ✅ | `test_double_run_is_byte_identical`（`stages.json` + 两份快照） |
| 幂等复用 | ✅ | `test_rerun_same_out_dir_is_idempotent`（`reused=True`，产物不变） |
| 缺依赖显式失败（D1） | ✅ | `test_missing_engine_fails_loudly`：exit 3 + `stages.json` 留 `failed` 记录 + 后续阶段不再执行 |
| 不回落 openpyxl（K3） | ✅ | `test_excel_stage_does_not_fall_back_to_openpyxl` |
| 两条 Excel 通道产出**不同**损失形态 | ✅ | `test_excel_and_openpyxl_differ_on_2_pow_50`：2^50 → Excel `1.1259E+15` vs openpyxl `1125899906842624` |
| `docs/pipeline-schema.md` | ✅ | `git ls-files docs/pipeline-schema.md` |
| 退出码用法通道 | ✅ | `tests/test_exit_codes.py` → 11 passed |
| 全套测试 | ✅ | `py -3.12 -X utf8 -m pytest -q` → **53 passed**（M0 的 17 + M1 新增 36） |
| 布局门 / 脱敏门 | ✅ | 布局门 9 条全绿；脱敏门 0 命中 |
| sdist 自足 | ✅ | `python -m build --sdist` → 解包 → 两门 + `pytest` 53 passed（`docs/` 已随包） |

**未发生的事（不许写成已完成）**：
- **没有跑过一次 CI**（无远端）。CI 结论只能写"本地等价校验"。
- **`run` 不返回 0/1/2**：差异引擎在 M2、门禁在 M4，此刻没有任何差异被算过，
  所以 `run` 一律 exit 3 并在输出里写"不产出有损/无损判定"。**跑通 ≠ 判为无损**。
- M2–M6 未开工。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

1. **状态副本共 4 处**：`plan/00` 里程碑表、`plan/05` 状态表、`README.md` 状态表、
   `plan/00` 承诺-证据台账。翻任一里程碑必须在**同一提交**里改全 4 处，否则 `LAYOUT.STATUS` / `LAYOUT.LEDGER` 变红。
2. **`plan/05` §三 出口门表首列刻意是 `E0`…`E6`**，不是里程碑号。改成 `| M1 |` 会被布局门误采成第二份状态行 → 假红。
3. **`plan/06` 缺口表**：「目标里程碑」列不参与扫描，但**「说明」列里不许写里程碑号**（文件名里的 `M6` 也会中招）。关闭缺口时只描述、不点名文件。
4. **版本号唯一来源 = `src/tripwire/__init__.py::__version__`**；`pyproject.toml` 用 `dynamic = ["version"]`。永不写第二份字面量。
5. **退出码单点 = `src/tripwire/exitcodes.py`**；口径 = `data/README.md` §6.3。`argparse` 的 `SystemExit(2)` 经 `_Parser.error()` → `_UsageError` → exit 3。
6. **写盘唯一入口 = `tripwire/serialization.py`**。M1 新增 `write_text_raw()`：
   快照必须**逐字节**落盘（CRLF / 无结尾换行都是被测形态），而 `write_json` / `write_text`
   仍做归一。**不要把快照改成 `write_text`**——那会让审计器自己成为失真源（K1）。
7. **`csvio.read_text` 必须走 `open(..., newline="")`**：`Path.read_text(newline=)` 是 **3.13** 才有的参数，
   本包承诺 3.10+。M0 骨架里那行在 3.12 上会 `TypeError`——M1 已修，别再写回去。
8. **`pipeline/stages/*` 里依赖一律函数内导入**：这样缺 pandas / 缺 openpyxl / 缺 pywin32 的机器
   仍能 `import tripwire` 并跑别的通道；模块顶层 import 会把这些机器整个打死。
9. **Excel COM 收尾顺序是硬约束**：关文档 → `app.Quit()` → 放代理 → `gc.collect()` → `CoUninitialize()`。
   顺序反了本机实测 **segfault（exit 139）**：同一进程内连续两次"init → DispatchEx → Quit → uninit"必崩。
   已封进 `excel_com_csv._close_excel()`，**不要内联重写**。
10. **`stages.json` 不含任何时间戳 / 耗时**。`data/README` §6.5 的字段表里没有时间类字段，
    而 G9 要求"同输入双跑逐字节一致"——加一个 `generated_at` 就让这条承诺只在同一天内成立。
11. **`decl_sha256` 只哈希语义字段**（`name` / `input` / `schema_version` / `stages`），不哈希文件路径与缩进。
    同一份声明换个文件名 → 同 `run_id`（`test_decl_fingerprint_ignores_file_location` 钉住）。
12. **`stage_index` 是 1-based 输出序号**：`stage-0` = 输入副本（`stage_name="input"`），`stage-1` = 第一份输出。
    M3 的 `--explain` 里 `first_seen_at=stage <k>` 必须与这套编号一致。
13. **`rules.json` 已冻结 18 条**（id 1–18，四族 8/2/4/4）。M3 只新增谓词函数，不得增删规则、不得改 `id`/`name`/`possible_stages`。
14. **`excel_com_csv` 与 `openpyxl_csv` 是两个 stage 名**，`schema.py` 硬校验 stage_name↔engine 一一对应。
    `pipelines/` 现有 4 份声明（`pandas` / `excel_com` / `openpyxl` / `json_sqlite`），各跑各的。
15. **`_not_implemented()` 只剩 `diff` / `attribute` / `gen-fixture` / `report` 四个分支**；`run` 已接线。
    M2 落地 `diff` 时同样要**删掉**旧分支并补测试，而不是在旧分支上加判断。
16. **`run` 当前的 exit 3 是刻意的**（`NO_VERDICT_NOTE`）。M5 接线判定通道时，
    `tests/test_exit_codes.py::test_run_does_not_claim_lossless_in_m1` 必须**显式改写**，不许放宽断言蒙过去。

---

## 三、下一棒待办（M2）

- [ ] `src/tripwire/diff/align.py`：`align(orig, got, strategy, key) -> list[tuple[int|None, int|None]]`
- [ ] `src/tripwire/diff/engine.py`：`diff_tables(...) -> DiffResult(diffs, structures)`
- [ ] 三策略：`key`（默认，无 `--key` → exit 3，K4）/ `position` / `lcs`（精确指纹，不做相似度）
- [ ] 四项结构差异独立成记录：`row_count` / `col_count` / `col_order` / `header`；`--batch N` 另产 `dtype_drift`
- [ ] `row_key` 语义：`key` 下 = 主键值文本；`position` 下 = `#<row_index>`；`lcs` 下 = 匹配到的原行指纹
- [ ] 差异排序 `(row_key, col_index)` 稳定（K5）；双跑逐字节一致
- [ ] 主键重复 → exit 3（不"取第一个"）；`--key` 列不存在 → exit 3 并报列名
- [ ] `tests/test_diff_engine.py`（出口门 E2）：原型 9 差异、四项结构差异、无主键 exit 3、重复主键 exit 3、排序稳定
- [ ] 收尾：改 4 处状态副本 → 关 `plan/06` 的 G-2 → 写 `plan/HANDOFF-M2.md` → commit

> **M2 可直接复用的东西**：`csvio.read_csv(path) -> (CsvTable, text)` 已是原文视图；
> `runner.RunStages.stages[k].sha256` 与 `stage-<k>.csv` 是现成的"比较对象"；
> `csvio.CsvTable.cell(row, col)` 对**行短于表头**返回 `""`（缺格语义），`column_index` 抛 `KeyError`。

---

## 四、既定口径清单（K 编号，动了会打挂测试）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| K1 | 快照存原始文本，不存 DataFrame；落盘走 `write_text_raw` | `test_snapshot_is_raw_text_not_reserialized` 红 |
| K2 | `run_id` 由内容派生，不用时间戳 | `test_run_id_*` / `test_same_input_same_run_id` 红 |
| K3 | `excel_com_csv` ≠ `openpyxl_csv`，不混称、不回落 | `test_validate_pipeline_rejects_engine_stage_mismatch` / `test_excel_stage_does_not_fall_back_to_openpyxl` 红 |
| K4 | 无 `--key` 且 `--align key` → exit 3 | `test_no_key_refuses_to_run_and_writes_nothing` 红 |
| K5 | 差异排序 `(row_key, col_index)` 稳定 | M2 双跑逐字节测试红 |
| K6 | 规则谓词纯函数；一差多命中按 `id` 升序取首条 | M3 `test_also_matched_recorded` 红 |
| K7 | `unclassified` 单独计数、可 `--fail-on` | M3/M4 门禁失去意义 |
| K8 | 生成器不读时钟/全局 random（自研 splitmix64） | M4 同 seed 逐字节测试红 |
| K9 | 报告渲染不读时钟/随机；三格式同源 | M5 `test_three_formats_same_findings` 红 |
| K10 | `fingerprint = sha256(row_key \x1f col \x1f rule)[:16]` | M5 跨 run diff 失效 |
| K11 | 一切 JSON 落盘走 `serialization.write_json` | 产物字节漂移 |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

- `py -0p` → **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符。**一律 `py -3.12 -X utf8`**。
- 本机 3.12 通道：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2 / **pywin32 312（M1 新装）**；
  Excel **16.0 Build 20326.0**（COM 可用）。`pywin32` 不在 `[project.dependencies]` 里，只在 `[windows]` extra。
- **`Path.read_text(newline=)` 在 3.10–3.12 不存在**（3.13 才有）。M0 的 `csvio.read_text` 与本轮
  我自己的两处测试都踩过：报 `TypeError: Path.read_text() got an unexpected keyword argument 'newline'`。
  一律用 `open(..., newline="")` 或 `csvio.read_text()`。
- **Excel COM segfault**：先 `CoUninitialize` 再析构 COM 代理 → 进程 exit 139。同一进程内
  连续两次"init → DispatchEx → Quit → uninit"必崩（本机 3/3 复现）。修法见不变量 9。
- **Excel COM 会写 CRLF**（`SaveAs FileFormat=6`）；openpyxl / pandas / sqlite 通道写 LF。
  这不是 bug，是四条通道的真实差异，**不许归一**。
- `python -m tripwire` 需要 `src/` 在 `sys.path`：未 `pip install -e .` 时用 `PYTHONPATH=src`。
  测试里 `subprocess` 起 CLI 必须显式传 `PYTHONPATH`（`test_exit_codes.py` 已示范）。
- 临时落点用仓库内 `.tmp/`（已 gitignore；脱敏门也跳过它）。Git Bash 的 `/tmp` 与 Windows Python 不通。

---

## 六、DoD 逐项 checklist（M1）

- [x] 四条通道各跑通一次（`test_three_families_produce_stages`，本机 0 skip）
- [x] `excel_com_csv` **真机**跑通并记录 `excel_version` / `excel_build`
- [x] `stages.json` 含每阶段 `columns`（名 + 声明类型）/ `rows` / `cols` / `sha256` / `runtime`
- [x] `stage-<k>.csv` 为原始文本（CRLF 保留、无 BOM 强转）且 sha256 可独立复算
- [x] 缺依赖 → `StageUnavailable` → exit 3 + `stages.json` 留 `failed` 记录 + 终止整条管线
- [x] 不回落 openpyxl（D1/K3）
- [x] 同输入同 `run_id`（含跨进程）；双跑逐字节一致
- [x] 幂等复用；同 id 异内容 → 冲突
- [x] `docs/pipeline-schema.md` 落盘（阶段命名规则 + 禁止混称 Excel + 失败路径）
- [x] `tests/test_pipeline_stages.py` / `tests/test_snapshots.py` / `tests/test_exit_codes.py`
- [x] 全套 `pytest -q` → 53 passed
- [x] 布局门全绿 / 脱敏门 0 命中
- [x] sdist 解包后自足（两门 + 53 passed，`docs/` 随包）
- [x] 4 处状态副本一致（M0–M1 ✅ / M2–M6 ⬜）
- [x] `plan/06` 缺口 G-1 关闭（只描述，不点名文件）
- [ ] CI 首跑 —— **不适用本轮**（无远端）。写"CI 待首推验证"，不写"CI 绿"

---

## 七、关键命令速查

```bash
# 门
python tools/check_sprint_layout.py
python tools/check_desensitized.py
python tools/verify_gate_mutations.py      # 门自身的变异验证

# 测试（M1 出口门 E1 = 前两条）
python -m pytest -q tests/test_pipeline_stages.py tests/test_snapshots.py
python -m pytest -q

# 跑管线（四条通道）
PYTHONPATH=src python -m tripwire run --pipeline pipelines/pandas.json    --input sample.csv --key id
PYTHONPATH=src python -m tripwire run --pipeline pipelines/json_sqlite.json --input sample.csv --key id
PYTHONPATH=src python -m tripwire run --pipeline pipelines/openpyxl.json  --input sample.csv --key id
PYTHONPATH=src python -m tripwire run --pipeline pipelines/excel_com.json  --input sample.csv --key id

# 通道可用性（不可用的会显式写 UNAVAILABLE，别当成"已验证"）
PYTHONPATH=src python -m tripwire selftest

# 校验声明 / 规则条数
PYTHONPATH=src python -m tripwire validate-pipeline pipelines/*.json
PYTHONPATH=src python -m tripwire rules --count

# sdist 自足复核
python -m build --sdist --outdir .tmp/sdist
tar -xzf .tmp/sdist/*.tar.gz -C .tmp/unpack && cd .tmp/unpack/tripwire-* && python -m pytest -q
```

> 本机（Windows）把 `python` 换成 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。
