# HANDOFF-M6 → 完结（脱敏与发布：公开仓库 + tag + Release + 发布留档）

> **续接方式**（用户侧）：`/goal 读取 "plan/HANDOFF-M6.md" 继续完成任务`
> **第一动作（硬约束）**：先跑 `py -3.12 tools/check_sprint_layout.py`，绿了再动手；红了先修布局。
> 本棒 = **M6（脱敏与发布）**，已收尾。**M0–M6 全部 ✅，项目完结**。
> 后续若继续：**二期候选**（YAML/TOML/MessagePack 通道、LibreOffice 通道、真实大规模数据）不在首期承诺内。

---

## 一、当前进度（含证据）

| 项 | 状态 | 证据（可复跑） |
|---|---|---|
| 包名 / 仓库名核对（D5/Q1） | ✅ | PyPI `tripwire` 与 `tripwire-audit` 均 404；GitHub `yuluo554/10-21-tripwire` 404 → 可用 |
| 提交元数据邮箱 | ✅ | `git log --format='%ae %ce' --all \| sort -u` → **只剩 noreply 一个值**（无需改写历史） |
| 版本定版 | ✅ | `__version__ = "0.1.0"`（唯一来源）；金样本 `manifest.json`/`expected.json` 随 `generator_version` 重生成（`orig.csv` 逐字节不变） |
| CI 发布产物 job | ✅ | `.github/workflows/ci.yml` `release-artifacts`：tag 或手动触发，产 sdist+wheel+`SHA256SUMS` + 干净 venv 冒烟 + upload-artifact |
| README 输入可跑性 | ✅ | 原稿 `sample.csv`/`a.csv`/`b.csv` **仓库里从未存在**；改为 `fixtures/golden/orig.csv` + `runs/<run_id>/stage-<k>.csv` |
| README 契约守门 | ✅ | `tests/test_readme_contract.py`（4 条）；**3 组变异已验红**（不存在的管线路径 / 产物名连字符 / report 缺 `--expected`） |
| 干净 clone 逐条实测 | ✅ | 中立目录 `git clone --no-local --depth 1` + 全新 venv → README **14 条命令逐条退出码**（§RELEASE-M6 §1.3） |
| sdist 自足 | ✅ | 解包树（无 `.git`）两门全绿 + **211 passed** |
| wheel 中立 CWD | ✅ | 只装 wheel、仓库外跑 `run --expected`：首屏三段正确，exit 1 |
| 发布留档（tag 前落盘） | ✅ | `plan/RELEASE-M6.md` 两栏 + §三 阶段 7 覆盖对账（三态，24–25 行） |
| 发布留档门可证伪 | ✅ | 把 M6 临时翻 ✅ 后跑变异：**17 组全部按预期红，0 SKIP，0 未按预期** |
| 公开仓库 | ✅ | `https://github.com/yuluo554/10-21-tripwire`（公开） |
| CI 首跑（G-6） | ✅ | 3 个 run 全绿；四矩阵各 **192 passed / 19 skipped / 0 failed** |
| tag（G-7） | ✅ | `v0.1.0` **annotated**；远端 `git/refs/tags/v0.1.0` → `object.type = "tag"` |
| Release + 附件 | ✅ | `isDraft=false`；3 附件（sdist 238736 B / wheel 98142 B / `SHA256SUMS` 186 B） |
| 真下载复核 | ✅ | `gh release download` → `sha256sum -c` **两件均 OK** |
| 附件 vs tag 树 | ✅ | 共有 **79 文件 / 0 差异**；两侧独有 3 + 8（构建/入包元数据，预期不同构） |
| 从 tag 重建 | ✅ 内容级 | sdist 104 成员内容全等；wheel 成员内容全等。**字节级不等**（sdist 嵌 mtime）；wheel 在 `SOURCE_DATE_EPOCH` 固定下**字节可复现**（实测） |
| 脱敏门 | ✅ | 0 命中（86 份文本，豁免 2 份） |
| 布局门 | ✅ | 全绿（文档 10 / 交接单 7 / 状态副本 4 / 点名工具 3） |
| 门变异 | ✅ | 17 组：14 红 / 3 SKIP（M6 前形态）/ 0 未按预期 |

**发布 digest（CI 生成，本机不产）**：

```
531de2469dc1d81430c5dfee204c9a628a07b746908c22a85a50d51af7d4df9a  tripwire-0.1.0.tar.gz
e8a4b7a415ec2f314ec7aaff119e8767b3682306340a06a04b562822ac9403db  tripwire-0.1.0-py3-none-any.whl
```

**未发生的事（不许写成已完成）**：

- **没有做过 PyPI 发布**（Q5：首期只发 GitHub Release）。
- **没有跑过真实大规模数据**（首期只承诺 200 行合成样本）。
- **`excel_com_csv` 在 Linux/CI 上从未真跑**（COM 仅 Windows）；19 条相关测试在 CI 上声明式 skip。
- **sdist 字节级不可复现**（setuptools 嵌 mtime）；承诺的是**内容级同源 + 校验和可复核**。
- **LibreOffice / Google Sheets / WPS / YAML / TOML / MessagePack** 全部未实测（二期）。

---

## 二、当前事实·状态不变量（下一棒动手前必须知道）

M5 的 48 条仍然全部有效（见 `plan/HANDOFF-M5.md` §二），下面只列 **M6 新增/改动** 的：

49. **版本号 = `0.1.0`**（`src/tripwire/__init__.py`，唯一来源）。`pyproject` 走 `dynamic`，
    **tag 名 `v0.1.0` 与它对齐**。改版本 = 必须重打 tag（且属交付面改动 → 只能走新版本号，不许移动已发布 tag）。
50. **`fixtures/golden/` 与版本耦合**：`manifest.json` / `expected.json` 的 `generator_version`
    来自 `GENERATOR_VERSION = __version__`。**改版本必须重生成金样本**，否则
    `test_golden_manifest_sha256_matches` 与 `test_fixture.py` 的版本断言会红。
    重生成后 `orig.csv` 应**逐字节不变**（只有版本那两行变）——这是"生成器确定性"的免费复证。
51. **`SHA256SUMS` 只由 CI 产**（`.github/workflows/ci.yml` 的 `release-artifacts` job）。
    本机 `python -m build` 的产物**从不**上传；Release 附件必须来自 `gh run download` 的字节。
52. **`release-artifacts` 的触发条件**：`startsWith(github.ref, 'refs/tags/v')` 或 `workflow_dispatch`。
    分支 push 不产发布物（首推那次该 job 显示 skipped 是**正确**的，不是失败）。
53. **CI 的 `pytest -q` 与 `pyproject` 的 `addopts = "-q"` 叠加成 `-qq` → 摘要行不打印**。
    要数 passed/skipped，从日志里数进度行的 `.`/`s`/`F`（本棒实测：四矩阵各 192/19/0）。
54. **`selftest` 按 CWD 相对路径找 `pipelines/`**：装 wheel 后在仓库外跑会报「缺管线声明」。
    README「已知环境问题」已登记。**别为了消掉它把 selftest 改成包内找**——那会改变
    "随包声明与仓库声明一致"这条判据的语义（要改就单独立项，并补测试）。
55. **README 契约守门在 `tests/test_readme_contract.py`**：抽命令参数断言输入存在 / 产物名与
    setuptools 规范化一致 / `report` 示例带 `--expected` / 子命令真实存在。
    加新 README 命令时它可能误报——**判据是"用户要读的输入存在"，产出落点（`.tmp/`、`runs/`、`dist/`、`verify/`）已放行**。
56. **发布留档的自指约束**：`plan/RELEASE-M6.md` §一/§三 **进 tag 树**，所以**不许写** tag OID / commit sha /
    附件 sha256。字面值只在 §二（tag 后追加）与 Release 正文。**别"好心补上"§二的空值**——那会让值再次失效。
57. **发布留档变异的 SKIP 判据 = 里程碑状态**（`tools/verify_gate_mutations.py::_milestone_done`），
    **不是文件存在性**：`LAYOUT.RELEASE` 在发布里程碑未 ✅ 时早退为 True，而留档要求**先于 tag 落盘**
    ——按文件判据会把 V11–V13 永久 SKIP 掉（本棒实测踩到并修）。
58. **tag 之后只允许非交付面提交**（`plan/`、`README.md`、`tools/`、`tests/`）；
    `src/`、`rules.json`、`pipelines/`、`fixtures/` **零差异**。本棒 tag 后的提交只动了 `plan/` 与 `README.md`。
59. **Release 是"绑分支"形态**（`target_commitish = main`）：移动 tag **不会**打回 draft。
    但每次移动 tag 后仍应复验 `isDraft`——两种形态都真实存在，别套模板。
60. **状态副本仍是 4 处**（`plan/00` 里程碑表 / `plan/05` 状态表 / `README.md` 状态表 / `plan/00` 台账）：
    翻任一里程碑必须**同一提交**里改全 4 处。M6 已全翻 ✅。
61. **`plan/06` 缺口表已清空**（G-5/G-6/G-7 全关）。`LAYOUT.GAPS` 会扫这张表，
    新缺口要**只描述、不点名文件**（D15）。
62. **随包 README 的状态表是"开发里程碑快照"，不是发布状态**（表下已加注）。
    这解决了"tag 后只能改文档面"与"README 状态行转正"的冲突——发布状态以 Release 页为准。

---

## 三、下一棒待办（本项目已完结；以下为二期候选，**均未承诺**）

- [ ] 二期：YAML / TOML / MessagePack 数据通道（`plan/00` 弃选项 C3 的二期部分）
- [ ] 二期：LibreOffice / Google Sheets / WPS 通道（当前**未实测**，不得声称已验证）
- [ ] 二期：真实大规模数据表现（首期只承诺 200 行合成样本）
- [ ] 二期：sdist 字节级可复现（需 setuptools 侧支持固定 mtime，本版不承诺）
- [ ] 若发现已发布版本的缺陷：**不移动 tag**，走新版本号 + 追加提交（`plan/05` §五）

---

## 四、既定口径清单（K 编号，动了会打挂测试）

M5 的 K1–K11 与 D16–D20 全部仍然有效（见 `plan/HANDOFF-M5.md` §四）。

### M6 新增的口径

| 编号 | 约定 | 违反后果 |
|---|---|---|
| D21 | 版本号定版 = `__version__` 一处；**tag 名与之对齐**；改版本必须重生成金样本 | `test_golden_manifest_sha256_matches` / `test_version_matches_pyproject` 红 |
| D22 | `SHA256SUMS` 只由 CI 生成；Release 附件只用 `gh run download` 的字节 | 校验和不可复核（`plan/06` R7） |
| D23 | README 点名的输入必须是仓库真有的文件（产出落点除外） | `test_readme_path_args_exist_or_are_documented_placeholders` 红 |
| D24 | README 点名的产物名必须与 setuptools 规范化一致（下划线） | `test_readme_artifact_names_match_setuptools_normalization` 红 |
| D25 | 发布留档 §一/§三 在 tag 树内，**不写** tag OID / sha / 附件哈希 | 值写入即失效 → 需移动 tag 重发（纯浪费） |
| D26 | 承诺"内容级同源 + 校验和可复核"，**不承诺 sdist 字节级可复现** | 把"内容全等"写成"逐字节一致"= 虚高声明 |

---

## 五、本机环境坑（只写实测过的，2026-10-21）

M5 的十条仍然有效（见 `plan/HANDOFF-M5.md` §五）。M6 新增：

- **`gh` token scopes = `gist, read:org, repo`（无 `workflow`）**：`gh repo create --push` 带
  `.github/workflows/*` 会被拒。正解 = `gh repo create … --source . --remote origin`（**不带 `--push`**）
  → `git remote set-url origin git@github.com:<u>/<r>.git` → SSH push（**SSH 不受 OAuth scope 限制**，
  workflow 文件正常识别并触发 CI）。本棒实测一次成。
- **建仓输出 ≠ push 发生**：建仓命令末行打印仓库 URL 看着像全成，实际 push 是独立副作用。
  判据 = `gh api repos/<u>/<r>/commits/<branch> --jq .sha` 与本地 `git rev-parse HEAD` 相等。
- **tag push 会独立触发一轮 run**（`on: push` 未配 filters）：本棒 2 次 push → 2 次 run，如实记录。
- **`actions/upload-artifact@v4` + `if-no-files-found: error`**：产物没打出来会当场红，不会静默。
- **`sha256sum ./*` 会把输出文件自己收进去**：写成 `sha256sum *.tar.gz *.whl > SHA256SUMS`。
- **`--no-index` 装 wheel 会因 pandas/openpyxl 缺席失败**：CI 里应正常联网装依赖，别加 `--no-index`。
- **两次独立 CI 构建**：sdist **成员内容 104/104 全等**，但字节不同（gzip 头 mtime + tar 成员 mtime）；
  wheel 在 `SOURCE_DATE_EPOCH` 固定下**字节可复现**（本机两次 `cmp` 一致）。别把 sdist 字节级也承诺进去。
- **`rm -rf` 删不掉 `.tmp/` 里的目录（Device or resource busy）**：Windows 上有句柄残留；
  用 `py -3.12 -c "import shutil; shutil.rmtree(path, onerror=...)"` 带 chmod 兜底。
- **Git Bash 下 `cmd | head` 的 `$?` 是 `head` 的**：取真实退出码要单跑或 `${PIPESTATUS[0]}`。

---

## 六、DoD 逐项 checklist（M6）

- [x] 发布前核对包名与仓库名（D5/Q1）：PyPI `tripwire` 404、GitHub `yuluo554/10-21-tripwire` 404 → 可用
- [x] 提交元数据邮箱全为 noreply（无需历史重写）
- [x] `plan/RELEASE-M6.md` **在 tag 之前**写好并进 tag 树（§一 tag 前事实 / §二 tag 后追加 / §三 阶段 7 覆盖对账 三态）
- [x] `python -m build` 产 sdist + wheel（本机验证用）；**`SHA256SUMS` 只由 CI 生成**
- [x] 首次推远端 → CI 真跑（G-6）：3 run 全绿；四矩阵各 192/19/0；`excel_com_csv` skip 并标注
- [x] `v0.1.0` annotated tag（远端 `object.type=tag`）；Release 附 sdist + wheel + `SHA256SUMS`；正文登记 digest
- [x] tag 后只提交非交付面（`plan/`、`README.md`）；`src/`、`rules.json`、`pipelines/`、`fixtures/` 零差异
- [x] 复核：真下载 + 中立目录 + `sha256sum -c`（两件 OK）+ 附件 vs tag 树共有 79 文件 0 差异
- [x] 脱敏门 0 命中（86 份）；`plan/06` 关 G-6 / G-7
- [x] 收尾：`plan/HANDOFF-M6.md`（七节）+ 4 处状态副本翻 ✅
- [x] 布局门全绿 / 脱敏门 0 命中 / 变异 17 组按预期
- [x] 全量测试：dev 211 passed / 干净 clone 192+19skip / sdist 解包 211 passed
- [x] README 契约守门落地（4 条 + 3 组变异验红）

---

## 七、关键命令速查

```bash
# 门（第一动作）
py -3.12 tools/check_sprint_layout.py
py -3.12 tools/check_desensitized.py
py -3.12 tools/verify_gate_mutations.py

# 测试（要摘要就别叠加 -q：addopts 已是 -q）
py -3.12 -m pytest -o addopts="" -q
py -3.12 -m pytest -o addopts="" -q tests/test_readme_contract.py

# 发布物复核（真下载 + 校验和）
rm -rf .tmp/verify && mkdir -p .tmp/verify && cd .tmp/verify
gh release download v0.1.0 -D . && sha256sum -c SHA256SUMS

# 附件 vs tag 树（共有文件逐字节；不是 diff -r）
git archive v0.1.0 | tar -x -C .tmp/arch
tar -xzf .tmp/verify/tripwire-0.1.0.tar.gz -C .tmp/rebuild

# CI 状态
gh run list --limit 5
gh api repos/yuluo554/10-21-tripwire/actions/runs/<id>/jobs --jq '.jobs[] | "\(.name): \(.conclusion)"'
gh release view v0.1.0 --json isDraft,assets
```

> 本机（Windows）一律 `py -3.12 -X utf8`；`PYTHONPATH=src` 在 PowerShell 里写 `$env:PYTHONPATH="src"`。
