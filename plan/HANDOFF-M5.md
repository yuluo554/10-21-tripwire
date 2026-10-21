# HANDOFF-M5 → M6（报告三格式 + 首屏三段 + 退出码四条）

> **续接方式**（用户侧）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `py -3.12 tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = M5（报告与 CI 出口），已完成；下一棒 = **M6（脱敏与发布：公开仓库 + tag + Release + 发布留档）**。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| `report/model.py`：`RunResult` + `build_run_result(run, expected, *, key, strategy, stage_index)` | ✅ | `tests/test_report.py`（23 passed）；三条命令共用（`run --expected` / `report` / `gate`） |
| `render_md.py` / `render_json.py` / `render_sarif.py`：**只读 `RunResult`** | ✅ | AST 守门 `test_renderers_only_read_run_result`（不 import 差异/规则/门禁/管线，不 `open()`/`read_text()`） |
| 首屏三段（顺序与字面固定） | ✅ | `test_first_screen_three_lines`（前三行字面）+ `test_lossless_first_screen_literals` |
| 第三段整行 = **`Gate.line()`**（不重拼格式串） | ✅ | `test_gate_line_comes_from_gate_not_reassembled`（stdout / MD / JSON / SARIF 四处同一串） |
| `report` 子命令接线（`--format md,json,sarif`、`--expected` 必填） | ✅ | `test_report_writes_three_files_and_keeps_stages_json` / `test_report_format_selection` |
| `run` 新增 `--expected`（M5 起 `run` 串起 M1→M2→M3→M5） | ✅ | `test_run_refuses_verdict_without_truth_and_uses_gate_with_it`（两条都断言） |
| 产物落 `runs/<run_id>/report.{md,json,sarif}`，**不改写** `stages.json` 与快照 | ✅ | `test_report_writes_three_files_and_keeps_stages_json`（逐文件字节比对） |
| 三格式同源：finding 集合按 `fingerprint` 相等 | ✅ | `test_three_formats_same_findings` / `test_first_screen_carried_by_all_three_formats` |
| `unclassified` 也是一等公民 finding（三格式都带） | ✅ | `test_unclassified_is_a_first_class_finding`（含 SARIF `ruleId`） |
| SARIF 2.1.0 形状：`ruleId` / `level` / `partialFingerprints.primaryLocationLineHash` / `stage-<k>.csv` / **不写绝对路径** | ✅ | `test_sarif_shape_and_no_absolute_paths` |
| 退出码 **0/1/2/3 各一条**（`main(argv)` 与真实进程各一遍） | ✅ | `tests/test_exit_codes.py`：`test_exit_0_lossless_and_gate_passed` / `test_exit_1_lossy_and_gate_passed` / `test_exit_2_gate_failed` / `test_exit_3_usage_channel`（15 passed） |
| **显式改写** `test_run_does_not_claim_lossless_in_m1` + 删 `NO_VERDICT_NOTE` | ✅ | 现名 `test_run_refuses_verdict_without_truth_and_uses_gate_with_it`；`grep NO_VERDICT_NOTE` 0 命中 |
| `_not_implemented()` 删除（M5 后无未实现子命令） | ✅ | `tests/test_skeleton.py::test_unimplemented_commands_are_gone` |
| 渲染不读时钟（两次渲染逐字节一致 + AST） | ✅ | `test_render_is_clock_free`；`test_same_input_two_runs_byte_identical`（三个报告文件逐字节一致） |
| 零网络 AST 守门（`src/tripwire/**`） | ✅ | `test_no_network_imports_in_package`（扫 28 个 .py） |
| K11 守门：裸 `json.dump(` 0 命中 | ✅ | `test_no_bare_json_dump_in_package` |
| G12 机制面：`rules.json` 从包内读到 18 条 | ✅ | `test_rules_json_readable_from_package`（`importlib.resources` + `package-data` 声明） |
| 首次明确定义的"无损三形态"与首屏第二段字面 | ✅ | `docs/report-schema.md` §二/§三；`plan/03` §M5 的八条补充口径 |
| 全套测试 | ✅ | `py -3.12 -X utf8 -m pytest` → **204 passed in 105.72s**（M0 17 + M1 36 + M2 30 + M3 34 + M4 60 + M5 27） |
| 布局门 / 脱敏门 / 变异验证 | ✅ | 布局门全绿（文档 10 / 交接单 6 / 状态副本 4）；脱敏门 0 命中（扫 84 份）；变异 17 组 **14 红 / 3 SKIP / 0 未按预期** |
| sdist 自足 | ✅ | `py -3.12 -m build --sdist --wheel` → 解包树两门全绿 + `pytest` exit 0（204 collected；`docs/report-schema.md` 随包） |
| G12 的"干净 venv"面 | ✅ | `py -3.12 -m venv` → `pip install --no-deps --no-index <wheel>` → 包内读到 18 条规则 + `tripwire --version` = `0.1.0.dev0` + `--help` 里有 `report`（全程离线） |

**退出码实测（真实进程，金样本 seed 42 / 200 行）**：

| 码 | 命令 | 实测 |
|---|---|---|
| 0 | `run` 控制组样本 + `expected.json = {"cells": []}` | `VERDICT: LOSSLESS (0/480 cells, 0 rules)` + 空跑 NOTE；exit 0 |
| 1 | `run` 金样本 + `json_sqlite` + 金真值 | `VERDICT: LOSSY (45/1600 cells, 3 rules)`；exit 1 |
| 2 | `run` 金样本 + **裁剪过的**真值（只留 1 条期望） | `GATE FAILED recall 1.00 / precision 0.02`；exit 2（报告**仍产出**） |
| 3 | `run` 无 `--expected` / `report` 无 `--expected` / 无 `--key` / `--format xml` | 一律 exit 3，且 stderr 说清原因 |

**未发生的事（不许写成已完成）**：

- **没有跑过一次 CI**（无远端）。G-6 仍开：一切 CI 结论只能写"本地等价校验"。
- **没有 tag / 没有 Release / 没有附件**（G-7，M6）。
- **首屏三段只在本地实测过**；四条通道里 `excel_com_csv` 只在 Windows 有（CI 上必须 skip 并标注）。
- **没有为报告加任何"大规模压测"结论**；金样本仍是 200 行合成样本（`data/README` §6.7）。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

M4 的 34 条仍然全部有效（见 `plan/HANDOFF-M4.md` §二），下面只列 **M5 新增/改动** 的：

35. **判定出口 M5 起三条并列**（D19）：`run --expected`（可选参数）/ `report`（`--expected` **必填**）/ `gate`。
    `run`（无真值）/ `diff` / `attribute` 一律 exit 3 并明说"不产出有损/无损判定"。
    **0/1 只出自真算过门禁的出口**——`run` 的码来自 `RunResult.exit_code`（内部就是 `compute_gate`）。
36. **首屏三段的字面只在 `report/model.py` 拼一次**（`RunResult.first_screen()`）；第三段**整行**取
    `Gate.line()`。三个渲染器里出现 `VERDICT:` / `FIRST LOSS AT:` / `GATE: recall` 即假同源（AST 有守门）。
37. **`FIRST LOSS AT` 三种形态**（`docs/report-schema.md` §三）：`none` / `stage k = name (runtime)` /
    `unknown (no snapshot stage carried the change)`。三种**都不省略整行**；阶段号取
    `Attribution.first_seen_at` 的最小值（实际观察到的那一步）。
38. **运行时指纹分族**：`Excel {v} Build {b}` / `pandas {v}` / `openpyxl {v}` / `SQLite {v}` / 其余 `unknown`。
    `runtime_label()` 只对 `excel_build` 去掉 `.0` 尾巴（COM 回来是浮点读数 `20326.0`，Build 号是整数）；
    `excel_version = "16.0"` 是**版本号**，不动。**`stages.json` 里记录的仍是 COM 原样**（K1：只改渲染）。
39. **`LOSSLESS` ⇒ `Gate.vacuous == True`**（D20，可证）：真值只登记"会变的格" ⇒ 期望集非空就必有差异。
    所以 `vacuous` 时必须多打一行 `NOTE: 本次 0 条差异 —— 门禁「通过」是空跑通过…`。
    `verify` 用的无损样本 = `tests/conftest.py::control_only_csv` + `{"cells": []}`。
40. **SARIF 的 `artifactLocation.uri` = 本次判定阶段的快照**（`stage-<k>.csv`，**相对名**）；
    "值第一次在哪一步变的"放 `results[*].properties.firstSeenStage*`。首屏三段另放
    `runs[0].properties.firstScreen`；`invocations[0]` 带 `executionSuccessful` / `exitCode`。
41. **`report.json` 的 `gate` 段就是 `Gate.to_json()`**：数字在 `gate.counts.{expected,reported,matched}`
    下（不是顶层），失败明细在 `gate.missing/unexpected/wrong_rule`。
42. **`build_run_result()` 是唯一在内存里算结论的地方**：差异 → 归因 → 门禁 → 判定。
    `gate` 命令也走它（只保留自己的打印形态），M5 之前那三份重复实现已收掉。
43. **`_not_implemented()` 已删除**；`argparse` 的必填参数（`report --expected`）是 exit 3 的正常来源。
44. **`tests/conftest.py` 现在有跨文件夹具** `control_only_csv`（金样本里 `ctl-*` 60 行）。
    改它要同时想 `tests/test_report.py` 与 `tests/test_exit_codes.py` 的 exit-0 那两条。
45. **报告层不写绝对路径**（`str(run.out_dir)` 不该出现在任何报告文件里），也不含时间戳；
    `render_json.render(result)` 与 `serialization.write_json(path, payload(result))` 产出**同一串字节**。
46. **K11 AST 守门在 `tests/test_report.py`**（`json.dump(` 0 命中）；新增落盘代码别绕开 `serialization`。
47. **状态副本仍是 4 处**（`plan/00` 里程碑表 / `plan/05` 状态表 / `README.md` 状态表 / `plan/00` 台账）：
    翻任一里程碑必须在**同一提交**里改全 4 处。
48. **`docs/report-schema.md` 是报告形状的落点**；改首屏字面 / SARIF 映射 / 退出码对照，必须同步它
    与 `plan/03` §M5 的八条补充口径（`tests/test_report.py` 会打挂不一致的那半边）。

---

## 三、下一棒待办（M6：脱敏与发布）

- [ ] 发布前核对包名与仓库名（D5/Q1）：PyPI `tripwire`、GitHub `yuluo554/10-21-tripwire`
- [ ] `plan/RELEASE-M6.md` **在 tag 之前**写好并进 tag 树：§一 tag 前事实 / §二 tag 后追加事实 / §三 阶段 7 覆盖对账（三态：实现 / 不适用 / 待首推）
- [ ] `py -3.12 -m build` 产 sdist + wheel；**`SHA256SUMS` 只由 CI 生成**（本机不产）
- [ ] 首次推远端 → 看 CI 真跑（G-6）；CI 上 `excel_com_csv` 必须 skip 并标注
- [ ] `v0.1.0` annotated tag 打在定版提交上；Release 附 sdist + wheel + `SHA256SUMS`；正文登记 digest
- [ ] tag 后**只允许非交付面提交**（`plan/`、`README.md`、`tools/`、`tests/`）；`src/`、`rules.json`、`pipelines/`、`fixtures/` 零差异
- [ ] 复核：真下载 + 中立目录 + `sha256sum -c` + 从 tag 重建 `cmp` 逐字节一致
- [ ] 脱敏门 0 命中（当前 83 份 0 命中）+ `plan/06` 关 G-6 / G-7
- [ ] 收尾：写 `plan/HANDOFF-M6.md`（或 `plan/WRAPUP-M6.md`）+ 改 4 处状态副本

> **自指约束**：tag 树内的留档**不写** tag OID / commit sha / 附件 sha256 的字面值——字面值写在 tag 之后的提交或 Release 正文里。

> **M6 最可能踩的两处**：
> ① `plan/RELEASE-M6.md` 必须在 tag **之前**落盘（布局门 `LAYOUT.RELEASE` 在 M6 ✅ 后会要求"两栏 + 覆盖对账 + ≥3 行三态"）；
> ② 交付面（`src/`、`rules.json`、`pipelines/`、`fixtures/`）在 tag 之后**零差异**——想改就得重新定版。

---

## 四、既定口径清单（K 编号，动了会打挂测试）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| K1 | 快照存原始文本，不存 DataFrame；落盘走 `write_text_raw` | `test_snapshot_is_raw_text_not_reserialized` 红 |
| K2 | `run_id` 由内容派生，不用时间戳 | `test_run_id_*` 红 |
| K3 | `excel_com_csv` ≠ `openpyxl_csv`，不混称、不回落 | `test_excel_stage_does_not_fall_back_to_openpyxl` 红 |
| K4 | 无 `--key` 且 `--align key` → exit 3 | `test_no_key_refuses_to_run` 等红 |
| K5 | 差异排序 `(row_key, col_index)` 稳定 | `test_diff_order_stable` 红 |
| K6 | 规则谓词纯函数；一差多命中按 `id` 升序取首条 | `test_also_matched_recorded` 红 |
| K7 | `unclassified` 单独计数、可 `--fail-on` | `test_cli_attribute_fail_on_unclassified_exits_2` 红 |
| K8 | 生成器不读时钟/全局 random（自研 splitmix64） | `test_splitmix64_known_sequence` 红 |
| K9 | 报告渲染不读时钟/随机；三格式同源；首屏字面只拼一次 | `test_render_is_clock_free` / `test_three_formats_same_findings` / `test_renderers_only_read_run_result` 红 |
| K10 | `fingerprint = sha256(row_key \x1f col \x1f rule)[:16]` | `test_fingerprint_matches_documented_formula` 红 |
| K11 | 一切 JSON 落盘走 `serialization.write_json`（裸 `json.dump(` 0 命中） | `test_no_bare_json_dump_in_package` 红 / 产物字节漂移 |

### M4/M5 新增的口径（D 编号）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| D16 | 样本形态合法 ⟺ "变了的通道集合 ⊆ 该规则的 `possible_stages`" | 越界通道落 `unclassified` → 门禁失败 |
| D17 | 夹具表稠密；`zip` 列填充必须整数形 | 控制组假差异 → precision 失守 |
| D18 | 0/1 只出自真算过门禁的出口 | `run`/`diff`/`attribute` 报 0/1 = 把"没验过"写成"验过了" |
| D19 | 判定出口三条并列（`run --expected` / `report` / `gate`），无真值仍 3 | `test_exit_3_usage_channel` / `test_run_refuses_verdict_without_truth_and_uses_gate_with_it` 红 |
| D20 | `LOSSLESS` ⇒ `Gate.vacuous`；空跑必须在报告里写清楚 | `test_lossless_run_says_vacuous_clearly` / `test_vacuous_gate_does_not_fake_coverage` 红 |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

- `py -0p` → **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符。**一律 `py -3.12 -X utf8`**。
- 本机 3.12 通道：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2 / pywin32 312；Excel **16.0 Build 20326**（COM 可用）。
- **`Path.read_text(newline=)` 在 3.10–3.12 不存在**（3.13 才有）。一律 `open(..., newline="")`。
- **Excel COM segfault**：先 `CoUninitialize` 再析构代理 → exit 139。已封进 `_close_excel()`。
- **Excel COM 写 CRLF**；其余三通道写 LF。这是真实差异，**不许归一**（报告本身一律 LF）。
- `python -m tripwire` 需要 `src/` 在 `sys.path`：未 `pip install -e .` 时用 `PYTHONPATH=src`。
- 临时落点用仓库内 `.tmp/`（已 gitignore）。Git Bash 的 `/tmp` 与 Windows Python 不通。
- **整库 `pytest` 实测 105.72s**（含 Excel COM 真机跑；M4 手记里的"8–10 分钟"是当时偏保守的估计）。
  pytest 收 `addopts = "-q"`，再给一个 `-q` 就成为 `-qq`：**摘要行不打印**，看退出码；
  要摘要就跑 `py -3.12 -m pytest -o addopts="" -q`。
- **`app.Build` 经 COM 回来是浮点读数 `20326.0`**（`app.Version` 是 `"16.0"` 字符串）：
  报告显示时只对 Build 去掉 `.0`（`report/model.py::_build_text`），`stages.json` 原样。
- **`report.json` 的 `Gate` 数字在 `gate.counts` 下**（`test_gate_line_comes_from_gate_not_reassembled` 踩过）。
- **`--format ""` 与未知格式都是 exit 3**：`_parse_formats` 返回 `None`（空列表也算"没点格式"）。
- **无损样本怎么造**：把金样本的 `ctl-*` 行单独成表 + 真值给 `{"cells": []}`
  （`tests/conftest.py::control_only_csv`）。**别用整张金样本**——它必然有差异。
- **报告里不许出现绝对路径**：`str(run.out_dir)` 一旦被写进报告，`test_sarif_shape_and_no_absolute_paths` 立刻红。
- **`Argparse` 的 `--expected` 必填**在 `report` 上：缺它走的是**参数错误 → 3**，不是"缺真值"分支。

---

## 六、DoD 逐项 checklist（M5）

- [x] `report/model.py`：`RunResult` + `build_run_result(...)`
- [x] `render_md.py` / `render_json.py` / `render_sarif.py`：只读 `RunResult`（AST 守门）
- [x] 首屏三段（顺序与字面固定；第三段整行 = `Gate.line()`）
- [x] `report` 子命令接线（`--format md,json,sarif`、`--expected` 必填）
- [x] 产物落 `runs/<run_id>/report.{md,json,sarif}`（不写绝对路径、不含时间戳）
- [x] SARIF 2.1.0：`ruleId` / `level=warning` / `partialFingerprints.primaryLocationLineHash` / `artifactLocation.uri = stage-<k>.csv`
- [x] 退出码 0/1/2/3 各一条（`main(argv)` 与真实进程一致）
- [x] **显式改写** `test_run_does_not_claim_lossless_in_m1` + 删 `NO_VERDICT_NOTE` + 删 `_not_implemented()`
- [x] 零网络 AST 守门（`src/tripwire/**`）
- [x] 渲染不读时钟（两次渲染逐字节一致 + AST）+ 同输入两次 run 报告逐字节一致
- [x] `tests/test_report.py`（E5）23 passed；`tests/test_exit_codes.py` 15 passed
- [x] 全套 `pytest -q` → 204 passed
- [x] 布局门全绿 / 脱敏门 0 命中（84 份）/ 变异 17 组（14 红 / 3 SKIP / 0 未按预期）
- [x] sdist 解包后自足（两门 + pytest exit 0，204 collected）；wheel + 干净 venv 能读到包内 `rules.json` 与 `report` 子命令
- [x] 4 处状态副本一致（M0–M5 ✅ / M6 ⬜）；`plan/06` 缺口 G-5 关闭
- [x] `docs/report-schema.md` 落盘；`plan/03` §M5 补八条落地口径；`plan/02` §四 退出码表改写
- [ ] CI 首跑 —— **不适用本轮**（无远端）。写"CI 待首推验证"，不写"CI 绿"

---

## 七、关键命令速查

```bash
# 门（第一动作）
py -3.12 tools/check_sprint_layout.py
py -3.12 tools/check_desensitized.py
py -3.12 tools/verify_gate_mutations.py

# 测试（M5 出口门 E5 = 第一条）
py -3.12 -m pytest -q tests/test_report.py tests/test_exit_codes.py
py -3.12 -m pytest -q            # 全库约 8–10 分钟（4 次 Excel COM），建议后台跑

# 判定 + 三格式报告（首屏三段就是前三行）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/json_sqlite.json \
    --input fixtures/golden/orig.csv --key id --out-dir runs --expected fixtures/golden/expected.json
PYTHONPATH=src py -3.12 -X utf8 -m tripwire report --run-id <run_id> \
    --expected fixtures/golden/expected.json --key id --format md,json,sarif

# 退出码四条（0/1/2/3）
PYTHONPATH=src py -3.12 -X utf8 -m tripwire run --pipeline pipelines/json_sqlite.json \
    --input fixtures/golden/orig.csv --key id --out-dir runs     # 无真值 → 3
# 0 的那条：控制组样本 + {"cells": []} 真值（见 tests/conftest.py::control_only_csv）

# 夹具 / 通道可用性
PYTHONPATH=src py -3.12 -X utf8 -m tripwire gen-fixture --seed 42 --rows 200 --out-dir fixtures/golden
PYTHONPATH=src py -3.12 -X utf8 -m tripwire rules --count      # 18
PYTHONPATH=src py -3.12 -X utf8 -m tripwire selftest

# sdist 自足复核 + wheel（G12）
py -3.12 -m build --sdist --wheel --outdir .tmp/sdist
tar -xzf .tmp/sdist/*.tar.gz -C .tmp/unpack && cd .tmp/unpack/tripwire-* && py -3.12 -m pytest -q
py -3.12 -m venv .tmp/venv && .tmp/venv/Scripts/python -m pip install --no-deps --no-index .tmp/sdist/*.whl
```

> 本机（Windows）把 `python` 换成 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。