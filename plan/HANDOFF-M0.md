# HANDOFF-M0 → M1（结构化数据往返保真审计器）

> **续接方式**（用户侧）：`/goal 读取 "<项目绝对路径>\plan\HANDOFF-M0.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `python tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = M0（计划 + 装订 + 骨架），已完成；下一棒 = **M1（管线执行器 + 逐段快照）**。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| `plan/00`–`plan/06` 全部落盘 | ✅ | `git ls-files plan/` → 7 份 |
| `data/README.md`（口径唯一真相源） | ✅ | `git ls-files data/README.md` |
| `AGENTS.md`（方法论锚点） | ✅ | `python tools/check_sprint_layout.py` → `LAYOUT.BINDING_HEAD` PASS |
| 布局门 `tools/check_sprint_layout.py` | ✅ | 9 条判据全绿；`这轮扫到：文档 10 / 交接单 1 / 状态副本 4 / 文档点名工具 3` |
| 门自身的变异验证 | ✅ | `python tools/verify_gate_mutations.py` → 17 组：**14 组按预期红 / 3 组 SKIP（发布留档在 M6 前尚不存在）/ 0 组未按预期**；还原后两门复绿 |
| 脱敏门 `tools/check_desensitized.py` | ✅ | 0 命中；变异 4 组全红（同一条脚本） |
| 可运行骨架 | ✅ | `python -m tripwire --version` / `validate-pipeline pipelines/*.json` / `rules --count` → 18 |
| 冒烟测试 | ✅ | `python -m pytest -q` → 17 passed |
| CI workflow | ✅ 已写、**未跑** | `.github/workflows/ci.yml`；**无远端 → CI 待首推验证，不得写"CI 绿"** |

**未发生的事（不许写成已完成）**：没有 git remote、没有 tag、没有 Release、没有跑过一次 CI。
M1–M6 全部未开工。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

1. **状态副本共 4 处**：`plan/00` 里程碑表、`plan/05` 状态表、`README.md` 状态表、`plan/00` 承诺-证据台账。
   翻任一里程碑必须在**同一提交**里改全 4 处，否则 `LAYOUT.STATUS` / `LAYOUT.LEDGER` 变红。
2. **`plan/05` §三 出口门表的首列刻意不是里程碑号**（写成 `E0`…`E6`）。改成 `| M1 |` 会让布局门把它误采成第二份状态行 → 假红。
3. **`plan/06` 缺口表的「目标里程碑」列不参与扫描**，但**「说明」列里不许写里程碑号**——布局门会判"缺口表仍提已完成的里程碑"。关闭缺口时只描述、不点名文件（文件名里的 `M6` 也会中招）。
4. **版本号唯一来源 = `src/tripwire/__init__.py::__version__`**；`pyproject.toml` 用 `dynamic = ["version"]` 读它。**永远不要**在 `pyproject.toml` 里写第二份 version 字面量。
5. **退出码语义单点 = `src/tripwire/exitcodes.py`**；文档口径 = `data/README.md` §6.3。`argparse` 的 `SystemExit(2)` 必须经 `_Parser.error()` 转成 `_UsageError` → exit 3（这条已有测试钉住：`test_missing_required_arg_is_usage_error_not_gate_failure`）。
6. **写盘唯一入口 = `tripwire/serialization.py`**（K11：`sort_keys=True, ensure_ascii=False, indent=2` + LF + 结尾换行 + 原子写）。M1 的 `stages.json`、M5 的三份报告都必须走它。
7. **`csvio` 只做文本切分，不经 pandas**（K1）；pandas 只允许出现在 `pipeline/stages/pandas_csv.py` 内部。
8. **`rules.json` 已冻结 18 条**（id 1–18，四族计数 8/2/4/4，测试已断言）。M3 **只新增谓词函数**，不得增删规则、不得改 `id`／`name`／`possible_stages`——改了会让 `expected.json` 与 fingerprint 全部失效。
9. **`excel_com_csv` 与 `openpyxl_csv` 是两个 stage 名**，`pipelines/excel_com.json` 与 `pipelines/openpyxl.json` 各跑各的。`schema.py` 里有硬校验：stage_name 与 engine 必须一一对应（`test_validate_pipeline_rejects_engine_stage_mismatch`）。
10. **骨架期的未实现子命令统一 exit 3**（`_not_implemented()`）。M1 落地 `run` 时，要**删掉** `_not_implemented("run", ...)` 分支并补 `tests/test_exit_codes.py`，而不是在旧分支上加判断。

---

## 三、下一棒待办（M1）

- [ ] `src/tripwire/pipeline/runner.py`：`run_pipeline(decl, input_csv, out_dir) -> RunStages`
- [ ] `src/tripwire/pipeline/stages/`：四个阶段实现（`pandas_csv` / `excel_com_csv` / `openpyxl_csv` / `json_sqlite_csv`）
- [ ] `run_id = sha256(pipeline_name | input_sha256 | decl_sha256)[:16]`（K2，不含时间戳）
- [ ] `runs/<run_id>/stage-<k>.csv` 写**原始文本**；`stages.json` 写 `stage_index / stage_name / columns / rows / cols / sha256 / runtime`
- [ ] 缺依赖 → `StageUnavailable` → exit 3，`stages.json` 留 `failed` 记录，**终止整条管线**
- [ ] `docs/pipeline-schema.md`（阶段命名规则 + 禁止混称 Excel 的约束）
- [ ] 测试：`tests/test_pipeline_stages.py`、`tests/test_snapshots.py`（见 `plan/03` §M1 测试点）
- [ ] 本机先跑 `excel_com_csv` 真机验证（Windows + Excel COM），再补 openpyxl fallback
- [ ] 收尾：改 4 处状态副本 → 写 `plan/HANDOFF-M1.md` → commit

---

## 四、既定口径清单（K 编号，动了会打挂测试）

| 编号 | 约定 | 违反后果 |
|---|---|---|
| K1 | 快照存原始文本，不存 DataFrame | 审计器自己成为失真源 |
| K2 | `run_id` 由内容派生，不用时间戳 | 跨机不可对账；`test_same_input_same_run_id` 红 |
| K3 | `excel_com_csv` ≠ `openpyxl_csv`，不混称 | 制造假阴性；`test_validate_pipeline_rejects_engine_stage_mismatch` 红 |
| K4 | 无 `--key` 且 `--align key` → exit 3 | `test_no_key_refuses_to_run` 红 |
| K5 | 差异排序 `(row_key, col_index)` 稳定 | 双跑逐字节测试红 |
| K6 | 规则谓词纯函数；一差多命中按 id 升序取首条 | `test_also_matched_recorded` 红 |
| K7 | `unclassified` 单独计数、可 `--fail-on` | 门禁失去意义 |
| K8 | 生成器不读时钟/全局 random（自研 splitmix64） | 同 seed 逐字节测试红 |
| K9 | 报告渲染不读时钟/随机；三格式同源 | `test_three_formats_same_findings` 红 |
| K10 | `fingerprint = sha256(row_key \x1f col \x1f rule)[:16]` | 跨 run diff 失效 |
| K11 | 一切 JSON 落盘走 `serialization.write_json` | 产物字节漂移 |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

- `py -0p` → **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符。**一律 `py -3.12 -X utf8`**。
- 本机 3.12 通道已装：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2；Node v24.15.0 可用。
- `python -m tripwire` 需要 `src/` 在 `sys.path`：未 `pip install -e .` 时用 `PYTHONPATH=src`，或直接 `pip install -e .`（CI 走后者）。
- 测试里 `subprocess` 起 CLI 必须显式传 `PYTHONPATH`（`tests/test_skeleton.py` 已示范），否则本地未安装时子进程找不到包。
- Excel COM 仅 Windows；Linux CI 上 `excel_com_csv` 必须**显式跳过并标注**，不得当作"已验证"。

---

## 六、DoD 逐项 checklist（M0）

- [x] `plan/00`–`plan/06` + `data/README.md` 齐备且含必需小节
- [x] `AGENTS.md` 含方法论名 / 布局门命令 / 装订日期 / 强制布局清单
- [x] `plan/00` 顶部装订行（三锚点同现）
- [x] 布局门 9 条判据全绿，且**非空跑自证**（打印扫到的份数）
- [x] 门自身变异验证 17 组：14 组按预期红、3 组显式 SKIP（发布留档 M6 前不存在）、0 组未按预期；还原后复绿
- [x] 脱敏门 0 命中；4 组变异全红
- [x] `tripwire --version` / `--help` / `validate-pipeline` / `rules --count` / `selftest` 可运行
- [x] 未实现子命令 exit 3；`argparse` 参数错误也 exit 3（不冒充门禁失败）
- [x] `pytest -q` → 17 passed
- [x] `plan/HANDOFF-M0.md`（本节所在文件）七节齐
- [x] 4 处状态副本一致（M0 ✅ / M1–M6 ⬜）
- [ ] CI 首跑 —— **不适用本轮**（无远端）。写"CI 待首推验证"，不写"CI 绿"

---

## 七、关键命令速查

```bash
# 门
python tools/check_sprint_layout.py
python tools/check_desensitized.py
python tools/verify_gate_mutations.py      # 门自身的变异验证（14 组）

# 测试
python -m pytest -q

# CLI
PYTHONPATH=src python -m tripwire --version
PYTHONPATH=src python -m tripwire validate-pipeline pipelines/*.json
PYTHONPATH=src python -m tripwire rules --count
PYTHONPATH=src python -m tripwire selftest

# 安装（与 CI 同形态）
python -m pip install -e ".[dev]"
```

> 本机（Windows）把 `python` 换成 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。
