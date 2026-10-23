# -*- coding: utf-8 -*-
"""`requires-python` 与 CI 实际跑的版本必须一致（D5，本迭代新增）。

为什么要有这条：`requires-python` 是**对用户的分发承诺**，CI 矩阵是**唯一被验证过的范围**。
两者一旦分叉，就会出现「声明支持 3.13 但从未有人跑过」——用户装了、崩了，而我们没有任何证据。
`>=3.10` 这种开区间上界缺失是最常见的分叉形态（3.13/3.14 发布之后它自动"支持"了新版本）。

三条判据：
1. **CI 跑的每个版本都必须落在 `requires-python` 里**（矩阵不能比声明更宽：否则 CI 在验一个
   我们说不支持的环境，红绿都没有意义）。
2. **`requires-python` 必须有上界**（声明不能比矩阵更宽：否则就是承诺未验证的版本）。
3. **两端必须被 CI 覆盖**：下界那个次版本与上界之下最大的次版本都要在矩阵里
   （否则 `>=3.10,<3.13` 也可能只跑 3.12 一格，声明仍然虚高）。

第 4~6 条是**审计函数自身的负控**：喂合成的分叉输入，必须报错。没有这组，
上面的断言只证明「当前文件是对的」，不证明「这个门会红」（与 `test_license_metadata.py` 同构）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_toml(text):
    """3.11+ 用 tomllib；3.10 腿退回 tomli（`dev` extra 里已声明）。"""
    try:
        import tomllib as _t  # py>=3.11
    except ImportError:  # pragma: no cover - 取决于解释器版本
        try:
            import tomli as _t
        except ImportError:  # pragma: no cover
            pytest.skip("需要 tomllib(py>=3.11) 或 tomli 才能解析 pyproject")
    return _t.loads(text)


def parse_spec(spec):
    """把 `>=3.10,<3.13` 解析成 (lo, hi, hi_inclusive)；缺项为 None。只支持 >= 与 < / <=。"""
    lo = hi = None
    hi_inclusive = False
    for part in spec.split(","):
        part = part.strip()
        if part.startswith(">="):
            lo = tuple(int(x) for x in part[2:].strip().split(".")[:2])
        elif part.startswith("<="):
            hi = tuple(int(x) for x in part[2:].strip().split(".")[:2])
            hi_inclusive = True
        elif part.startswith("<"):
            hi = tuple(int(x) for x in part[1:].strip().split(".")[:2])
            hi_inclusive = False
    return lo, hi, hi_inclusive


def parse_ci_matrix(ci_text):
    """从 ci.yml 的 `python-version:` 矩阵行取版本列表。不引 yaml 依赖（本仓零第三方 CI 依赖）。"""
    m = re.search(r"python-version:\s*\[([^\]]+)\]", ci_text)
    if not m:
        return []
    return [v.strip().strip("\"'") for v in m.group(1).split(",") if v.strip()]


def _minor(v):
    parts = v.split(".")
    return (int(parts[0]), int(parts[1]))


def audit_matrix(pyproject_text, ci_text):
    """返回违规描述列表（空 = 一致）。纯函数，供负控直接喂合成文本。"""
    problems = []
    rp = (_load_toml(pyproject_text).get("project") or {}).get("requires-python") or ""
    lo, hi, hi_inclusive = parse_spec(rp)
    if lo is None:
        problems.append("requires-python 缺下界或无法解析：%r" % (rp,))
    if hi is None:
        problems.append(
            "requires-python=%r 没有上界 —— 开区间会声明支持未来所有版本，"
            "而 CI 只验过有限几格；请写成 >=x.y,<a.b 形态" % (rp,)
        )

    versions = parse_ci_matrix(ci_text)
    if not versions:
        problems.append("ci.yml 里找不到 python-version 矩阵（判据无法落地）")
        return problems

    minors = [_minor(v) for v in versions]

    # 判据 1：矩阵不能比声明更宽
    for v, minor in zip(versions, minors):
        if lo is not None and minor < lo:
            problems.append("CI 跑 %s，低于 requires-python 下界 %r" % (v, rp))
        if hi is not None:
            too_high = minor > hi if hi_inclusive else minor >= hi
            if too_high:
                problems.append("CI 跑 %s，高于 requires-python 上界 %r" % (v, rp))

    # 判据 2：声明不能比矩阵更宽（两端都要真跑过）
    if lo is not None and lo not in minors:
        problems.append("requires-python 下界 %d.%d 不在 CI 矩阵 %r 里（下界从未被验）" % (lo + (versions,)))
    if hi is not None:
        top = hi if hi_inclusive else (hi[0], hi[1] - 1)
        if top not in minors:
            problems.append(
                "requires-python 上界之下最高版本 %d.%d 不在 CI 矩阵 %r 里（上界从未被验）" % (top + (versions,))
            )
    return problems


# ---- 对真实仓文件的断言 ----


def _require_ci_file():
    """`ci.yml` 只在仓库树里存在：`MANIFEST.in` 有 `prune .github`（`plan/02`：CI 只对仓库有意义），
    所以 sdist 解包树里拿到它是不合理的——那里显式 SKIP 并写明原因，不让 sdist 变红。

    但**有 `.git` 的树里缺 `ci.yml` 就是真缺陷**（有人在检出的仓库里删了 CI，判据不能静默消失），
    所以那种情况照样红。
    """
    if CI.is_file():
        return
    if (REPO_ROOT / ".git").exists():
        pytest.fail("仓库树里找不到 .github/workflows/ci.yml —— 判据无法落地（不是 sdist 场景）")
    pytest.skip("sdist 解包树不含 .github/（MANIFEST.in prune .github），本判据只在仓库树成立")


def test_repo_requires_python_matches_ci_matrix():
    _require_ci_file()
    problems = audit_matrix(
        PYPROJECT.read_text(encoding="utf-8"), CI.read_text(encoding="utf-8")
    )
    assert problems == [], "requires-python 与 CI 矩阵不一致：\n  - " + "\n  - ".join(problems)


def test_ci_matrix_line_is_parseable():
    """矩阵格式变了（比如改成 include: 形态）必须立刻红，而不是静默返回空列表。"""
    _require_ci_file()
    versions = parse_ci_matrix(CI.read_text(encoding="utf-8"))
    assert len(versions) >= 2, "CI 矩阵解析出 %r，期望至少两格" % (versions,)


# ---- 审计函数自身的负控（证明这个门会红）----

GOOD_PY = '[project]\nname = "x"\nrequires-python = ">=3.10,<3.13"\n'
GOOD_CI = '        python-version: ["3.10", "3.12"]\n'


def test_auditor_accepts_consistent_input():
    assert audit_matrix(GOOD_PY, GOOD_CI) == []


def test_auditor_flags_open_upper_bound():
    """`>=3.10` 无上界 = 声明支持 3.13/3.14，而 CI 从没跑过。"""
    bad = GOOD_PY.replace('">=3.10,<3.13"', '">=3.10"')
    problems = audit_matrix(bad, GOOD_CI)
    assert any("没有上界" in p for p in problems), problems


def test_auditor_flags_untested_upper_bound():
    """上界放宽到 3.13 但矩阵仍只跑到 3.12 → 3.12 之外那格是靠声明撑着的。"""
    bad = GOOD_PY.replace('">=3.10,<3.13"', '">=3.10,<3.14"')
    problems = audit_matrix(bad, GOOD_CI)
    assert any("上界从未被验" in p for p in problems), problems


def test_auditor_flags_ci_outside_declared_range():
    """反向分叉：CI 去跑一个声明里不支持的版本。"""
    bad_ci = '        python-version: ["3.10", "3.13"]\n'
    problems = audit_matrix(GOOD_PY, bad_ci)
    assert any("高于 requires-python 上界" in p for p in problems), problems
