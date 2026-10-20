# 差异记录格式（`tripwire diff`）

> 本文只描述**记录形状与对齐语义**。数值口径（退出码、`fingerprint` 构造）的唯一真相源是
> `data/README.md` §6，此处只引用不复述。代码侧单点 = `src/tripwire/diff/{align,engine}.py`。

---

## 一、命令

```bash
tripwire diff --orig <stage-0.csv> --got <stage-<k>.csv> --key <列名>
tripwire diff --orig a.csv --got b.csv --align position
tripwire diff --orig a.csv --got b.csv --align lcs
tripwire diff --orig a.csv --got b.csv --key id --batch 100 --json out.json --stage-index 1
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--orig` / `--got` | ✅ | 两份**原始文本快照**（`stage-0.csv` 与 `stage-<k>.csv`） |
| `--key` | `--align key` 时必填 | 主键列名。缺 → **exit 3**，不产出任何差异结论 |
| `--align` | | `key`（默认）/ `position` / `lcs` |
| `--batch N` | | 按 N 行分块推断类型，不一致落 `dtype_drift` 结构记录 |
| `--stage-index k` | | 把差异归属到 1-based 输出阶段序号（与 `stages.json` 同一套编号） |
| `--json FILE` | | 落 `DiffResult`（走 `serialization.write_json`） |

**退出码**：M2 期间一律 `3`（拒绝判定）——`0`/`1` 的语义里都带"门禁通过"，而门禁在 M4。
见 `data/README.md` §6.3。

---

## 二、对齐语义

| `--align` | 行怎么配 | `row_key` 是什么 | 什么时候用 |
|---|---|---|---|
| `key` | 按主键值一对一 | 主键值文本 | 默认。有稳定主键就该用它 |
| `position` | 按行号 `i`↔`i` | `#<row_index>` | 没有主键、且确定没有插删行 |
| `lcs` | 行指纹精确 LCS 作锚点，锚点之间按位置补配 | 匹配到的**原行**指纹（`~` 前缀 = 只在往返后出现） | 没有主键但可能插删行 |

三条**拒绝运行**的情形（全部 exit 3，**不产出 `diffs: []`**）：

1. `--align key` 没给 `--key`（K4 / D3）；
2. 主键列不在任一表头里（报列名，不猜"最像的那一列"）；
3. 主键有重复值（不"取第一个"——那会把任意选择藏进结论）。

`position` 遇到插行会**雪崩式误报**（后面每行都对不上）。这不是 bug，是这条策略的固有代价；
默认不用它就是因为它会给出一个漂亮但骗人的差异数（D3）。

---

## 三、`DiffRecord` 形状

```json
{
  "row_key": "r1",
  "col": "zip",
  "col_index": 2,
  "orig_text": "02114",
  "got_text": "2114",
  "orig_missing": false,
  "got_missing": false,
  "declared_type": null,
  "stage_index": 1
}
```

| 字段 | 说明 |
|---|---|
| `row_key` | 语义随策略变（见上表）；M5 的 `fingerprint` 把它作为输入 |
| `col` | 列名（给人看） |
| `col_index` | 列序号（**排序键的第二段**；按名排序会随 `col_order` 漂移） |
| `orig_text` / `got_text` | 两侧**原始文本**，不做类型推断（K1） |
| `orig_missing` / `got_missing` | 该格是否**不存在**（行短于表头）；`false` 且文本为空 = 空串 |
| `declared_type` | 该列声明的类型；无声明为 `null`（不猜） |
| `stage_index` | 产出该差异的输出阶段序号；离线比较两份任意 CSV 时为 `null` |

**排序**：`(row_key, col_index)`（K5）。同一输入两跑的 `--json` 产物逐字节一致。

---

## 四、`StructureRecord` 形状

```json
{"kind": "row_count", "detail": {"orig": 2, "got": 1, "missing_rows": ["2"], "extra_rows": []}, "stage_index": 1}
```

| `kind` | `detail` 的键 | 判据 | 触发条件 |
|---|---|---|---|
| `row_count` | `orig` / `got` / `missing_rows` / `extra_rows` | 行数不等 | 出现单边行对子 |
| `col_count` | `orig` / `got` | 列数不等 | 表头长度不同 |
| `col_order` | `orig` / `got`（**只含两侧都有的列**） | 公共列相对顺序变了 | 例如 `a,b` → `b,a` |
| `header` | `orig` / `got` / `added` / `removed` | 列名集合不同 | 改名、增删列 |
| `dtype_drift` | `side` / `col` / `col_index` / `types` / `chunks` | 同一列在不同 chunk 推断不一致 | 仅 `--batch N` |

落盘顺序 = 上表顺序（`STRUCTURE_KINDS`），不依赖字典序。

**为什么不折算进单元格差异率**：列名改了会被读成"N 个单元格都变了"，一个结构事实被膨胀成 N 条；
而差异率的分母是单元格数，同一个问题会被计两次。

**为什么整行消失不产单元格差异**：同理。消失的行进 `row_count` 的 `missing_rows`，
不在单元格层再报一遍。

**`col_order` 只比公共列**：`c` 改名成 `d` 是 `header` 事实；说"列序也变了"是把一件事报两遍。

**`dtype_drift` 的推断口径**（`--batch N`）：只认 `common.cell_kind` 的四类（`int`/`float`/`text`/`empty`），
一个 chunk 里出现非数字文本就整块落回 `text`（贴 pandas 的 `object` 回退，不做多数表决）。
全空 chunk 返回 `null`，不参与漂移判定。

---

## 五、确定性

- 不 import pandas、不读时钟、不读随机、不读文件系统（差异是两份输入的纯函数）；
- 列配对：`position` 按序号，`key`/`lcs` **按列名**——列序变化归 `col_order`，不在单元格层重复报；
- `cells_compared = 配对行数 × 配对列数`，是差异率分母的唯一定义处。

### 空值三态：缺格 vs 空串

`DiffRecord` 带 `orig_missing` / `got_missing` 两个布尔标记：

- `true` = 这一行**比表头短**（格根本不存在）；
- `false` = 格存在，文本可能为空串。

所以 `1,x`（缺第 3 格）与 `1,x,`（第 3 格为空串）**会被报成一条差异**：
`orig_text=""`+`orig_missing=true` → `got_text=""`+`got_missing=false`。

这是 M3 第 9 条规则 `empty_vs_null_vs_missing` 的证据面。没有它，三态在差异层就塌缩成
"值都是空串"，那条规则无从判定。`empty` 与 `null-token`（`NULL` / `N/A` 等字面量）
的区别仍在**文本**里，谓词自己看 `orig_text`。
