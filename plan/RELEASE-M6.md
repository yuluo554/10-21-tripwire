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

### 1.2 定版提交前的实测（本机，2026-10-21 · **`v0.1.0` 时点快照**）

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

> **本节数字是 `v0.1.0` 定版时点的真值，不是当前树的真值。**（2026-10-23 复核追加）
> 解出 tag 树实测：`git archive v0.1.0 | tar -x` → `pytest --collect-only -q` = **211 tests collected**，
> 树内**没有** `tests/test_license_metadata.py`。所以 211 / 192+19 在本节是对的，改成 218 反而会假。
> 当前树（`main` @ 9c5710f 之后）的实测计数**只登记在 `plan/RELEASE-M6.1.md` §1.2 一处**
> （散落多处必然在下次加测试时漂移，本仓已有自指守门 `tests/test_count_guard.py` 拦这件事）。
> 差值来源 = 9c5710f 新增的 `tests/test_license_metadata.py`（**7 条**：211+7=218、192+7=199，这是算术，不是实测值）。
> 同一份快照的另一处旁证：本节布局门写「交接单 **6**」——第 7 份是 tag 之后 `df8d7da` 才加的 `HANDOFF-M6.md`。
> v0.1.1 的定版真值记在 `plan/RELEASE-M6.1.md` §1.2。

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
| CI 实跑 | ✅ 已跑（首推即绿；见 §2.3） |

---

## 二、tag 后追加事实

> **本栏由 tag 之后的独立提交写入**（不改变 tag 树字节）。tag OID、commit sha、附件 sha256 只写在这里或 Release 正文。

### 2.1 tag 与 Release

| 项 | 值 |
|---|---|
| tag | `v0.1.0`（**annotated**；远端 `git/refs/tags/v0.1.0` 的 `object.type = "tag"`） |
| tag 对象 OID | `c7ca8277ffea4dc6c52ff11ff9776df6d9f3c28f` |
| tag 指向的 commit | `ff7e4e800ca2288e2bb0416865cc4b96b767189f`（"M6 发布留档（tag 前落盘）…"） |
| 远端主分支 tip | 同上（tag 与 `main` 在打 tag 时同一提交） |
| Release | `v0.1.0`，`isDraft=false`、`isPrerelease=false`；`target_commitish=main`（**绑分支形态**——移动 tag 不会打回 draft） |
| 附件 | `tripwire-0.1.0.tar.gz`（238736 B）/ `tripwire-0.1.0-py3-none-any.whl`（98142 B）/ `SHA256SUMS`（186 B） |
| 仓库 | `https://github.com/yuluo554/10-21-tripwire`（公开） |

### 2.2 附件 digest（CI 生成，本机不产）

```
531de2469dc1d81430c5dfee204c9a628a07b746908c22a85a50d51af7d4df9a  tripwire-0.1.0.tar.gz
e8a4b7a415ec2f314ec7aaff119e8767b3682306340a06a04b562822ac9403db  tripwire-0.1.0-py3-none-any.whl
```

> **口径**：`SHA256SUMS` 只由 CI 的 `release-artifacts` job 生成（`plan/06` R7）；本机 build 的产物**从不**上传。

### 2.3 CI 首跑（G-6 关闭）

| run | 事件 | 结论 |
|---|---|---|
| 39528824668 | `push main`（首推） | **5 job 全绿**；`release-artifacts` 按设计 skip（分支 push 不产发布物） |
| 39529248748 | `push v0.1.0`（tag） | **6 job 全绿**，含 `build release artifacts` |
| 39529702552 | `workflow_dispatch` | 全绿（用于"两次独立 CI 构建"的内容对账） |

- **四矩阵一致**：ubuntu/windows × Python 3.10/3.12 —— 每个矩阵 **192 passed / 19 skipped / 0 failed**（总计 211 项收集）。
  （v0.1.0 tag 时点真值；当时树内无 `tests/test_license_metadata.py`。v0.1.1 起的收集数与两档计数见
  `plan/RELEASE-M6.1.md` §1.2 —— 不在本文写当前值，避免下次加测试时又漂。）
- **19 条 skip 逐条可指认**：全部是 `excel_com_csv` 的声明式跳过（COM 仅 Windows，CI runner 无 Excel），`-rs` 每条带原因。
- **首推即绿**：预留的"诊断+修复+再推"预算**未动用**（开发期前置工程到位：`eol=lf` / extras 装齐 / 平台无关写法）。
- **push 数 = run 数**：2 次 push（main + tag）→ 2 次 run；tag push 因 `on: push` 未配 filters 而独立触发一轮（如实记录）。
- **镜像口径**：`ubuntu-latest` / `windows-latest` 都是**浮动标签**，具体镜像版本随 GitHub 侧迁移而变，
  本留档不给镜像版本号（给了就会在下次迁移时变成假话）。已知信号：ubuntu-latest **2026-10-19 起迁 Ubuntu 26**，
  CI 注解里会出现 notice；v0.1.0 的三个 run 都建立在该迁移窗口附近，结论是绿的（见上表 run id 可复查）。
  需要"钉死镜像"的场合另说（本仓未钉，`runs-on` 用的就是浮动标签）。

### 2.4 发布物复核（G-7 关闭）

| 步 | 命令 | 结果 |
|---|---|---|
| 真下载 | `gh release download v0.1.0 -D verify/` | ✅ 三件（sdist / wheel / `SHA256SUMS`） |
| 校验和 | `cd verify && sha256sum -c SHA256SUMS` | ✅ 两件均 `OK`（exit 0） |
| 下载件 → 中立目录安装 | 全新 venv + `pip install tripwire-0.1.0-py3-none-any.whl` | ✅ `--version` = `0.1.0`；`rules --count` = 18；`run --expected` 首屏三段正确、exit 1 |
| 附件 vs tag 树（**共有文件**逐字节） | sdist 解包树 ∩ `git archive v0.1.0` 解包树 | ✅ **共有 79 个文件，0 个不同** |
| 两侧独有集合逐项点名 | — | `git archive` 独有 3：`.gitattributes` / `.gitignore` / `.github/workflows/ci.yml`；sdist 独有 8：`PKG-INFO` / `setup.cfg` / `src/tripwire.egg-info/*`（6 个）—— 均为构建/入包元数据，**预期不同构** |
| 从 tag 重建（内容级） | `git archive v0.1.0 \| tar -x` → `python -m build` → 与下载件比**成员内容** | ✅ sdist 104 个成员**内容全等**；wheel 成员内容全等 |
| 从 tag 重建（字节级） | `cmp` | ⚠️ **不等**：gzip 头 mtime + tar 成员 mtime 随构建时刻变（sdist）；wheel 在 `SOURCE_DATE_EPOCH` 固定时**可字节复现**（实测两次构建 `cmp` 一致） |

> **字节级复现的边界（如实登记，不夸大）**：setuptools 的 **sdist 嵌入文件 mtime**，即使设 `SOURCE_DATE_EPOCH`
> 仍两次构建不同；**wheel 在 `SOURCE_DATE_EPOCH` 固定下字节可复现**（本机实测）。两次独立 CI 构建的
> sdist 成员**内容** 104/104 全等、仅 mtime 不同。所以本项目承诺的是
> **"内容级同源 + 校验和可复核"**，**不承诺 sdist 字节级可复现**——后者需要 setuptools 侧支持，不在本版范围。

### 2.5 tag 后追加的文档提交（tag 树外）

| 提交主题 | 内容 | 是否触碰交付面 |
|---|---|---|
| M6 收尾 | 4 处状态副本翻 ✅、`plan/06` 关 G-6/G-7、`plan/HANDOFF-M6.md`、本节回填 | ❌ 只动 `plan/`、`README.md`（**README 一处「已知环境问题」补行**，见下） |

> **README 的一处补行**（`selftest` 在仓库外报「缺管线声明」）来自真下载复核时的实测发现：
> 装 wheel 后在仓库外跑 `selftest` 会因 `pipelines/` 按 CWD 相对路径找而失败。
> 这是**文档缺口**（README 未说明该前提），已补进「已知环境问题」表。
> 按 `plan/05` §五 第 5 条，`README.md` 属允许的非交付面；`src/`、`rules.json`、`pipelines/`、`fixtures/` **零差异**。

### 2.6 脱敏门的扫描面差异（逐项归因，防"双绿但悄悄少扫"）

| 环境 | 扫到的文本文件 | 差异归因 |
|---|---|---|
| 开发机工作树 | 87 | 含本地 `pip install -e .` 产生的 `src/tripwire.egg-info/`（6 份：`PKG-INFO` / `SOURCES.txt` / `dependency_links.txt` / `entry_points.txt` / `requires.txt` / `top_level.txt`） |
| 公开仓库全新 clone | 81 | 87 − 6 = 81；`*.egg-info/` 在 `.gitignore`，**不入库**，故 clone 里没有 |

> 两侧都是 **0 命中**，但"扫了 81 份"与"扫了 87 份"不是同一个证明。差值已逐项指认到构建残留，
> **不是**门少扫了交付面文件。判别 = "这条绿的扫描面里，到底有几个文件？"——数得出来才算证据。

### 2.7 公开仓库全新 clone 复核（最终形态）

| 检查 | 命令 | 结果 |
|---|---|---|
| clone | `git clone --depth 1 https://github.com/yuluo554/10-21-tripwire.git` | ✅ |
| 布局门 | `python tools/check_sprint_layout.py` | ✅ 全绿（交接单 7 / 状态副本 4） |
| 脱敏门 | `python tools/check_desensitized.py` | ✅ 0 命中（81 份，见 §2.6） |
| 全量测试 | 全新 venv + `pip install -e ".[dev]"` → `pytest` | ✅ **192 passed / 19 skipped**（与 CI 四矩阵一致；v0.1.0 tag 时点值，当前树值见 `plan/RELEASE-M6.1.md` §1.2） |

---

## 三、阶段 7 覆盖对账

> 逐条给出口门一个归宿，三态不许留空：**实现**（贴命令+输出）/ **不适用**（写具体理由）/ **待首推**（无远端期间如实标注）。
> **本表在 tag 树内版本里 `待首推` 项 = 发布动作尚未发生**；tag 之后的提交把它逐条改为实测结论（本节现为改后版本）。

| 出口门 | 状态 | 证据 / 不适用理由 |
|---|---|---|
| 发布物本体已验（真下载 + 中立目录） | 实现 | §2.4：`gh release download` → `sha256sum -c` 两件 OK → 全新 venv 装 wheel → 中立 CWD 跑 `run --expected` 首屏三段正确 |
| 入仓工具在无 `.git` 树里能跑 | 实现 | sdist 解包树（无 `.git`）跑布局门 + 脱敏门 + 全量 pytest 全绿：§1.2 |
| 发布包实测：README 每条命令在解包树真敲 | 实现 | §1.3 十四条逐条退出码；干净 clone + 全新 venv，非 0 码均为明示语义 |
| README 前置条件单列成节 | 实现 | `README.md`「安装」三行前置（venv / `python -m pip` 而非 `py`）+「已知环境问题」表 |
| 留档第三栏自指约束（不写 tag OID / sha / 包哈希） | 实现 | 本文顶部自指约束；§二 用自指表述「含本记录完整内容的那个提交」 |
| 附件与 tag 树逐字节同源（共有文件比对 + 两侧独有集合点名） | 实现 | §2.4：共有 **79 文件 / 0 差异**；两侧独有集合逐项点名（3 + 8，全是构建/入包元数据）。**字节级**复现的边界见 §2.4 末尾（sdist 嵌 mtime，wheel 在 `SOURCE_DATE_EPOCH` 下可字节复现） |
| 源码包自足（`MANIFEST.in` 白名单） | 实现 | `MANIFEST.in` 白名单 + 解包树两门全绿 + 211 passed（v0.1.0 时点；当前树值见 `plan/RELEASE-M6.1.md` §1.2）：§1.2 |
| 构建排在交付面定稿之后 | 实现 | 顺序 = 版本/夹具/README 定稿 → 全量测试 → build → 双装态验证 → tag |
| README 提到的附件名真在 Release 里 | 实现 | `tests/test_readme_contract.py::test_readme_artifact_names_match_setuptools_normalization`（下划线形态；变异已验红） |
| 对外样例产物在中立示意目录生成 | 不适用 | 本项目不发布样例报告产物；`runs/` 是运行产物且被 gitignore，附件只有 sdist/wheel |
| 附件口径四选一 + 留档写明 | 实现 | 口径 = **sdist + wheel + `SHA256SUMS`**（§1.1）；`SHA256SUMS` 只由 CI 产（R7） |
| 附件 sha256 只写不动点（Release 正文 / tag 后追加） | 实现 | §一（进 tag 树的那半）不写任何哈希；§2.2 与 Release 正文登记 digest |
| 版本号四处一致由机器断言 | 实现 | 单一来源 `__init__.__version__` + `pyproject` dynamic；`tests/test_skeleton.py::test_version_matches_pyproject` + `test_readme_contract.py` 断言产物名带版本 |
| 随包 README 状态行不承载发布状态 | 实现 | README 状态表加注「本表记录开发里程碑，不是发布状态；发布状态以 Release 页为准」 |
| DoD 打勾只在事实落地后 | 实现 | §一 全部有实测行；§二 在 tag 后才回填（tag 树内那版 §二 是待回填骨架） |
| 脱敏四步 + 产物本体扫描 | 实现 | §1.4 五步；产物扫描 39 成员 0 命中 |
| CI 首跑（G-6） | 实现 | §2.3：3 个 run 全绿；四矩阵各 192 passed / 19 skipped / 0 failed（v0.1.0 时点）；skip 逐条指认到 Excel COM 声明式跳过 |
| tag + Release + 附件（G-7） | 实现 | §2.1：annotated tag（远端 `object.type=tag`）+ Release `isDraft=false` + 3 附件；§2.4 真下载复核通过 |
| 计数差异逐项归因（dev vs 干净环境 vs CI） | 实现 | dev 211 / 干净 clone 192+19skip / sdist 解包 211 / 公开仓库 clone 192+19skip（**全为 v0.1.0 时点值**）；19 条 skip 逐条指认到 Excel COM 声明式跳过；**脱敏门扫描面 87 vs 81 的差值也逐项归因**（§2.6）。v0.1.1 起的计数与差值来源见 §1.2 后记 |
| 零网络声明可核验 | 实现 | `tests/test_report.py::test_no_network_imports`（AST 扫包内全部 .py）；wheel 产物扫描 0 网络客户端 |
| 缓议项清零 | 实现 | `plan/06` §五 Q1–Q5 全部「保持」，无悬空项 |
