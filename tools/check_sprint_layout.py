#!/usr/bin/env python3
"""布局门（方法论装订第②件）：把"项目还长在方法论上"变成可跑红的断言。

来源：ai-tool-project-sprint `references/templates/check-sprint-layout.mjs`（判据集同构）。
判据一律落**仓库内文件**，不读 git 元数据（浅克隆 / 无 `.git` 的解包树下会翻转）。
退出码：0 全绿 / 1 有 FAIL / 2 用法错误。

变异验证（判据有几条就做几组，全组必须变红）：
  V1  删 AGENTS.md                                  -> LAYOUT.FILES
  V2  把 plan/05 某个 ✅ 翻成 ⬜                      -> LAYOUT.STATUS
  V3  在 plan/06 缺口说明里写回已 ✅ 的里程碑          -> LAYOUT.GAPS
  V4  删一份 plan/HANDOFF-M<k>.md                   -> LAYOUT.HANDOFFS
  V5  删 plan/00 顶部装订行                          -> LAYOUT.BINDING_HEAD
  V6  删发布留档的「覆盖对账」整节                     -> LAYOUT.RELEASE（M6 ✅ 后）
  V7  删一份 plan/0<k>                              -> LAYOUT.FILES
  V8  去掉发布留档 §二 的 "tag 后" 标记               -> LAYOUT.RELEASE（M6 ✅ 后）
  V9  把台账某条 ✅ 行改成 ⬜ 待 M<k>                  -> LAYOUT.LEDGER
  V10 保留 M6 ✅ 但删掉 RELEASE-M6.md               -> LAYOUT.RELEASE（M6 ✅ 后）
V6/V8/V10 在 M6 未完成时报 PASS 并写明"尚不适用"——它们的变异靶子在 M6 翻 ✅ 之后才存在。
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
scanned = {"docs": 0, "handoffs": 0, "copies": 0, "doc_tools": 0}


def add(check_id, ok, detail):
    checks.append((check_id, ok, detail))


def read(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    "data/README.md",
    "plan/00-README总览.md",
    "plan/01-题目文档.md",
    "plan/02-架构与技术选型.md",
    "plan/03-模块详设.md",
    "plan/04-数据计划.md",
    "plan/05-里程碑与发布.md",
    "plan/06-交付对标与决策.md",
]

# 装订行：三个锚点同现于同一行（顺序无关），不用 `A.*B.*C`（写死顺序会产生假红）
BINDING_LINE = re.compile(
    r"^>(?=.*ai-tool-project-sprint)(?=.*check_sprint_layout)(?=.*20\d{2}-\d{2}-\d{2}).*$",
    re.MULTILINE,
)

REQUIRED_SECTIONS = {
    "plan/00-README总览.md": ["文档索引", "决策记录", "承诺-证据台账", "里程碑"],
    "plan/01-题目文档.md": ["任务要求", "评分标准", "边界与非目标"],
    "plan/02-架构与技术选型.md": ["分层", "依赖选型", "退出码"],
    "plan/03-模块详设.md": ["M1", "M3", "跨模块门禁"],
    "plan/04-数据计划.md": ["数据清单", "真值覆盖口径", "确定性纪律"],
    "plan/05-里程碑与发布.md": ["DoD", "已知未验证项"],
    "plan/06-交付对标与决策.md": ["评分对标", "风险登记", "缺口表"],
    "data/README.md": ["依据查证记录", "数值口径"],
}

HANDOFF_SECTIONS = ["当前进度", "当前事实", "待办", "既定口径", "环境坑", "DoD", "命令速查"]

EXEMPT_MILESTONES = []  # 本项目 M0 也写 HANDOFF-M0.md（收尾棒与普通棒同一标准）
HANDOFF_FORMAT_FROM = 0

STATUS_COPIES = [
    {"file": "plan/00-README总览.md", "kind": "里程碑表"},
    {"file": "plan/05-里程碑与发布.md", "kind": "状态表"},
    {"file": "README.md", "kind": "状态表"},
]

STATUS_LINE = re.compile(r"^\|\s*\*{0,2}M(\d+)\b")
PENDING_MARKERS = ["⬜", "🟡", "未开始", "未执行", "待执行", "待确认"]


def check_required_files():
    missing = [rel for rel in REQUIRED_FILES if not os.path.isfile(os.path.join(ROOT, rel))]
    scanned["docs"] = len(REQUIRED_FILES) - len(missing)
    add("LAYOUT.FILES", not missing, "缺: " + ",".join(missing) if missing else "%d 份齐备" % scanned["docs"])


def check_binding_head():
    text = read("plan/00-README总览.md") or ""
    ok = bool(BINDING_LINE.search(text))
    add(
        "LAYOUT.BINDING_HEAD",
        ok,
        "plan/00 顶部有装订行（三锚点齐）"
        if ok
        else "plan/00 顶部缺装订行（需同现：方法论名 + 布局门命令 + 装订日期）",
    )


def check_sections():
    bad = []
    for rel, needles in REQUIRED_SECTIONS.items():
        text = read(rel)
        if text is None:
            continue
        missing = [n for n in needles if n not in text]
        if missing:
            bad.append("%s: %s" % (rel, "/".join(missing)))
    add("LAYOUT.SECTIONS", not bad, "；".join(bad) if bad else "%d 份小节齐备" % len(REQUIRED_SECTIONS))


def collect_states():
    """逐副本采集状态。**真值不取自任何一个副本**（防自我参照恒真）。"""
    states = {}
    for copy in STATUS_COPIES:
        text = read(copy["file"])
        if text is None:
            continue
        scanned["copies"] += 1
        for line in text.split("\n"):
            match = STATUS_LINE.match(line)
            if not match:
                continue
            pending = any(mark in line for mark in PENDING_MARKERS)
            states.setdefault(int(match.group(1)), set()).add("pending" if pending else "done")
    return states


def check_status_agreement(states):
    conflicts = []
    for k in sorted(states):
        if len(states[k]) > 1:
            conflicts.append("M%d 在副本间状态不一致（%s）" % (k, " vs ".join(sorted(states[k]))))
    add(
        "LAYOUT.STATUS",
        not conflicts,
        "；".join(conflicts)
        if conflicts
        else "%d 处副本 × %d 个里程碑 状态全一致" % (scanned["copies"], len(states)),
    )


def check_handoffs(done):
    missing = []
    for k in done:
        if k in EXEMPT_MILESTONES:
            continue
        rel = "plan/HANDOFF-M%d.md" % k
        text = read(rel)
        if text is None:
            missing.append("%s(缺)" % rel)
            continue
        scanned["handoffs"] += 1
        if k < HANDOFF_FORMAT_FROM:
            continue
        lack = [n for n in HANDOFF_SECTIONS if n not in text]
        if lack:
            missing.append("%s(缺节: %s)" % (rel, "/".join(lack)))
    add(
        "LAYOUT.HANDOFFS",
        not missing,
        "；".join(missing) if missing else "%d 份交接单齐（七节）" % scanned["handoffs"],
    )


def _table_cells(line):
    return [cell.strip() for cell in line.split("|")[1:-1]]


def check_stale_gaps(done):
    """plan/06 缺口表：按表头定位列，扫描面 = 表头 -> 首条非表格行即止。"""
    lines = (read("plan/06-交付对标与决策.md") or "").split("\n")
    # 表头判据 = 首格**恰为**「缺口」，不是"行里含『缺口』"——后者会命中风险登记表里
    # 正文含"让缺口可见"的那一行（本机实测：首版就是这样选错了表头，导致 V3 变异恒绿）。
    header_idx = next(
        (i for i, l in enumerate(lines) if l.startswith("|") and _table_cells(l)[:1] == ["缺口"]),
        -1,
    )
    if header_idx < 0:
        add("LAYOUT.GAPS", False, "plan/06 找不到含『缺口』表头的表（判据表搬走了？）")
        return
    headers = _table_cells(lines[header_idx])
    if not headers:
        add("LAYOUT.GAPS", False, "plan/06 缺口表表头为空（判据表搬走了？）")
        return
    # 扫描面 = 除「目标里程碑」列之外的**全部**单元格。
    # - 「目标里程碑」列合法地写着未来里程碑号（"这条缺口计划在 M1 关闭"），扫它会假红；
    # - 但「缺口号」「说明」两列都要扫：V3 变异实测，只扫「说明」列时，把已完成里程碑写回
    #   「缺口号」列（更真实的故障形态）门仍绿——那正是"表头定列但列选错"的假门。
    scan_cols = [i for i, h in enumerate(headers) if "目标" not in h] or list(range(len(headers)))
    stale = []
    rows = 0
    for i in range(header_idx + 2, len(lines)):
        if not lines[i].startswith("|"):
            break
        rows += 1
        cells = _table_cells(lines[i])
        for col in scan_cols:
            cell = cells[col] if col < len(cells) else ""
            for k in done:
                if re.search(r"(^|[^0-9A-Za-z])M%d([^0-9]|$)" % k, cell):
                    stale.append("plan/06 缺口列仍提 M%d: %s" % (k, cell[:60]))
    add(
        "LAYOUT.GAPS",
        not stale,
        "；".join(stale) if stale else "plan/06 缺口列扫了 %d 行，无已 ✅ 里程碑" % rows,
    )


def check_ledger(done):
    """承诺-证据台账是第四份状态副本，不在状态表里，要单独一条判据。"""
    lines = (read("plan/00-README总览.md") or "").split("\n")
    header_idx = next(
        (i for i, l in enumerate(lines) if l.startswith("|") and "承诺" in l and "状态" in l),
        -1,
    )
    if header_idx < 0:
        add("LAYOUT.LEDGER", False, "plan/00 找不到『承诺-证据台账』表头（承诺项与状态列）")
        return
    scanned["copies"] += 1
    headers = _table_cells(lines[header_idx])
    try:
        status_col = headers.index("状态")
    except ValueError:
        status_col = len(headers) - 1
    bad = []
    rows = 0
    for i in range(header_idx + 2, len(lines)):
        if not lines[i].startswith("|"):
            break
        rows += 1
        cells = _table_cells(lines[i])
        status = cells[status_col] if status_col < len(cells) else ""
        if not re.search(r"[⬜🟡]|未开始|待 M\d|待开工", status):
            continue
        for k in done:
            if re.search(r"(^|[^0-9A-Za-z])M%d([^0-9]|$)" % k, status, re.IGNORECASE):
                bad.append("台账行仍挂未完成: %s" % status[:60])
    add(
        "LAYOUT.LEDGER",
        not bad and rows > 0,
        "台账表 0 行——判据空跑"
        if rows == 0
        else ("；".join(bad) if bad else "台账 %d 行，已成 ✅ 的里程碑无未完成标记" % rows),
    )


RELEASE_MILESTONE = None  # None = 取状态表里出现过的最大里程碑号


def check_release_doc(done, all_milestones):
    release_milestone = RELEASE_MILESTONE if RELEASE_MILESTONE is not None else max(all_milestones or [0])
    if release_milestone == 0 or release_milestone not in done:
        add(
            "LAYOUT.RELEASE",
            True,
            "发布里程碑 M%d 未完成，收尾记录尚不适用（已扫 %d 个 ✅ 里程碑）"
            % (release_milestone, len(done)),
        )
        return
    release = read("plan/RELEASE-M%d.md" % release_milestone)
    wrapup = read("plan/WRAPUP-M%d.md" % release_milestone)
    if release is None and wrapup is None:
        add(
            "LAYOUT.RELEASE",
            False,
            "缺 plan/RELEASE-M%d.md 或 plan/WRAPUP-M%d.md" % (release_milestone, release_milestone),
        )
        return
    if release is not None:
        cols = bool(re.search(r"^##\s*一、tag 前事实", release, re.MULTILINE)) and bool(
            re.search(r"^##\s*二、tag 后追加", release, re.MULTILINE)
        )
        heading = bool(re.search(r"^#{2,3}.*覆盖对账", release, re.MULTILINE))
        rows = len(re.findall(r"^\|.*(实现|不适用|待首推).*\|$", release, re.MULTILINE))
        add("LAYOUT.RELEASE", cols and heading and rows >= 3, "两栏:%s 覆盖对账小节:%s 三态行数:%d" % (cols, heading, rows))
        return
    add("LAYOUT.RELEASE", True, "WRAPUP 形态")


def check_documented_tools_exist():
    """文档点名的 tools/ 脚本必须有实物（引用而不实现 = 出口门静默消失）。"""
    exempt = set()
    docs = ["AGENTS.md"]
    plan_dir = os.path.join(ROOT, "plan")
    if os.path.isdir(plan_dir):
        docs.extend("plan/" + name for name in sorted(os.listdir(plan_dir)) if name.endswith(".md"))
    referenced = set()
    for rel in docs:
        text = read(rel)
        if text is None:
            continue
        for match in re.finditer(r"tools/[\w.-]+\.(?:mjs|js|cjs|py|sh|ps1)", text):
            referenced.add(match.group(0))
    if not referenced:
        add(
            "LAYOUT.DOC_TOOLS",
            False,
            "扫了 %d 份文档，0 处 tools/ 引用——判据是空的（阳性对照失败）" % len(docs),
        )
        return
    scanned["doc_tools"] = len(referenced)
    missing = [rel for rel in sorted(referenced) if rel not in exempt and not os.path.isfile(os.path.join(ROOT, rel))]
    add(
        "LAYOUT.DOC_TOOLS",
        not missing,
        "文档点名但不存在的工具: " + ",".join(missing)
        if missing
        else "%d 个文档点名的 tools/ 脚本全部在位" % len(referenced),
    )


def main():
    if len(sys.argv) > 1:
        sys.stderr.write("check_sprint_layout: unknown argument %s\n" % sys.argv[1])
        return 2

    for run in (check_required_files, check_binding_head, check_sections, check_documented_tools_exist):
        try:
            run()
        except Exception as error:  # 门永不崩：异常报一条 FAIL 并继续
            add(run.__name__, False, "异常: %s" % error)

    try:
        states = collect_states()
    except Exception as error:
        add("collect_states", False, "异常: %s" % error)
        states = {}

    done = sorted(k for k, value in states.items() if "done" in value)
    all_milestones = sorted(states)

    for run in (
        lambda: check_status_agreement(states),
        lambda: check_handoffs(done),
        lambda: check_stale_gaps(done),
        lambda: check_ledger(done),
        lambda: check_release_doc(done, all_milestones),
    ):
        try:
            run()
        except Exception as error:
            add("check", False, "异常: %s" % error)

    failed = [c for c in checks if not c[1]]
    sys.stdout.write("布局门（方法论装订） · 判据只落仓库内文件\n")
    sys.stdout.write("=" * 56 + "\n")
    for check_id, ok, detail in checks:
        sys.stdout.write("%s  %s  %s\n" % ("PASS" if ok else "FAIL", check_id, detail))
    sys.stdout.write("=" * 56 + "\n")
    sys.stdout.write(
        "这轮扫到：文档 %d / 交接单 %d / 状态副本 %d / 文档点名工具 %d\n"
        % (scanned["docs"], scanned["handoffs"], scanned["copies"], scanned["doc_tools"])
    )
    sys.stdout.write("结论: %s\n" % ("全绿" if not failed else "%d 项 FAIL" % len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
