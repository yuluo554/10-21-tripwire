# tripwire

**结构化数据往返保真审计器** —— 一份数据经过 CSV → Excel → JSON → SQLite 转一圈，哪些值悄悄变了？

`tripwire` 给**逐单元格差异 + 归因规则名 + 证据 + 出问题的环节**。

```
VERDICT: LOSSY (9/14 cells, 5 rules)
FIRST LOSS AT: stage 2 = excel_com_csv (Excel 16.0 Build 20326)
GATE: recall 1.00 precision 1.00 unclassified 0
```

现有工具要么只做两文件单元格差异但不解释原因（qsv diff / csvdiff / daff），要么只做单文件体检但不做往返对照（pandera / Great Expectations / Soda / frictionless）。`tripwire` 把"差异、归因、环节"三件事钉在同一条可复现管线上，并把 `unclassified` 当作一等公民。

## 状态

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 计划与方法论装订 + 可运行骨架 | ✅ |
| M1 | 往返管线执行器 + 逐段快照 | ⬜ |
| M2 | 单元格级差异引擎 | ⬜ |
| M3 | 归因规则引擎（18 条） | ⬜ |
| M4 | 真值夹具生成器 + 门禁 | ⬜ |
| M5 | 报告与 CI 出口 | ⬜ |
| M6 | 脱敏与发布 | ⬜ |

> 开发中。当前可用：`--help` / `--version` / `validate-pipeline` / `rules --count`；其余子命令返回退出码 3（用法通道）。

## 安装

```bash
python -m pip install -e ".[dev]"
```

## 快速开始

```bash
tripwire --version
tripwire validate-pipeline pipelines/pandas.json
```

## 退出码

| 码 | 语义 |
|---|---|
| 0 | 无损（无差异且门禁通过） |
| 1 | 有损（存在差异，门禁通过） |
| 2 | 门禁失败（recall / precision / unclassified 任一不满足） |
| 3 | 用法错误 / 拒绝运行（未声明主键、管线声明非法、缺依赖） |

判定通道 = 0/1/2；用法通道 = 3。**3 不计入"有损/无损"判定。**

## 边界与承诺

- **归因上限是"环节"，不是"代码行"。** 工具能证明"值在 stage 2 变成这样"，不能证明"是 openpyxl 的 `%.16g` 那一行"。
- **纯本地、零网络**（含零遥测、零版本检查）。
- **只读输入、只写 `runs/`**，不自动修复、不写回源文件。
- **无主键时拒绝运行**（exit 3），不做"智能猜测对齐"。
- `excel_com_csv` 与 `openpyxl_csv` 是**两个不同阶段**，报告只写实际跑的那个，绝不混称 "Excel"。
- 夹具全部为**合成数据**，不含真实个人或商户数据。

首期范围：四通道（CSV / XLSX / JSON / SQLite）、五模块、18 条规则。YAML / TOML / MessagePack 与 LibreOffice 通道为二期。

## 开发

```bash
python tools/check_sprint_layout.py     # 布局门（方法论装订）
python tools/check_desensitized.py      # 脱敏门（发布前 0 命中）
python -m pytest -q
```

计划文档见 `plan/`，口径真相源见 `data/README.md`，方法论锚点见 `AGENTS.md`。

## 许可

MIT
