# tripwire

**结构化数据往返保真审计器** —— 一份数据经过 CSV → Excel → JSON → SQLite 转一圈，哪些值悄悄变了？

`tripwire` 给**逐单元格差异 + 归因规则名 + 证据 + 出问题的环节**。

```
VERDICT: LOSSY (9/14 cells, 5 rules)
FIRST LOSS AT: stage 1 = excel_com_csv (Excel 16.0 Build 20326)
GATE: recall 1.00 precision 1.00 unclassified 0
```

> 前三行是 `tripwire report` / `run --expected` 的实际首屏（数值随本次运行变；上例是原型 14 单元格样本）。
> `stage <k>` 是**输出阶段序号**：`stage-1` 是第一份输出（`stage-0` 是输入副本）。

现有工具要么只做两文件单元格差异但不解释原因（qsv diff / csvdiff / daff），要么只做单文件体检但不做往返对照（pandera / Great Expectations / Soda / frictionless）。`tripwire` 把"差异、归因、环节"三件事钉在同一条可复现管线上，并把 `unclassified` 当作一等公民。

## 状态

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 计划与方法论装订 + 可运行骨架 | ✅ |
| M1 | 往返管线执行器 + 逐段快照 | ✅ |
| M2 | 单元格级差异引擎 | ✅ |
| M3 | 归因规则引擎（18 条） | ✅ |
| M4 | 真值夹具生成器 + 门禁 | ✅ |
| M5 | 报告与 CI 出口 | ✅ |
| M6 | 脱敏与发布 | ⬜ |

> **本表记录的是开发里程碑**（随包快照，反映的是定版那一刻的状态），**不是发布状态**。
> "这一版是否已发布 / CI 是否绿"以 **Release 页**为准——随包文档不该是发布状态的第一手来源。
> 版本号：`tripwire 0.1.0`（唯一来源 `src/tripwire/__init__.py::__version__`）。

> 首期五模块已全部接线。可用子命令：`--help` / `--version` / `validate-pipeline` / `rules --count` /
> `selftest` / `run`（可带 `--expected` 一路判到报告）/ `diff` / `attribute` /
> `gen-fixture` / `gate` / **`report`（MD / JSON / SARIF 三格式 + 首屏三段）**。
>
> **0/1/2 只出自"真算过门禁"的出口**：`run --expected` / `report` / `gate`。`run`（不给 `--expected`）、
> `diff`、`attribute` 拿不到 recall / precision，一律走用法通道 3 并**明说"不产出有损/无损判定"**
> ——跑通 ≠ 判为无损。

## 安装

```bash
python -m venv .venv
# 激活：Windows `.venv\Scripts\activate` / POSIX `source .venv/bin/activate`
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

> **用 `python` 而不是 `py`**：Windows 的 `py` 启动器会无视已激活的 venv，把包装到系统解释器里。

`excel_com_csv` 通道还需要 Windows + 本机装好的 Excel + `pip install "tripwire[windows]"`；
其余三条通道（`pandas_csv` / `openpyxl_csv` / `json_sqlite_csv`）跨平台可用。

## 快速开始

> 下面的命令都假定 CWD = 仓库根（`pip install -e .` 之后 `tripwire` 才在 PATH 上）。
> 输入一律用**仓库里真有的文件**：`fixtures/golden/orig.csv`（seed 42 / 200 行合成金样本）。
> 没有自带输入的命令会先把样本生成到 `.tmp/`（已 gitignore），用完即删。

```bash
tripwire --version
tripwire validate-pipeline pipelines/pandas.json

# 跑一条往返管线，落 runs/<run_id>/stage-<k>.csv + stages.json
tripwire run --pipeline pipelines/json_sqlite.json \
    --input fixtures/golden/orig.csv --key id

# 对往返前后的两份快照做单元格级差异（默认按主键对齐；无 --key 拒绝运行）
tripwire diff --orig runs/<run_id>/stage-0.csv --got runs/<run_id>/stage-1.csv --key id
tripwire diff --orig runs/<run_id>/stage-0.csv --got runs/<run_id>/stage-1.csv \
    --align position    # 显式按位置（插行会连带误报）
tripwire diff --orig runs/<run_id>/stage-0.csv --got runs/<run_id>/stage-1.csv \
    --key id --batch 100    # 另报 dtype 漂移

# 给一次 run 的差异打上规则名与环节（--explain 逐条打印判定过程）
tripwire attribute --run-id <run_id> --key id --explain
tripwire attribute --run-id <run_id> --key id --fail-on unclassified   # 有未归因即 exit 2

# 四条通道各自的损失形态不同（Excel 与 openpyxl 是两个不同阶段）
tripwire selftest        # 同时报告本机四条通道是否可用

# 真值夹具（三组样本池）+ 门禁判定
tripwire gen-fixture --seed 42 --rows 200 --out-dir .tmp/golden   # 金样本；也可只生成某一池
tripwire run --pipeline pipelines/excel_com.json \
    --input fixtures/golden/orig.csv --key id
tripwire gate --run-id <run_id> --expected fixtures/golden/expected.json --key id
#   0 无损 / 1 有损 / 2 门禁失败

# 一条命令判到底：跑管线 → 差异 → 归因 → 门禁 → 三格式报告（首屏就是判定三段）
tripwire run --pipeline pipelines/json_sqlite.json \
    --input fixtures/golden/orig.csv --key id \
    --expected fixtures/golden/expected.json
# 对已有 run 重算并出报告（--expected 必填：没有真值就没有 recall/precision）
tripwire report --run-id <run_id> --expected fixtures/golden/expected.json \
    --key id --format md,json,sarif
```

`report` / `run --expected` 的 stdout 前三行就是判定本身，可以直接被 CI 抓：

```
VERDICT: LOSSY (45/1600 cells, 3 rules)
FIRST LOSS AT: stage 1 = json_sqlite_csv (SQLite 3.49.1)
GATE: recall 1.00 precision 1.00 unclassified 0
```

产物落在同一个 run 目录里：`runs/<run_id>/report.md`（人读）、`report.json`（机读）、
`report.sarif`（CI 注解：`ruleId` = 规则名、`partialFingerprints.primaryLocationLineHash` = `fingerprint`、
`artifactLocation.uri` = `stage-<k>.csv`）。三份来自**同一个内存结果**，finding 集合按 `fingerprint` 恒等。
形状与"什么情况不产出报告"见 `docs/report-schema.md`。

## 退出码

| 码 | 语义 |
|---|---|
| 0 | 无损（无差异且门禁通过） |
| 1 | 有损（存在差异，门禁通过） |
| 2 | 门禁失败（recall / precision / unclassified 任一不满足） |
| 3 | 用法错误 / 拒绝运行（未声明主键、管线声明非法、缺依赖） |

判定通道 = 0/1/2；用法通道 = 3。**3 不计入"有损/无损"判定。**
**只有真算过门禁的出口才给 0/1/2**：`run --expected` / `report --expected` / `gate --expected`
——没有真值就没有 recall/precision，宁可拒绝判定（3）也不报 0/1。

## 报告

`report` / `run --expected` 产三份**同源**报告：

| 文件 | 给谁看 | 关键内容 |
|---|---|---|
| `report.md` | 人 | 首屏三段 + 结论 + 逐条归因（含 `fingerprint`）+ 结构差异 + 逐段快照 + 边界 |
| `report.json` | 机 | `RunResult.to_json()`：`findings` / `gate` / `counts` / `first_screen` |
| `report.sarif` | CI 注解 | SARIF 2.1.0：`ruleId` = 规则名、`partialFingerprints.primaryLocationLineHash` = `fingerprint`、`artifactLocation.uri` = `stage-<k>.csv` |

三份来自**同一个内存结果**（先算一次再渲染三次），finding 集合按 `fingerprint` 恒等。
报告**不含时间戳、不含绝对路径**：同一输入在不同机器 / 不同 `run_id` 下可逐字节对账。
形状、"什么情况不产出报告"与"无损必然是空跑通过"这条推论见 `docs/report-schema.md`。

## 边界与承诺

- **归因上限是"环节"，不是"代码行"。** 工具能证明"值在哪一步变成这样"，不能证明"是 openpyxl 的 `%.16g` 那一行"。
- **纯本地、零网络**（含零遥测、零版本检查）；报告不含时间戳、不含绝对路径。
- **只读输入、只写 `runs/`**，不自动修复、不写回源文件。
- **无主键时拒绝运行**（exit 3）；**没有真值时拒绝判定**（exit 3），不做"智能猜测对齐"。
- `excel_com_csv` 与 `openpyxl_csv` 是**两个不同阶段**，报告只写实际跑的那个，绝不混称 "Excel"。
- 夹具全部为**合成数据**，不含真实个人或商户数据；报告不构成对常规数据损失率的承诺。

首期范围：四通道（CSV / XLSX / JSON / SQLite）、五模块、18 条规则。YAML / TOML / MessagePack 与 LibreOffice 通道为二期。

## 开发

```bash
python tools/check_sprint_layout.py     # 布局门（方法论装订）
python tools/check_desensitized.py      # 脱敏门（发布前 0 命中）
python -m pytest -q
```

计划文档见 `plan/`，口径真相源见 `data/README.md`，方法论锚点见 `AGENTS.md`。

## 已知环境问题

| 现象 | 原因 | 规避 |
|---|---|---|
| `excel_com_csv` 报 `UNAVAILABLE`（exit 3） | COM 只在 Windows 有；Linux/macOS 天然没有 | 用 `openpyxl_csv`（**不同阶段名**，报告不会写成 "Excel"）；CI 上该阶段显式 skip 并标注 |
| `py -m pip install` 装完仍找不到 `tripwire` | Windows `py` 启动器无视 venv | venv 里一律用 `python -m pip` |
| 报告里的 `Excel 16.0 Build 20326` 只在本机出现 | Build 号由 COM 读数决定 | 这是**运行时指纹**不是固定值；别的机器读到的就是那台机器的号 |
| 装 wheel 后 `runs/` 落在 CWD | `--out-dir` 默认 `runs/` | 显式给 `--out-dir` |

## 从 Release 复验

发布附件由 CI 在 tag 上构建（`dist/` 三件：sdist、wheel、`SHA256SUMS`）。
**产物名由 setuptools 规范化**，是下划线形态（`tripwire-0.1.0.tar.gz` / `tripwire-0.1.0-py3-none-any.whl`），
不是包名里的任何连字符写法——按文件名找，别按包名推。

```bash
gh release download v0.1.0 --pattern "*" -D verify/
cd verify && sha256sum -c SHA256SUMS
```

校验和的字面值登记在 `plan/RELEASE-M6.md` 与 Release 正文（**由 CI 生成，本机不产**）。

## 许可

MIT
