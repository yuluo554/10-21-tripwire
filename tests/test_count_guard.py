# -*- coding: utf-8 -*-
"""测试计数自指守门（本迭代新增）。

**为什么要有这条**：本仓的 plan/ 与 HANDOFF 里大量引用「N passed / M skipped」。
这些数字只能靠人当场量、当场写，然后**下一次加测试就悄悄失效**——留档继续说谎，
而没有任何一条测试会红。（同批的 road-mqi-checker 踩过：只锁"收集数"不锁"通过数"，
把 README 改成荒谬值仍然 passed。）

本守门钉三件事：
1. **算术关系**：`collected == passed + skipped + failed + errors`（收集数不能凭空空转）。
2. **文档里的数字与现场一致**：`plan/RELEASE-M6.1.md` §1.2 登记的两个口径
   （有/无 pywin32）必须能在当前树上复现。文档写 218 而实测 224 时，这条会红。
3. **口径数量**：必须同时登记"装 pywin32"与"不装 pywin32"两档——只记一个是不完整的
   （19 条 `excel_com_csv` 声明式跳过的存在本身就是产品行为的一部分）。

⚠ 本测试**不自己跑 pytest**（嵌套 pytest 会拖慢一倍并可能递归）。它做的是：
从 `--collect-only` 拿收集数，再读 `plan/RELEASE-M6.1.md` 里登记的数字，两者对撞。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DOC = REPO_ROOT / "plan" / "RELEASE-M6.1.md"

#: 这些测试自身会让收集数变化，所以文档数字必须把本文件算进去——这不是豁免，是要求。
SELF = Path(__file__).name


def _collect_count():
    """收集数（**不自己跑测试**，只 collect）。

    ⚠ 这个子进程与本测试同 rootdir。实测（Windows）嵌套 pytest 与外层会话争用同一个
    `.pytest_cache` 会**间歇性**失败（约 1/45 次，本机 hammer 复现过 1 次）。
    这里显式禁掉缓存插件并把 `cache_dir` 指到临时目录 —— 收集数与缓存无关，排除掉它才是确定性判据。
    `-p no:cacheprovider` 也顺带避免了"跑测试会改工作树"这一类副作用。
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="countguard-") as cache_dir:
        proc = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "-o", "addopts=",
                "-p", "no:cacheprovider",
                "-o", "cache_dir=%s" % cache_dir,
                "--collect-only", "-q",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
    out = proc.stdout + proc.stderr
    m = re.search(r"(\d+) tests? collected", out)
    assert m, "pytest --collect-only 没打印收集数（rc=%d）：\n%s" % (proc.returncode, out[-800:])
    return int(m.group(1))


def _doc_numbers():
    """从 RELEASE-M6.1.md §1.2 读登记的两个口径。

    返回 `(collected, (with_pywin32_passed, with_pywin32_skipped), (without_passed, without_skipped))`。
    表格形态：`| 收集数 | ... | **227** |` / `| 全量测试（装 pywin32） | ... | **227 passed / 0 skipped**（…） |`
    """
    assert RELEASE_DOC.is_file(), "缺 plan/RELEASE-M6.1.md（发布留档）"
    text = RELEASE_DOC.read_text(encoding="utf-8")
    m = re.search(r"收集数[^\n]*?\*\*(\d+)\*\*", text)
    wp = re.search(r"装 pywin32）[^\n]*?\*\*(\d+) passed / (\d+) skipped\*\*", text)
    npw = re.search(r"无 pywin32）[^\n]*?\*\*(\d+) passed / (\d+) skipped\*\*", text)
    assert m and wp and npw, (
        "plan/RELEASE-M6.1.md §1.2 的三个计数没写全（收集数 / 装 pywin32 / 无 pywin32），"
        "且须是 `**N passed / M skipped**` 形态"
    )
    return int(m.group(1)), (int(wp.group(1)), int(wp.group(2))), (int(npw.group(1)), int(npw.group(2)))


def test_collected_matches_release_doc():
    """文档登记的收集数必须等于现场收集数。加测试不同轮改文档 => 这里红。"""
    live = _collect_count()
    documented, _, _ = _doc_numbers()
    assert live == documented, (
        "收集数与 plan/RELEASE-M6.1.md §1.2 登记的不一致：现场 %d / 文档 %d。"
        "新增或删除测试后必须在同一轮更新该节（本仓纪律：留档里的数字必须当场量）。" % (live, documented)
    )


def test_two_configurations_are_consistent_arithmetic():
    """两个口径必须自洽：收集数 = 通过数 + 跳过数，且两档的 passed 差值 = skip 差值。

    ⚠ 只锁"收集数"是不够的（road-mqi-checker 那轮的坑）：把通过数改成荒谬值，
    收集数照样对得上，门仍然 pass。所以这里锁的是**算术关系**。
    """
    collected, (wp_p, wp_s), (npw_p, npw_s) = _doc_numbers()
    assert collected == wp_p + wp_s, (
        "装 pywin32 口径算术不平：%d != %d passed + %d skipped" % (collected, wp_p, wp_s)
    )
    assert collected == npw_p + npw_s, (
        "无 pywin32 口径算术不平：%d != %d passed + %d skipped" % (collected, npw_p, npw_s)
    )
    assert wp_p - npw_p == npw_s, (
        "两档 passed 差值应等于跳过数：%d - %d != %d" % (wp_p, npw_p, npw_s)
    )
    assert npw_s > 0, "无 pywin32 档的 skipped 必须 > 0（19 条 Excel COM 声明式跳过是产品行为）"


def test_self_reported_counts_appear_only_in_release_doc():
    """其他 plan 文档只许出现**历史时点值**，不许出现"当前树"的计数。

    判据是**封顶**而非白名单：历史值天然都小于当前收集数（M3=117 / M4=177 / M5=207 /
    v0.1.0=211），所以「`N passed` 且 N >= 当前收集数」只可能是"当前值被散落"。
    这样规则不必随每次加测试而改，也不会误杀各棒交接单里合法的手记。
    """
    live = _collect_count()
    offenders = []
    for path in sorted((REPO_ROOT / "plan").glob("*.md")):
        if path.name == RELEASE_DOC.name:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            for m in re.finditer(r"\b(\d{3}) passed\b", line):
                if int(m.group(1)) >= live:
                    offenders.append("%s:%d: %s" % (path.name, lineno, line.strip()[:120]))
    assert offenders == [], (
        "这些 plan 文档写了「当前树」量级的测试计数（≥ 现场收集数 %d）。当前值只能写进 "
        "plan/RELEASE-M6.1.md §1.2，别处一律给指针：\n  - " % live + "\n  - ".join(offenders)
    )
