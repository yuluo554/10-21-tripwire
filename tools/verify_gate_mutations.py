#!/usr/bin/env python3
"""门自身的变异验证：故意弄坏被测对象，门必须变红；还原后必须复绿。

为什么要有这个脚本：一个"永远绿"的门和没有门是一回事。布局门/脱敏门里的每条判据
都必须被至少一组变异打过，否则它就是**未经证伪的判据**。

纪律（全脚本遵守）：
  1. 替换前 assert 标记存在；替换后 assert 文件字节已变；还原后 assert 字节一致（`try/finally`）。
  2. 变异点选**数据**不选**措辞**（改标题文案不会让数据消失，也就测不出判据）。
  3. 靶子随项目进度过期时走**显式 SKIP**（打印 SKIP，不计 FAIL 也不计绿）。

用法：`python tools/verify_gate_mutations.py`
退出码：0 全部按预期（红/绿/SKIP 都符合预期）/ 1 有未按预期 / 2 用法错误。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

results: list[tuple[str, str, str]] = []  # (case, status, detail)


class NothingToMutate(Exception):
    """靶子在当前项目进度下不存在——显式 SKIP，不冒充通过。"""


def _read(rel: str) -> str:
    # 注意：`Path.read_text(newline=)` 是 3.13 才有的参数，本机 3.12 会 TypeError
    with open(ROOT / rel, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_raw(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8", newline="")


def _bytes(rel: str) -> bytes:
    return (ROOT / rel).read_bytes()


def _gate() -> tuple[int, str]:
    proc = subprocess.run(
        [PY, str(ROOT / "tools" / "check_sprint_layout.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _desense() -> tuple[int, str]:
    proc = subprocess.run(
        [PY, str(ROOT / "tools" / "check_desensitized.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def mutate_text(rel: str, old: str, new: str, expect_fail: str, case: str, runner=_gate) -> None:
    """文本替换型变异：断言标记存在 -> 断言已变 -> 跑门 -> 断言指定判据 FAIL -> 还原 -> 断言复绿。"""
    original = _bytes(rel)
    text = original.decode("utf-8")
    if old not in text:
        raise NothingToMutate(f"{rel} 里找不到标记: {old[:40]!r}")
    mutated = text.replace(old, new, 1)
    assert mutated != text, "替换后字节未变化（变异是 no-op）"
    try:
        _write_raw(rel, mutated)
        assert _bytes(rel) != original, "写回后字节未变化（变异是 no-op）"
        code, output = runner()
        if code == 0:
            results.append((case, "FAIL(未变红)", f"{rel} 变异后门仍绿"))
            return
        line = next((l for l in output.split("\n") if l.startswith("FAIL") and expect_fail in l), "")
        results.append(
            (case, "PASS" if line else "FAIL(红错判据)", line.strip() or f"未出现 {expect_fail} 的 FAIL 行")
        )
    finally:
        _write_raw(rel, original.decode("utf-8"))
        assert _bytes(rel) == original, "还原后字节不一致"


def mutate_delete(rel: str, expect_fail: str, case: str, runner=_gate) -> None:
    """删件型变异：备份 -> 删除 -> 跑门 -> 断言指定判据 FAIL -> 还原。"""
    original = _bytes(rel)
    backup = Path(tempfile.mkdtemp(prefix="mut-")) / Path(rel).name
    shutil.copy2(ROOT / rel, backup)
    try:
        (ROOT / rel).unlink()
        code, output = runner()
        if code == 0:
            results.append((case, "FAIL(未变红)", f"删除 {rel} 后门仍绿"))
            return
        line = next((l for l in output.split("\n") if l.startswith("FAIL") and expect_fail in l), "")
        results.append(
            (case, "PASS" if line else "FAIL(红错判据)", line.strip() or f"未出现 {expect_fail} 的 FAIL 行")
        )
    finally:
        (ROOT / rel).write_bytes(original)
        assert _bytes(rel) == original, "还原后字节不一致"
        shutil.rmtree(backup.parent, ignore_errors=True)


# ── 布局门：10 条判据组（判据有几条，变异就覆盖几条）──────────────────────────

def v1_delete_agents():
    mutate_delete("AGENTS.md", "LAYOUT.FILES", "V1 删 AGENTS.md")


def v2_flip_status_in_one_copy():
    # 只改一个副本（README）→ 跨副本不一致
    mutate_text(
        "README.md",
        "| M0 | 计划与方法论装订 + 可运行骨架 | ✅ |",
        "| M0 | 计划与方法论装订 + 可运行骨架 | ⬜ |",
        "LAYOUT.STATUS",
        "V2 一处副本把 M0 翻 ⬜",
    )


def v3_stale_gap():
    """缺口说明里写回已 ✅ 的里程碑号（数据变异，不是措辞）。

    **动态选取**靶子行（与 V8 同一条纪律）：写死某一行文案时，那行缺口一被关闭靶子就消失，
    变异会退化成"靶子过期"（M1 关掉 G-1 时就真发生了）。这里改成：从缺口表挑**第一条
    仍存在**的数据行，把当前最小的已 ✅ 里程碑号注入它的「说明」列——注入哪行不重要，
    重要的是"缺口列里出现已完成里程碑号"这一形态必须让门变红。
    """
    rel = "plan/06-交付对标与决策.md"
    original = _bytes(rel)
    lines = original.decode("utf-8").split("\n")

    # 「已 ✅ 的里程碑」要从**状态副本**取（plan/06 本身没有状态行）：
    # plan/05 §一 状态表是权威副本之一，首格为 `M<k>`，末尾格为状态标记。
    done = []
    for line in _read("plan/05-里程碑与发布.md").split("\n"):
        match = re.match(r"^\|\s*M(\d+)\s*\|", line)
        if not match:
            continue
        if any(mark in line for mark in ("⬜", "🟡", "未开始", "未执行", "待执行", "待确认")):
            continue
        done.append(int(match.group(1)))
    done.sort()
    if not done:
        raise NothingToMutate("没有任何已 ✅ 的里程碑（项目还没完成过里程碑）")
    milestone = done[0]

    header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("|") and line.split("|")[1].strip() == "缺口"),
        -1,
    )
    if header_idx < 0:
        raise NothingToMutate("plan/06 找不到缺口表（判据表搬走了？）")
    target_idx = header_idx + 2
    if target_idx >= len(lines) or not lines[target_idx].startswith("|"):
        # 缺口表已清空（全部缺口关闭）——**注入**一行而不是跳过。
        # 变异要证明的是"缺口列出现已 ✅ 里程碑号 → 门必须红"；表格空着时这条判据仍是活的，
        # 靠"没有数据行可改"跳过就等于把它放进盲区（M6 收尾时实测踩到）。
        lines.insert(header_idx + 2, "| G-99 注入的缺口 | 变异注入：说明里含 M%d | M%d |" % (milestone, milestone))
        mutated = "\n".join(lines)
        assert mutated != original.decode("utf-8"), "注入后文本未变化（变异是 no-op）"
        try:
            _write_raw(rel, mutated)
            assert _bytes(rel) != original, "写回后字节未变化（变异是 no-op）"
            code, output = _gate()
            if code == 0:
                results.append(("V3 缺口说明写回已 ✅ 里程碑", "FAIL(未变红)", "注入缺口行后门仍绿"))
                return
            line = next((l for l in output.split("\n") if l.startswith("FAIL") and "LAYOUT.GAPS" in l), "")
            results.append(
                (
                    "V3 缺口说明写回已 ✅ 里程碑",
                    "PASS" if line else "FAIL(红错判据)",
                    line.strip() or "未出现 LAYOUT.GAPS 的 FAIL",
                )
            )
        finally:
            _write_raw(rel, original.decode("utf-8"))
            assert _bytes(rel) == original, "还原后字节不一致"
        return

    cells = lines[target_idx].split("|")
    if len(cells) < 4:
        raise NothingToMutate("缺口行结构异常（少于 4 段）")
    cells[2] = cells[2] + "（M%d 也没做）" % milestone
    lines[target_idx] = "|".join(cells)

    mutated = "\n".join(lines)
    assert mutated != original.decode("utf-8"), "替换后文本未变化（变异是 no-op）"
    try:
        _write_raw(rel, mutated)
        assert _bytes(rel) != original, "写回后字节未变化（变异是 no-op）"
        code, output = _gate()
        if code == 0:
            results.append(("V3 缺口说明写回已 ✅ 里程碑", "FAIL(未变红)", "plan/06 缺口列变异后门仍绿"))
            return
        line = next((l for l in output.split("\n") if l.startswith("FAIL") and "LAYOUT.GAPS" in l), "")
        results.append(
            (
                "V3 缺口说明写回已 ✅ 里程碑",
                "PASS" if line else "FAIL(红错判据)",
                line.strip() or "未出现 LAYOUT.GAPS 的 FAIL",
            )
        )
    finally:
        _write_raw(rel, original.decode("utf-8"))
        assert _bytes(rel) == original, "还原后字节不一致"


def v4_delete_handoff():
    mutate_delete("plan/HANDOFF-M0.md", "LAYOUT.HANDOFFS", "V4 删 HANDOFF-M0.md")


def v5_delete_binding_line():
    mutate_text(
        "plan/00-README总览.md",
        "> 方法论：`ai-tool-project-sprint`（装订 2026-10-21）｜布局门：`python tools/check_sprint_layout.py`｜续接对话第一件事 = 跑它\n",
        "",
        "LAYOUT.BINDING_HEAD",
        "V5 删 plan/00 顶部装订行",
    )


def v6_delete_plan_doc():
    mutate_delete("plan/02-架构与技术选型.md", "LAYOUT.FILES", "V6 删 plan/02")


def v7_missing_section():
    mutate_text(
        "plan/02-架构与技术选型.md",
        "## 三、依赖选型",
        "## 三、依赖",
        "LAYOUT.SECTIONS",
        "V7 改写 plan/02 必需小节标题",
    )


def v8_ledger_pending():
    """台账行变异：**动态选取**一条已 ✅ 的行（写死整行文本会随文案改动失效→静默 SKIP）。

    判别（SKILL 第十一形态）："这条变异找的靶子，在项目当前进度下还存在吗？"
    写死整行文案时，改一个字靶子就消失；动态按"状态格形态"选取则与文案解耦。
    """
    rel = "plan/00-README总览.md"
    original = _bytes(rel)
    lines = original.decode("utf-8").split("\n")
    target = None
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 3:
            continue
        status = cells[-2].strip()
        match = re.fullmatch(r"✅\s*M(\d+)", status)
        if match:
            target = (index, len(cells) - 2, int(match.group(1)))
            break
    if target is None:
        raise NothingToMutate("台账里没有任何『✅ M<k>』状态格（项目还没完成过里程碑）")

    index, cell_index, milestone = target
    cells = lines[index].split("|")
    cells[cell_index] = " ⬜ 待 M%d " % milestone
    lines[index] = "|".join(cells)
    mutated = "\n".join(lines)
    assert mutated != original.decode("utf-8"), "替换后文本未变化（变异是 no-op）"
    try:
        _write_raw(rel, mutated)
        assert _bytes(rel) != original, "写回后字节未变化（变异是 no-op）"
        code, output = _gate()
        if code == 0:
            results.append(("V8 台账 ✅ 行改 ⬜", "FAIL(未变红)", "台账行变异后门仍绿"))
            return
        line = next((l for l in output.split("\n") if l.startswith("FAIL") and "LAYOUT.LEDGER" in l), "")
        results.append(("V8 台账 ✅ 行改 ⬜", "PASS" if line else "FAIL(红错判据)", line.strip() or "未出现 LAYOUT.LEDGER 的 FAIL"))
    finally:
        _write_raw(rel, original.decode("utf-8"))
        assert _bytes(rel) == original, "还原后字节不一致"


def v9_documented_tool_missing():
    # 文档点名了 tools/ 脚本但它不在仓库里（"引用而不实现"的出口门静默消失形态）
    target = ROOT / "tools" / "check_desensitized.py"
    original = target.read_bytes()
    try:
        target.unlink()
        code, output = _gate()
        if code == 0:
            results.append(("V9 文档点名的工具缺失", "FAIL(未变红)", "删除 tools/check_desensitized.py 后门仍绿"))
            return
        line = next((l for l in output.split("\n") if l.startswith("FAIL") and "LAYOUT.DOC_TOOLS" in l), "")
        results.append(
            ("V9 文档点名的工具缺失", "PASS" if line else "FAIL(红错判据)", line.strip() or "未出现 LAYOUT.DOC_TOOLS 的 FAIL")
        )
    finally:
        target.write_bytes(original)
        assert target.read_bytes() == original, "还原后字节不一致"


def v10_ledger_header_missing():
    # 判据"找不到表头"分支：门要报 FAIL 而不是崩（rc=1 但一条结论都没跑）
    mutate_text(
        "plan/00-README总览.md",
        "| 承诺项 | 素材来源 | 交付物内可达性 | 核验方式 | 状态 |",
        "| 承诺项 | 素材来源 | 交付物内可达性 | 核验方式 | 进度 |",
        "LAYOUT.LEDGER",
        "V10 台账表头改名（判据表搬走）",
    )


def _milestone_done(number: int) -> bool:
    """状态表里 `M<number>` 是否已 ✅（读 `plan/05` §一）。

    发布留档类变异的靶子判据是**里程碑状态**，不是"文件在不在"：布局门的
    `LAYOUT.RELEASE` 在发布里程碑未 ✅ 时**早退为 True**（"收尾记录尚不适用"），
    而 `plan/05` §五 第 1 条又要求留档**先于 tag 落盘**——于是文件已存在、门却还不校验它。
    按文件存在性做 skip 会在这一窗口里把变异永久 SKIP 掉（实测踩到：V12/V13 报"未按预期"）。
    """
    text = _read("plan/05-里程碑与发布.md")
    for line in text.split("\n"):
        match = re.match(r"^\|\s*M(\d+)\b", line)
        if match and int(match.group(1)) == number:
            return "✅" in line
    return False


def v11_release_section_removed():
    if not _milestone_done(6):
        raise NothingToMutate("M6 未完成，LAYOUT.RELEASE 尚未校验发布留档（本条在 M6 之前的预期形态）")
    mutate_text(
        "plan/RELEASE-M6.md",
        "## 三、阶段 7 覆盖对账",
        "## 三、覆盖",
        "LAYOUT.RELEASE",
        "V11 删发布留档的覆盖对账小节",
    )


def v12_release_two_columns():
    if not _milestone_done(6):
        raise NothingToMutate("M6 未完成，LAYOUT.RELEASE 尚未校验发布留档（本条在 M6 之前的预期形态）")
    mutate_text(
        "plan/RELEASE-M6.md",
        "## 二、tag 后追加事实",
        "## 二、追加事实",
        "LAYOUT.RELEASE",
        "V12 去掉发布留档的两栏标记",
    )


def v13_release_doc_missing():
    if not _milestone_done(6):
        raise NothingToMutate("M6 未完成，LAYOUT.RELEASE 尚未校验发布留档（本条在 M6 之前的预期形态）")
    mutate_delete("plan/RELEASE-M6.md", "LAYOUT.RELEASE", "V13 删 RELEASE-M6.md")


# ── 脱敏门：4 条规则各一组 ────────────────────────────────────────────────

PROBE = "_mutation_probe.md"


def _probe(line: str, expect_rule: str, case: str) -> None:
    target = ROOT / PROBE
    try:
        target.write_text(line + "\n", encoding="utf-8")
        code, output = _desense()
        if code == 0:
            results.append((case, "FAIL(未变红)", f"注入 {line!r} 后脱敏门仍绿"))
            return
        hit = next((l for l in output.split("\n") if f"[{expect_rule}]" in l), "")
        results.append((case, "PASS" if hit else "FAIL(红错规则)", hit.strip() or f"未命中 {expect_rule}"))
    finally:
        target.unlink(missing_ok=True)


def d1_drive_path():
    _probe("D:/ProgramData/secret/notes.txt", "drive-absolute-path", "D1 盘符绝对路径")


def d2_msys_path():
    _probe("/c/Users/realname/secret.txt", "msys-user-path", "D2 MSYS 用户路径")


def d3_username():
    _probe("owner: ASUS", "host-username", "D3 本机用户名")


def d4_proxy():
    _probe("proxy=http://127.0.0.1:7897", "loopback-proxy", "D4 回环代理端口")


LAYOUT_CASES = [
    v1_delete_agents,
    v2_flip_status_in_one_copy,
    v3_stale_gap,
    v4_delete_handoff,
    v5_delete_binding_line,
    v6_delete_plan_doc,
    v7_missing_section,
    v8_ledger_pending,
    v9_documented_tool_missing,
    v10_ledger_header_missing,
    v11_release_section_removed,
    v12_release_two_columns,
    v13_release_doc_missing,
]

DESENSE_CASES = [d1_drive_path, d2_msys_path, d3_username, d4_proxy]

#: 允许 SKIP 的用例（发布留档在 M6 前结构上不可能存在）。
#: 其余任何 SKIP 都算"变异靶子过期"——静默 SKIP 会让假门伪装成绿（SKILL 第十一形态）。
ALLOWED_SKIPS = {
    "v11_release_section_removed",
    "v12_release_two_columns",
    "v13_release_doc_missing",
}


def main() -> int:
    if len(sys.argv) > 1:
        sys.stderr.write("verify_gate_mutations: unknown argument %s\n" % sys.argv[1])
        return 2

    code, output = _gate()
    if code != 0:
        sys.stdout.write("前置：布局门当前不是全绿，先修好再跑变异。\n" + output)
        return 1
    code, output = _desense()
    if code != 0:
        sys.stdout.write("前置：脱敏门当前不是 0 命中，先修好再跑变异。\n" + output)
        return 1

    sys.stdout.write("基线：布局门全绿 / 脱敏门 0 命中\n")
    sys.stdout.write("=" * 64 + "\n")

    skips = []
    for case in LAYOUT_CASES:
        try:
            case()
        except NothingToMutate as reason:
            skips.append((case.__name__, str(reason)))
        except AssertionError as error:
            results.append((case.__name__, "FAIL(变异未生效)", str(error)))
        code, output = _gate()
        if code != 0:
            results.append((case.__name__, "FAIL(还原后仍红)", output[-300:]))

    for case in DESENSE_CASES:
        try:
            case()
        except AssertionError as error:
            results.append((case.__name__, "FAIL(变异未生效)", str(error)))
        code, output = _desense()
        if code != 0:
            results.append((case.__name__, "FAIL(还原后仍红)", output[-300:]))

    for name, status, detail in results:
        sys.stdout.write("%-22s %-16s %s\n" % (status, name, detail))
    unexpected_skips = []
    for name, reason in skips:
        if name in ALLOWED_SKIPS:
            sys.stdout.write("%-22s %-16s %s\n" % ("SKIP", name, reason))
        else:
            unexpected_skips.append(name)
            sys.stdout.write("%-22s %-16s %s\n" % ("FAIL(靶子过期)", name, reason))

    bad = [r for r in results if not r[1].startswith("PASS")] + [
        (name, "FAIL(靶子过期)", "") for name in unexpected_skips
    ]
    sys.stdout.write("=" * 64 + "\n")
    sys.stdout.write(
        "变异组：%d 组，按预期红 %d / 允许 SKIP %d / 未按预期 %d\n"
        % (
            len(results) + len(skips),
            len(results) - len([r for r in results if not r[1].startswith("PASS")]),
            len(skips) - len(unexpected_skips),
            len(bad),
        )
    )
    sys.stdout.write("结论: %s\n" % ("符合预期" if not bad else "有 %d 组未按预期" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
