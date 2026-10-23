# AGENTS.md

本仓库遵循 **`ai-tool-project-sprint`** 方法论（装订日期：2026-10-21）。

## 任何新对话的第一件事

```bash
python tools/check_sprint_layout.py    # 布局门；必须绿，红了先修布局再干活
python tools/check_desensitized.py     # 脱敏门；发布前必须 0 命中
python tools/verify_gate_mutations.py  # 变异门；前两道门的判据自己可证伪（17 组必须全红、0 SKIP）
```

- 续接对话：读 `plan/HANDOFF-M<k>.md`（第 k 棒的收尾交接单），**先跑上面三条门**。
- 接手对话（无 HANDOFF）：先读 `plan/00`、`plan/05`、`plan/06` 与各 HANDOFF，重建"当前状态 + K 口径清单"再动手。
- **门不存在 = 本项目没装订** → 先补第零步三件（`AGENTS.md` + 布局门 + `plan/00` 顶部装订行），再做别的。

## 强制布局（布局门逐条断言，改动前先看这里）

| 项 | 位置 | 判据 |
| --- | --- | --- |
| 计划套件 | `plan/00`–`plan/06` + `data/README.md` | 存在且各含必需小节（标题关键词） |
| 数据台账 | `data/README.md` | 依据查证记录 + 数值口径两节在位 |
| 交接单 | `plan/HANDOFF-M<k>.md` | 每个 ✅ 里程碑一份（含收尾棒），**七节**齐（含"当前事实·状态不变量"） |
| 里程碑状态副本 | `plan/00` 里程碑表 + `plan/05` 状态表 + `README.md` 状态表 + `plan/00` 承诺-证据台账 | **逐处一致**，枚举式断言 |
| 缺口表 | `plan/06` §四 | 不得再提已 ✅ 的里程碑（只描述、不点名文件） |
| 发布留档 | `plan/RELEASE-M6.md`（两栏 + 覆盖对账）或 `plan/WRAPUP-M6.md` | 发布里程碑 ✅ 后必须存在 |
| 文档点名的工具 | 任何 `tools/*.py` 形式的引用 | `git ls-files` 指得到实物 |
| 门自身可证伪 | `tools/verify_gate_mutations.py`（17 组） | 布局门 13 组 + 脱敏门 4 组，**全红且 0 未按预期**；CI 常驻（methodology gates job） |

## 环境事实与禁忌

- 本机实测（2026-10-21）：`py -0p` 有 **3.8.8** 与 **3.12.10** 两条通道；`python` 是商店占位符，一律用 `py -3.12`。Node v24.15.0 可用。
- 本机已装：pandas 3.0.6 / openpyxl 3.1.5 / pytest 8.4.2（均在 3.12 通道）。Excel COM 仅 Windows。
- 命令行一律 `py -3.12 -X utf8`；临时文件用仓库内相对路径（Git Bash `/tmp` 与 Windows Python 不通）。
- 禁止：把"未执行"写成已完成；在 tag 之后改交付面（`src/`、`rules.json`、`pipelines/`、`fixtures/`）。

## 关键命令

| 用途 | 命令 |
| --- | --- |
| 布局门 | `py -3.12 tools/check_sprint_layout.py` |
| 脱敏门 | `py -3.12 tools/check_desensitized.py` |
| 变异门 | `py -3.12 tools/verify_gate_mutations.py` |
| 测试 | `py -3.12 -m pytest -q` |
| CLI 冒烟 | `py -3.12 -m tripwire --version` |
| 管线声明校验 | `py -3.12 -m tripwire validate-pipeline pipelines/pandas.json` |
