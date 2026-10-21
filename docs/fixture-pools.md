# 样本池构造纪律（三组样本池怎么造、为什么这么造）

> 生成器的接口与 schema 在 `src/tripwire/fixtures.py`；真值与门禁的**数值口径**唯一来源是
> `data/README.md` §6.2（门禁三数）。本文是**构造纪律**的人类可读副本，只解释"为什么这么造"，
> 不复述第二份数值。金样本 = `fixtures/golden/`（`--seed 42 --rows 200` 的生成留档）。

---

## 一、三组样本池各管什么

| 池 | id 前缀 | 行数（seed 42 / rows 200） | 管什么 |
|---|---|---|---|
| `canary-numeric` | `num-` | 60 | 数值族规则的**正例** |
| `canary-semantic` | `sem-` | 80 | 空值 / 文本 / 时间族的**正例与负样本** |
| `control-lossless` | `ctl-` | 60 | **0 差异**（precision 硬约束，D4） |

三组混在**同一张表**里（`plan/04` §二），一条管线就能同时测三类；`id` 前缀区分。行数比例是
生成器常量（`POOL_SHARE`），`--rows` 按比例缩放，和恰为 `--rows`（最大余数法，确定性）。

---

## 二、表是**稠密**的（每行每列都有值）

这一条不是排版偏好，是**正确性前提**。

pandas 的 dtype 推断是**按列**的：只要某列出现空格（NaN），整列就落成 `float64`，
于是控制行的 `94016` 被写成 `94016.0`——**一条假差异**，precision 一开跑就失败。
M4 实测过这个形态：稀疏表（金丝雀行只填自己那一列）跑 `pandas_csv` 得到 **59 条**
控制组差异，precision 当场掉到 0.85。

所以每行先铺满 `FILLER`（`fixtures.py` 的常量表）：

- `num_big` 列因为混着 20 位整数，恒为 `object`，填充值原样保留（控制组要的就是这个）；
- `zip` 列的填充必须是**整数形**——列里只要有一个非数字文本，整列就落 `object`，
  `02114` 的前导零就不会被剥，**规则 1 的正例当场消失**。

判别口诀：**"这一列的 dtype，是我决定的还是被某个空格决定的？"**

---

## 三、控制组为什么必须零差异

控制组是 D4 的守门组：它防的是"为了让 `unclassified` 归零而放宽规则导致的误报"。

它的零差异**不是**在 `gate.py` 里另判一条，而是 precision 的**推论**：控制行不在
`expected.json` 的 `cells` 里，所以它们一旦上报差异就是 `unexpected` → precision < 1。

控制组的取值（`CONTROL_SLOTS`）是逐列挑选的"无前导零、无小数尾零、无日期形态、无空白异常"
的纯 ASCII 字母数字，且**每行轮转换成**——一组固定值容易被某条规则恰好放过，
轮转能覆盖更多"看起来像"的组合。M4 实测：60 行控制组在四条通道上都是 **0 差异**。

---

## 四、生成器的确定性（K8）

- 随机只来自**自研 splitmix64**（`fixtures.py` 内 `SplitMix64`）：纯 64 位整数运算，
  跨版本 / 跨平台序列一致。**不用** stdlib `random`（它只承诺对当前版本稳定）；
- **不读时钟、不依赖 `set` 迭代序**；取样与打乱都走固定的索引顺序；
- 落盘：UTF-8 无 BOM、LF 行尾（`csv.writer(lineterminator="\n")`，且走 `write_text_raw`
  逐字节写——`orig.csv` 是**被审计的对象**，任何归一都会让"换行被改"这类差异测不出来）；
- `expected.json` / `manifest.json` 走 `serialization.write_json`（排序键 + LF + 结尾换行）。

**两层守门**（方法论"位级一致"条）：

1. **冻结产物形态**：`fixtures/golden/` 内部自洽——`manifest.json` 的 sha256 与两个文件复算一致、
   `expected.json` 不含 `observed_*` / `actual_*`、`cells` 的 `rule` 都在 `rules.json` 里；
2. **重跑生成器到临时目录 → 与冻结产物逐字节 `cmp`**。

只做第 1 层是**假门**：被测对象是生成器，断言读的却是它上次的产出——生成器改坏了测试照常绿。

---

## 五、真值不可与引擎同源（M4 实测校准）

### 5.1 期望值由输入独立推导

`expected.json` 的每条只存 `{cell, orig, rule, p_after}`：**输入与期望**。`p_after` 由
`fixtures.py::_after()` 按 `data/README` 的**文档化行为**（F1 15 位 / F4 无 -0 / F5 `%.16g` /
F6 null 塌缩 / F13 Excel 重写）从 `orig` 文本自行推导，函数体里**不出现任何阶段调用**。

判别 = **"把阶段实现全注释掉，真值还推得出来吗？"**——推不出来就说明期望与引擎同源，
那种基准在引擎坏掉时也不变色。配套：`tests/test_fixture.py` 用 AST 扫描 `fixtures.py`，
禁止它 import 任何 `pipeline.stages` / pandas。

**刻意重复实现**：`fixtures.py::round_significant` 与 `rules/predicates.py::round_significant`
是两份独立实现。它们看起来一样，但**不能"顺手统一"成一个 import**——统一后生成侧就变成
"用被测实现生成期望"，规则 5 算错与真值算错会一起错、一起绿。

### 5.2 合法形态的判据：**变了的通道集合 ⊆ 该规则的 `possible_stages`**

这是 M4 最关键的一条实测发现。

`rules.json` 里每条规则带 `possible_stages`（候选通道）；归因引擎（D1）会把
"观察到变化的阶段不在候选里"的差异**降级成 `unclassified`**。于是：

> 一个样本形态可以入库，**当且仅当**它在四条通道上"真的变了"的通道集合，
> 是它期望规则的 `possible_stages` 的子集。

否则门禁必失败，而且失败点会伪装成"规则没命中"。`rules.json` 已冻结（M4 不得增删规则、
不得改 `possible_stages`），所以**只能靠挑样本**。

M4 实测出来的几个越界形态（都在 `docs/rules.md` §六 里登记为已知缺口）：

| 形态 | 期望规则 | 越界的通道 | 为什么 |
|---|---|---|---|
| 16 位**以上**整数（> 2^53） | `int53_overflow`（候选不含 openpyxl） | `openpyxl_csv` | openpyxl 写进 xlsx 按 double 读回，也变了 |
| 15 位**以下**整数被 Excel 渲染成科学计数 | `scientific_notation_coercion` | `json_sqlite_csv` | SQLite 的 `.15g` 也会写科学计数 |
| 任意"其实未被任何通道改动"的数 | 各数值规则 | 全部 | 不加区分，不能当任何规则的正例 |

**反例优先于正例**：能靠"挑形态"救回来的就救，救不回来的（见 §六）**如实登记**，
不塞进样本池冒充覆盖。

### 5.3 一处必须靠字面量形态区分的边界

`decimal_trailing_zero_dropped` 的候选**不含** `openpyxl_csv`，但 openpyxl 的写入侧按
`stages/common.cell_kind` 决定"写数字还是写文本"：`19.90` 是数字形 → 写数字 → xlsx 里
按 double 读回 → 也变成 `19.9` → **越界**。

修法不是改谓词，而是**改字面量**：`19.90 `（**带一个尾随空格**）→ `cell_kind` 判成 `text`
→ openpyxl 原样保留 → 只有 pandas / SQLite / Excel 三条动它 → 恰好落在候选集里。

判别口诀：**"这条通道会不会动它，是形态的性质还是字面量的性质？"**

---

## 六、`uncovered_rules`：没有正例的规则**点名**，不假装覆盖

`expected.json` 的 `uncovered_rules` 列出"在本 seed 的样本里没有正例"的规则。M4 的 seed 42
金样本点名 8 条：

| 规则 | 为什么本 seed 无正例 | 状态 |
|---|---|---|
| `float_precision_truncated` | 候选不含 `excel_com_csv`，而四条通道里 Excel 真的会改这类定点小数 → 越界 | 需改 `possible_stages` 或改形态（**不在 M4 授权内**） |
| `null_token_collision` | 只要它命中，`id` 更小的 `empty_vs_null_vs_missing` 必先命中 → 被遮蔽 | 结构性 |
| `whitespace_collapsed` | 候选不含 `json_sqlite_csv` / `excel_com_csv`，而这两条都会裁空白 → 越界 | 需改 `possible_stages`（不在 M4 授权内） |
| `unicode_normalization_changed` | 四条 CSV 通道都不做 Unicode 归一 | 需专门的读取路径 |
| `bom_prepended` | 四条通道都不在原值前加 BOM | 需专门的写入路径 |
| `encoding_mojibake` | 四条通道都按 UTF-8 原样读写，不产生乱码 | 需非 UTF-8 路径 |
| `date_system_shift_1904` | 需要 1904 纪元切换的 Excel 实例 | 靠单测构造（M3 已做） |
| `number_format_dropped` | 四条 CSV 通道都不产出单元格级 `number_format` | 二期 xlsx 读回通道 |

**这些是事实，不是欠债**：它们精确指出了"现有 18 条规则 / 四条通道"覆盖不到的地方。
`docs/rules.md` §六 的覆盖表据此回填。补齐它们要么改 `rules.json` 的候选集（M4 无授权），
要么加新通道（二期），要么靠单测构造（#16 已做）。

---

## 七、部分运行不写全集清单（`plan/04` §五.5）

`gen-fixture --pool numeric` 这类**局部入口**只写 `orig.csv`，**不写** `expected.json` /
`manifest.json`。

为什么：入仓的全集清单只该由**全集生成**写出。否则一次调试用的局部生成会把入仓的清单
**静默改小**，而当场全绿、退出码 0——真正的红灯要等另一次核对才亮，红点离真因隔了一棒。

`tests/test_fixture.py` 有一条专门的"部分运行不写清单"测试钉住这条。

---

## 八、一条命令能做什么

```bash
# 金样本（入仓形态）：seed 42 / 200 行
py -3.12 -m tripwire gen-fixture --seed 42 --rows 200 --out-dir fixtures/golden

# 局部生成（调试用，不写清单）
py -3.12 -m tripwire gen-fixture --seed 42 --rows 60 --out-dir .tmp/partial --pool numeric

# 跑一条通道 → 判门禁（0 无损 / 1 有损 / 2 门禁失败 / 3 用法错误）
py -3.12 -m tripwire run --pipeline pipelines/excel_com.json --input fixtures/golden/orig.csv --key id
py -3.12 -m tripwire gate --run-id <run_id> --expected fixtures/golden/expected.json --key id
```