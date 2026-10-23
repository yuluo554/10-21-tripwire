# RELEASE-M6.1 · 发布物与代码同步（v0.1.1）

> **本文档在 tag 之前落盘并进 tag 树**（`plan/05` §五 第 1 条）。
> **自指约束**：§一/§三 **不写** tag OID、commit sha、附件 sha256 的字面值——写进去的那一刻就失效。
> 字面值写在 **§二（tag 后追加）**，那一栏由 tag 之后的独立提交产生，不改变 tag 树字节。
>
> **两栏分工**：§一 = 打 tag 那一刻可确证的事实；§二 = tag 之后才产生的事实（CI run、附件 digest、真下载复核）。
>
> **为什么有 M6.1**：`v0.1.0` 的 tag 打在做完定版的 `ff7e4e8` 上，之后 `9c5710f` 改了**交付面**
> （`pyproject.toml` 的 license 改 PEP 639 形态 + `setuptools>=77`）并新增 7 条守门测试。
> 已发布 wheel 的 `METADATA` 因此是**旧形态**（`License: MIT`，无 `License-Expression`），
> 且 sdist/wheel 里没有那个新测试文件。D1 的定性是「发布物落后于代码」，不是代码缺陷。

---

## 一、tag 前事实

### 1.1 交付面（tag 树的内容）

| 项 | 值 |
|---|---|
| 包名（PyPI / `pyproject`） | `tripwire` |
| 仓库 | `yuluo554/10-21-tripwire`（公开） |
| 版本 | **`0.1.1`**（唯一来源 `src/tripwire/__init__.py::__version__`，`pyproject` 走 `dynamic`） |
| tag | `v0.1.1`（annotated） |
| 产物口径 | **sdist + wheel + `SHA256SUMS`**（`plan/00` §六 DoD 口径 A，不降级） |
| `SHA256SUMS` 生成者 | **CI 的 `release-artifacts` job**（`plan/06` R7：本机不产校验和） |
| 许可证 | MIT，**SPDX 表达式形态**（`license = "MIT"` + `license-files = ["LICENSE"]`，PEP 639） |
| `requires-python` | **`>=3.10,<3.13`**（上界与 CI 矩阵对齐，D5） |

**与 v0.1.0 的交付面差异**（`git diff --name-only v0.1.0..v0.1.1` 的实质内容）：

| 文件 | 变化 | 为什么进 v0.1.1 |
|---|---|---|
| `pyproject.toml` | `license = {text="MIT"}` → `license = "MIT"` + `license-files`；`setuptools>=68` → `>=77`；`requires-python` 加 `<3.13` 上界 | PEP 639（旧 TOML 表形态 2027-02-18 后硬失败）+ D5 版本口径 |
| `src/tripwire/__init__.py` | `__version__` `0.1.0` → `0.1.1` | 版本单一来源 |
| `tests/test_license_metadata.py` | 新增（7 条）：SPDX 形态 + classifier 禁令 + setuptools 下限 + requires-python 下限 + 4 条审计函数负控 | 把 PEP 639 的连带约束变成机检 |
| `tests/test_python_version_matrix.py` | 新增（6 条）：`requires-python` 与 CI 矩阵双向一致 + 上界必须真跑过 + 3 条负控 | D5 的守门（否则下次又漂） |
| `tests/test_count_guard.py` | 新增（3 条）：收集数与本文档登记值对撞 + 两口径算术自洽 + 当前计数不许散落到别的 plan 文档 | 防自述计数漂移 |
| `tools/check_desensitized.py` | `SKIP_DIRS` 加 `update` | `update/` 是迭代交接物，必然记录本机路径；排除的是**目录**不是判据 |
| `fixtures/golden/expected.json`、`manifest.json` | `generator_version` `0.1.0` → `0.1.1`（`manifest` 另随 `files.expected.json` 自指 sha256 变一行）；**`orig.csv` 逐字节不变** | `GENERATOR_VERSION = __version__` 是硬耦合，抬版本必须重生成（`plan/04` §`manifest.json` 已写明） |
| `plan/02`、`plan/04`、`plan/05`、`plan/06`、`plan/00`、`plan/01`、`plan/HANDOFF-M6.md`、`plan/RELEASE-M6.md` | 状态回写 + 历史计数加时点标注 + M6.1 留档 + 金样本重生成纪律说明 | 非交付面，`plan/05` §五 第 5 条允许 |

> **`src/tripwire/**` 的判定引擎逻辑零改动**：只有 `__init__.py` 的版本号与两个新测试文件。
> 18 条归因规则、退出码语义、`fixtures/golden/orig.csv`（金样本输入字节）全部未动。
>
> **金样本重生成不是"动金样本"**：`orig.csv` 逐字节不变，改的只是 `generator_version` 这个**自指字段**；
> 且用的是仓内官方 `gen-fixture`（非手改），重生成后 README 首屏示例仍逐字一致
> （`VERDICT: LOSSY (45/1600 cells, 3 rules)` / `FIRST LOSS AT: stage 1 = json_sqlite_csv (SQLite 3.49.1)`
> / `GATE: recall 1.00 precision 1.00 unclassified 0`），判定能力未受影响。

### 1.2 定版提交前的实测（本机，2026-10-23 · **`v0.1.1` 时点快照**）

> **本节是全仓唯一登记"当前树测试计数"的地方。** 其他 `plan/` 文档只许给指针——
> `tests/test_count_guard.py` 会拦住"当前量级的数字散落到别处"，因为那种写法在下次加测试时必然漂移。

| 检查 | 命令 | 结果 |
|---|---|---|
| 收集数 | `py -3.12 -m pytest -o addopts="" --collect-only -q` | **227** |
| 全量测试（装 pywin32） | `pytest -o addopts="" -rs` | **227 passed / 0 skipped**（Excel COM 真机跑，约 150s） |
| 全量测试（无 pywin32） | 同上（该 venv 不装 pywin32） | **208 passed / 19 skipped**（19 = 全部 `excel_com_csv` 声明式跳过，`-rs` 逐条给原因） |
| 布局门 | `python tools/check_sprint_layout.py` | 全绿（文档 10 / 交接单 7 / 状态副本 4 / 点名工具 3） |
| 脱敏门 | `python tools/check_desensitized.py` | 0 命中（88 份文本，豁免 2 份） |
| 门变异 | `python tools/verify_gate_mutations.py` | **17 组：17 红 / 0 SKIP / 0 未按预期**，rc=0 |
| wheel 安装 | 全新 venv → `pip install <wheel>` | `--version` = `0.1.1`；`rules --count` = 18 |
| 中立 CWD 全链 | 只装 wheel，在仓库外跑 `run --expected` | 首屏三段正确，exit 1（LOSSY 45/1600） |

**计数口径的算术**（防"只记一个口径"）：

```
227 collected = 227 passed + 0 skipped      （装 pywin32：19 条 skip 转为真跑）
227 collected = 208 passed + 19 skipped     （无 pywin32）
227 − 208 = 19 = skipped 数                  ← 两档差值必须等于跳过数
```

**相对 `v0.1.0`（211 collected）的 +16 来自**：`test_license_metadata.py` 7（9c5710f，存量）+
`test_python_version_matrix.py` 6（本迭代 D5）+ `test_count_guard.py` 3（本迭代，防漂移）。

### 1.3 v0.1.0 → v0.1.1 的修订清单（D1 + 三处接线）

| # | 缺陷 | 定级 | 本迭代的处理 | 判据 |
|---|---|---|---|---|
| D1 | 发布物落后于代码：tag 后 `9c5710f` 改了交付面，已发布 wheel/sdist 不含 PEP 639 形态与新测试 | **P0** | 发 `v0.1.1`：版本、产物、tag、Release 全部重建 | §二 的 METADATA 行与 sdist 含新测试文件 |
| D2 | 测试计数：`plan/` 里的 211 / 192 与当前树不符 | P1 | **不改历史值**（它们是 `v0.1.0` tag 树实测真值），逐处加「v0.1.0 时点值」标注 + 指向本文 §1.2 | 解出 `git archive v0.1.0` 实测 211 collected（已验）；本文 §1.2 登记当前值 |
| D3 | 变异门不在 CI：`plan/00` 与 5 份 HANDOFF 把它当方法论硬证据，但 CI 只跑两道门 | P1 | 加进 `methodology gates` job；`AGENTS.md` 门清单从 2 条补到 3 条 | CI 有 `verify_gate_mutations` step；干净 venv（只装 pip）跑它 17/17 rc=0 |
| D4 | actions 全是 node20（`checkout@v4` / `setup-python@v5` / `upload-artifact@v4`），注解里飘 Node20 弃用警告 | P1 | 三个全部升 **v7**（node24） | 推送后 Node20 注解计数 = 0 |
| D5 | `requires-python = ">=3.10"` 开区间，CI 只跑 3.10/3.12 ⇒ 3.11 未跑、3.13+ 声明支持但未验 | P1 | 收紧成 **`>=3.10,<3.13`**；新增 `tests/test_python_version_matrix.py` 双向守门 | 声明与矩阵一致；负控：改回开区间立刻红（已验） |
| — | 脱敏门把 `update/`（迭代交接物，必然含本机路径）判红 ⇒ 变异门连带跑不了 | 阻塞 | `SKIP_DIRS` 加 `update`（与 `.tmp`/`runs`/`build` 同族；排除**目录**不是判据） | 脱敏门 rc=0；D1–D4 变异组仍全红（判据未削弱） |

### 1.4 本迭代**没有**做的事（如实登记）

| 项 | 为什么不 |
|---|---|
| 重切 `v0.1.0` | 本仓纪律是"要改就重切并把原因写进 §二"，但这里只是发布物落后——发新版比改写已发布 tag 干净（DEC-1 甲案） |
| 改判定引擎 / 18 条归因规则 / 退出码语义 | D1 是发布面同步问题，不是代码缺陷（`plan/05` §五） |
| 动 `fixtures/golden/**` | 金样本字节被 sha256 登记，`.gitattributes` 明写"git 不许碰" |
| 把 `excel_com_csv` 的 19 条 skip 改成"永远 skip" | 那是把真实覆盖藏起来（本迭代纪律 §四 第 1 条明令禁止） |
| 减少变异组 / 删 `test_license_metadata.py` 来让 D1"消失" | 同上：那正是把发布物落后藏起来 |
| 加 3.11 的 CI 腿 | DEC-4 选了乙案（收紧上界），不是甲案（加格）；`>=3.10,<3.13` 与 3.10/3.12 两端一致即成立 |
| 发 PyPI | `plan/06` D5 已核对：PyPI `tripwire` 与 `tripwire-audit` 均 404，本项目**不发 PyPI**，只发 GitHub Release |

---

## 二、tag 后追加（本栏由 tag 之后的独立提交写入）

> 本节在 `v0.1.1` 的 tag / Release / CI 真跑完成后回填（2026-10-23）。**无预测值。**
> 本节的提交**不属于 tag 树**，所以可以写 sha256 / OID 这类一进包就失效的字面值。

### 2.1 tag 与 Release

| 项 | 值 |
|---|---|
| tag | `v0.1.1`（annotated；远端 `refs/tags/v0.1.1` 的 `object.type = "tag"`） |
| tag 对象 OID | `39d14e9bf0e8c8e26cfbf2ca49f1776cc870d3d5` |
| tag 指向的 commit | `df7e51238afdb6c36bdb2bce7a0378bbe2e4b200` |
| Release | `isDraft=false` / `isPrerelease=false`；`--latest`（`/releases/latest` → `tag_name = v0.1.1`） |
| 附件 | `tripwire-0.1.1.tar.gz` 259,560 B ／ `tripwire-0.1.1-py3-none-any.whl` 98,278 B ／ `SHA256SUMS` 186 B |

### 2.2 附件 digest（CI 生成，本机不产）

CI `release-artifacts` job 的产物摘要（本机 `python -m build` 的字节**从未上传**）：

```
ffad108e71dcc653e8eb54257674f748d7b0737a19d26260c5572e6253bea572  tripwire-0.1.1.tar.gz
2776b9b6bfc1c52efc8b5925364586b1e40bb61d3eff90513b6d7a9c1eab0b95  tripwire-0.1.1-py3-none-any.whl
f47d55fdeffa3742afb6509f750de80777fcbfcb75a7ce41fc618cb1a87bb9f4  SHA256SUMS
```

**三方一致**：匿名下载件复算 ／ `SHA256SUMS` 内容 ／ GitHub `assets[].digest` 逐条相同。

### 2.3 CI run

| run | 事件 | 结论 |
|---|---|---|
| 39907408169 | `push main` | ✅ success（6 job：`methodology gates` + 4× `tests` + `release-artifacts` skipped） |
| 39907461058 | `push v0.1.1`（tag） | ✅ success（6 job 全 success，含 `build release artifacts`） |

**Node20 弃用注解 = 0 条**（6 job 的 `check-runs/*/annotations` 全扫）。余下注解只有
`ubuntu-latest` 将迁 Ubuntu 26 的 notice——**非本迭代可消**，「四矩阵全绿」当前仍指 Ubuntu 24.04 镜像。

### 2.4 发布物复核（匿名通道）

| 步 | 命令 | 结果 |
|---|---|---|
| 匿名可达 | `curl -s -L -H "Accept: application/octet-stream" <asset api url>` | HTTP 200；3 件 259,560 / 98,278 / 186 B |
| METADATA 形态 | `unzip -p <wheel> tripwire-0.1.1.dist-info/METADATA \| head -6` | ✅ `Version: 0.1.1` + **`License-Expression: MIT`** + `License-File: LICENSE`（PEP 639 形态） |
| sdist 含新测试 | `tar tzf <sdist> \| grep test_license_metadata` | ✅ 有输出（`tripwire-0.1.1/tests/test_license_metadata.py`） |
| 真下载 + 校验和 | 匿名下载 3 件 → `sha256sum -c SHA256SUMS` | ✅ 两件 `OK` |
| 真装 + 真跑 | 全新 py3.12 venv 装匿名下载的 wheel → 中立 CWD | ✅ `tripwire --version` = `tripwire 0.1.1`；`rules --count` = 18 |
| sdist 解包树自足 | 解包 → `pytest -o addopts=""` | ✅ 206 passed / 21 skipped（227 collected；多出 2 条 skip = `ci.yml` 被 `prune .github` 排除，判据显式跳过并写明原因） |

> ⚠ **本机网络限制（如实登记）**：`github.com` 主机与 `releases/download/...` 的 CDN 重定向
> 在本机（直连，以及经开发机上常见的本机回环 HTTP 代理）**均超时**；
> 而 `api.github.com` 与 `objects.githubusercontent.com` 可达。
> 故匿名验收走 **API 资产通道**（`api.github.com/.../releases/assets/<id>` + `Accept: application/octet-stream`，
> **不带任何 token**）——它同样匿名且不做 token 校验，结论等价。`gh release download` 的常规通道未在此机复跑。

### 2.5 tag 之后的提交（如实登记：`tests/` 一条，交付面零差异）

tag 指向 `df7e512`（13:43:50）。之后落了两条提交，**均非交付面**：

| commit | 时间 | 改动 | 定性 |
|---|---|---|---|
| `4c8d9fd` | 13:53:06 | `tests/test_count_guard.py`（嵌套 pytest 加 `-p no:cacheprovider` + 临时 `cache_dir`） | **非交付面**（`plan/05` §五 第 5 条明文允许 tag 后提交 `plan/`、`README.md`、`tools/`、`tests/`） |
| `a0ea795` | 13:55:27 | `plan/RELEASE-M6.1.md`（即本节） | 非交付面（本节自身） |

**交付面零差异**（`plan/05` §五 第 5 条的硬判据，实测）：

```
git diff --name-only v0.1.1..HEAD | grep -E "^(src/|rules.json|pipelines/|fixtures/)"
→ 零输出（src / rules.json / pipelines / fixtures 全未动）
git diff --name-only v0.1.1..HEAD   →  plan/RELEASE-M6.1.md、tests/test_count_guard.py 两件
```

⇒ **tag 合规，不重切**。`4c8d9fd` 是 test-only 的确定性改进（去掉缓存争用），
不进 wheel（wheel 不含 `tests/`），进 sdist 但因上面这条纪律**不影响发布物契约**。

⚠ **该提交对「flake」的定性未被我复现**（如实登记）：在已发布 sdist 的 bundled
`test_count_guard.py`（= 无该 fix 的版本）上，串行 x15、以及「外层 + 嵌套同 rootdir 并发」x25，
**0 次失败**。故「约 1/45 间歇」是**外部会话在同一 rootdir 下大规模并发**时的观测，
本机稳态下复现不出。它的改动是**纯收益**（缓存与收集数无关），故保留。


---

## 三、阶段 7 覆盖对账

> 逐条给出口门一个归宿，三态不许留空：**实现**（贴命令+输出）/ **不适用**（写具体理由）/ **待首推**（如实标注）。

| 出口门 | 状态 | 证据 / 不适用理由 |
|---|---|---|
| 发布物与代码同步（D1 的正面判据） | 实现 | §1.1 差异表；§1.3 D1 行；§2.4 的 METADATA 与 sdist 两条判据 |
| 发布物本体已验（匿名通道） | 实现 | §2.4：匿名 API 资产通道下载 3 件 → `sha256sum -c` OK → 全新 venv 真装 → 中立 CWD `--version`/`rules --count` |
| 入仓工具在无 `.git` 树里能跑 | 实现 | §1.2：解包树两门 + 全量 pytest（`tools/` 与 `tests/` 都在 sdist 白名单里） |
| 构建排在交付面定稿之后 | 实现 | 顺序 = 版本/文档/新测试定稿 → 全量测试（两档）→ 三门 → build → 装态验证 → tag |
| 版本号单一来源由机器断言 | 实现 | `tests/test_skeleton.py::test_version_matches_pyproject`（`dynamic = ["version"]`）+ `test_readme_contract.py` 断言产物名带版本 |
| 留档第三栏自指约束（不写 tag OID / sha / 包哈希） | 实现 | 本文顶部自指约束；§二 用自填形态，tag 后才写 |
| 附件口径不降级 | 实现 | 口径 = **sdist + wheel + `SHA256SUMS`**（§1.1）；`SHA256SUMS` 只由 CI 产（R7） |
| 附件 sha256 只写不动点 | 实现 | §一 不写任何哈希；§2.2 与 Release 正文登记 digest |
| 计数差异逐项归因 | 实现 | §1.2 算术三行（两档 + 差值等于跳过数）；`tests/test_count_guard.py` 把这三行变成机检 |
| 门自身可证伪（方法论装订硬约束③） | 实现 | §1.2 变异行 17/17 / 0 SKIP；CI 常驻（D3）；`AGENTS.md` 已列三门 |
| 声明与验证范围一致（D5） | 实现 | `requires-python = ">=3.10,<3.13"` × CI `["3.10","3.12"]`；`tests/test_python_version_matrix.py` 双向守门 + 3 条负控已验红 |
| CI 无 Node20 注解（D4） | 实现 | §2.3：6 job 的 `check-runs/*/annotations` 全扫，`Node.js 20 is deprecated` 计数 = **0**（余下仅 `ubuntu-latest`→Ubuntu 26 的 notice） |
| 未把 FAIL 降级成 WARN / 未减判据 | 实现 | §1.4：三道门的判据未动；19 条 Excel COM skip 保持原样；变异 17 组未减；`test_license_metadata.py` 保留 |
| 已发布 tag 未被改写 | 实现 | `v0.1.0` 的 tag 对象与指向 commit 全程未动（§1.4 第 1 行） |
| 发 PyPI | 不适用 | `plan/06` D5：PyPI 同名 404，本项目只发 GitHub Release |
