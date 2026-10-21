# RELEASE-M6 · 脱敏与发布

> **本文档在 tag 之前落盘并进 tag 树**（`plan/05` §五 第 1 条）。
> **自指约束**：本文档随 tag 树一起被发布，所以 §一/§三 **不写** tag OID、commit sha、附件 sha256 的字面值——
> 写进去的那一刻就失效（`git tag -f` 会变、包字节会变）。字面值写在 **§二（tag 后追加）**，
> 那一栏由 tag 之后的独立提交产生，不改变 tag 树字节。
>
> **两栏分工**：§一 = 打 tag 那一刻可确证的事实；§二 = tag 之后才产生的事实（CI run、附件 digest、真下载复核）。

---

## 一、tag 前事实

### 1.1 交付面（tag 树的内容）

| 项 | 值 |
|---|---|
| 包名（PyPI / `pyproject`） | `tripwire` |
| 仓库 | `yuluo554/10-21-tripwire`（公开） |
| 版本 | `0.1.0`（唯一来源 `src/tripwire/__init__.py::__version__`，`pyproject` 走 `dynamic`） |
| tag | `v0.1.0`（annotated） |
| 产物口径 | **sdist + wheel + `SHA256SUMS`**（`plan/00` §六 DoD 口径 A，自首提交起不降级） |
| `SHA256SUMS` 生成者 | **CI 的 `release-artifacts` job**（`plan/06` R7：本机不产校验和） |
| 许可证 | MIT |

### 1.2 定版提交前的实测（本机，2026-10-21）

| 检查 | 命令 | 结果 |
|---|---|---|
| 布局门 | `py -3.12 tools/check_sprint_layout.py` | 全绿（文档 10 / 交接单 6 / 状态副本 4 / 点名工具 3） |
| 脱敏门 | `py -3.12 tools/check_desensitized.py` | 0 命中（85 份文本，豁免 2 份） |
| 门变异 | `py -3.12 tools/verify_gate_mutations.py` | 17 组：14 红 / 3 SKIP（M6 前不适用）/ 0 未按预期 |
| 全量测试（dev 树） | `py -3.12 -m pytest -o addopts="" -q` | **211 passed**（含 Excel COM 真机） |
| 全量测试（干净 clone） | 中立目录 + 全新 venv + `pip install -e ".[dev]"` | **192 passed / 19 skipped**（19 = 全部 Excel COM 声明式跳过，逐条 `-rs` 可指认） |
| 全量测试（sdist 解包树） | 解包 → `py -3.12 -m pytest` | **211 passed** |
| sdist 自足 | 解包树里跑两条门 | 布局门全绿 / 脱敏门 0 命中 |
| wheel 安装 | 全新 venv → `pip install <wheel>` | `--version` = `0.1.0`；`rules --count` = 18（包内 `rules.json` 可读）；`report` 在 `--help` 里 |
| 中立 CWD 全链 | 只装 wheel，在仓库外跑 `run --expected` | 首屏三段正确，exit 1（LOSSY 45/1600） |

### 1.3 README 逐条实测（干净 clone + 全新 venv，2026-10-21）

> 判据 = "README 的每条命令在一个从没装过东西的解释器上还成立吗"。**非 0 退出码只要符合明示语义就是 ✅**。

| # | 命令 | 退出码 | 判定 |
|---|---|---|---|
| 1 | `tripwire --version` | 0 | ✅ 输出 `tripwire 0.1.0` |
| 2 | `tripwire validate-pipeline pipelines/pandas.json` | 0 | ✅ `PASS name=pandas stages=[pandas_csv]` |
| 3 | `tripwire run … --key id`（无 `--expected`） | 3 | ✅ **明示语义**：不产出判定，NOTE 说清怎么补真值（D19） |
| 4 | `tripwire diff --key id` | 3 | ✅ 明示语义：差异算出（45 条）但不判定（D18） |
| 5 | `tripwire diff --align position` | 3 | ✅ 同上（45 条，按位置） |
| 6 | `tripwire diff --key id --batch 100` | 3 | ✅ 同上（含 dtype 漂移面） |
| 7 | `tripwire attribute --explain` | 3 | ✅ 明示语义：归因 45/3 rules/0 unclassified，不判定 |
| 8 | `tripwire attribute --fail-on unclassified` | 3 | ✅ 同上（unclassified=0，未触发 2） |
| 9 | `tripwire selftest` | 0 | ✅ `version=0.1.0 rules=18 pipelines=4`；`excel_com_csv` 显式 `UNAVAILABLE` |
| 10 | `tripwire gen-fixture --seed 42 --rows 200 --out-dir .tmp/golden` | 0 | ✅ 132 cells / 三池 60+80+60 |
| 11 | `tripwire run --pipeline pipelines/excel_com.json` | 3 | ✅ 明示语义：本机 venv 未装 pywin32 → `阶段不可用`，**不回落 openpyxl**（K3） |
| 12 | `tripwire gate --expected …` | 1 | ✅ 明示语义：LOSSY + `recall 1.00 precision 1.00 unclassified 0` |
| 13 | `tripwire run --expected …`（全链） | 1 | ✅ 首屏三段 + 报告三件落 `runs/<run_id>/` |
| 14 | `tripwire report --format md,json,sarif` | 1 | ✅ 三格式同源（json/sarif fingerprint 集合相等，45 = 45） |

**README 输入可跑性**：原稿的 `sample.csv` / `a.csv` / `b.csv` 在仓库里**从未存在过**（只在开发机 CWD 残留过），
定版改为仓库真有的 `fixtures/golden/orig.csv` 与 `runs/<run_id>/stage-<k>.csv`。
守门 = `tests/test_readme_contract.py`（抽命令参数断言存在；3 组变异已验红）。

### 1.4 脱敏四步

| 步 | 动作 | 结果 |
|---|---|---|
| 1 | 跟踪文件清单扫描（`.env` / `.key` / `secret` / `token` 命名） | 0 命中 |
| 2 | 内容级扫描（盘符路径 / 用户名 / 回环代理） | `tools/check_desensitized.py` 0 命中（85 份） |
| 3 | 二进制样例 | 仓库内无二进制样例（`fixtures/golden/` 全是 CSV/JSON 文本） |
| 4 | 历史重写 | **不需要**：11 个提交、无远端、历史即工作树；`git log --format='%ae %ce' --all \| sort -u` **只剩 noreply 一个值** |
| 附加 | 产物本体扫描 | wheel 39 个成员逐个扫（盘符 / 用户名 / 代理 / 个人邮箱）→ **0 命中** |

### 1.5 与 `plan/05` §四「已知未验证项」的对应

| 项 | 本轮状态 |
|---|---|
| `excel_com_csv` 在 Linux CI | ⬜ 不适用（COM 仅 Windows）；CI 上显式 skip 并标注，`-rs` 逐条可见 |
| LibreOffice / Sheets / WPS | ⬜ 未实测（二期） |
| YAML / TOML / MessagePack | ⬜ 二期 |
| 真实大规模数据 | ⬜ 未测（首期只承诺 200 行合成样本） |
| CI 实跑 | **待首推**（§二 回填） |

---

## 二、tag 后追加事实

> **本栏由 tag 之后的独立提交写入**（不改变 tag 树字节）。tag OID、commit sha、附件 sha256 只写在这里或 Release 正文。

### 2.1 tag 与 Release

| 项 | 值 |
|---|---|
| tag | `v0.1.0`（annotated） |
| tag 指向 | **含本记录完整内容的那个提交**（自指表述，不用绝对值：`git rev-list -n1 v0.1.0` 与 `git rev-parse HEAD` 相等即可核对） |
| Release | `v0.1.0`，附件 = sdist + wheel + `SHA256SUMS` |
| Release 正文 | 登记 digest（一行一个） |

### 2.2 CI 首跑（G-6）

| 项 | 值 |
|---|---|
| 首推 run | 待回填（`gh run list --limit 5`） |
| 四矩阵 | ubuntu/windows × 3.10/3.12 —— 待回填 |
| `release-artifacts` job | tag 触发 —— 待回填 |
| skip 数 | 待回填（windows 上 `excel_com_csv` 若 Excel 缺席亦 skip） |

### 2.3 发布物复核（G-7）

| 步 | 命令 | 结果 |
|---|---|---|
| 真下载 | `gh release download v0.1.0 -D verify/` | 待回填 |
| 校验和 | `cd verify && sha256sum -c SHA256SUMS` | 待回填 |
| 附件 vs tag 树 | sdist 解包树 ∩ `git archive v0.1.0` 解包树的**共有文件**逐个 sha256 相等；两侧独有集合逐项点名 | 待回填 |
| 从 tag 重建 | `git archive v0.1.0 \| tar -x` → `python -m build` → 与下载件 `cmp` | 待回填 |

> **`diff -r` 是错判据**：sdist 独有 `PKG-INFO` / `*.egg-info` / `setup.cfg`，`git archive` 独有
> `.gitignore` / `.gitattributes` / `.github/`——两棵树**结构上不同构**，零差异永不可能。

---

## 三、阶段 7 覆盖对账

> 逐条给出口门一个归宿，三态不许留空：**实现**（贴命令+输出）/ **不适用**（写具体理由）/ **待首推**（无远端期间如实标注）。

| 出口门 | 状态 | 证据 / 不适用理由 |
|---|---|---|
| 发布物本体已验（真下载 + 中立目录） | 待首推 | 无远端期间无法真下载；本地等价 = §1.2「中立 CWD 全链」+ §2.3 待回填 |
| 入仓工具在无 `.git` 树里能跑 | 实现 | sdist 解包树（无 `.git`）跑布局门 + 脱敏门 + 全量 pytest 全绿：§1.2 |
| 发布包实测：README 每条命令在解包树真敲 | 实现 | §1.3 十四条逐条退出码；干净 clone + 全新 venv，非 0 码均为明示语义 |
| README 前置条件单列成节 | 实现 | `README.md`「安装」三行前置（venv / `python -m pip` 而非 `py`）+「已知环境问题」表 |
| 留档第三栏自指约束（不写 tag OID / sha / 包哈希） | 实现 | 本文顶部自指约束；§二 用自指表述「含本记录完整内容的那个提交」 |
| 附件与 tag 树逐字节同源（共有文件比对 + 两侧独有集合点名） | 待首推 | §2.3；判据已按「不同构」写成共有文件比对，不是 `diff -r` |
| 源码包自足（`MANIFEST.in` 白名单） | 实现 | `MANIFEST.in` 白名单 + 解包树两门全绿 + 211 passed：§1.2 |
| 构建排在交付面定稿之后 | 实现 | 顺序 = 版本/夹具/README 定稿 → 全量测试 → build → 双装态验证 → tag |
| README 提到的附件名真在 Release 里 | 实现 | `tests/test_readme_contract.py::test_readme_artifact_names_match_setuptools_normalization`（下划线形态；变异已验红） |
| 对外样例产物在中立示意目录生成 | 不适用 | 本项目不发布样例报告产物；`runs/` 是运行产物且被 gitignore，附件只有 sdist/wheel |
| 附件口径四选一 + 留档写明 | 实现 | 口径 = **sdist + wheel + `SHA256SUMS`**（§1.1）；`SHA256SUMS` 只由 CI 产（R7） |
| 附件 sha256 只写不动点（Release 正文 / tag 后追加） | 实现 | 本文 §一 不写哈希；§二 与 Release 正文登记（待回填） |
| 版本号四处一致由机器断言 | 实现 | 单一来源 `__init__.__version__` + `pyproject` dynamic；`tests/test_skeleton.py::test_version_matches_pyproject` + `test_readme_contract.py` 断言产物名带版本 |
| 随包 README 状态行不承载发布状态 | 实现 | README 状态表加注「本表记录开发里程碑，不是发布状态；发布状态以 Release 页为准」 |
| DoD 打勾只在事实落地后 | 实现 | 本文 §一 DoD 项全部有实测行；§二 待回填项保持「待回填」不预填 |
| 脱敏四步 + 产物本体扫描 | 实现 | §1.4 五步；产物扫描 39 成员 0 命中 |
| CI 首跑（G-6） | 待首推 | 无远端期间一切 CI 结论只能写「本地等价校验」；§2.2 回填 |
| tag + Release + 附件（G-7） | 待首推 | §2.1 / §2.3 回填 |
| 计数差异逐项归因（dev vs 干净环境 vs CI） | 实现 | dev 211 / 干净 clone 192+19skip / sdist 解包 211；19 条 skip 逐条指认到 Excel COM 声明式跳过 |
| 零网络声明可核验 | 实现 | `tests/test_report.py::test_no_network_imports`（AST 扫包内全部 .py）；wheel 产物扫描 0 网络客户端 |
| 缓议项清零 | 实现 | `plan/06` §五 Q1–Q5 全部「保持」，无悬空项 |
