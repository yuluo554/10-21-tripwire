"""README 可执行性守门（M6）。

三条判据，各自打挂一类"文档说能跑但没给可跑输入"的缺口：

1. **README 里 `--input` / `--orig` / `--got` / `--expected` / `--pipeline` 的实参必须真存在**
   （`fixtures/golden/orig.csv`、`pipelines/*.json` 等）。静态扫仓内路径抓不到裸文件名，
   所以判据落在"从命令里抽参数"上。
2. **README 里出现的发布产物名必须是 CI 真会产出的名字**（setuptools 会规范化分发名）。
3. **README 声明的命令形态与 `--help` 一致**（子命令存在、`report` 的 `--expected` 是必填）。

第一条是方法论里"第三类缺口"的机器化：只在本地跑过不算，要看输入是否由版本控制保证存在。
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"

#: 命令里这些选项的实参是**文件路径**（`--run-id` / `--key` / `--format` 不是）。
PATH_ARGS = {"--input", "--orig", "--got", "--expected", "--pipeline", "--json", "--out-dir"}

#: 以**位置参数**吃文件路径的子命令（`validate-pipeline a.json b.json …`）。
#: 只认选项的守门会漏掉这一类——实测变异把它放过了一次。
POSITIONAL_PATH_COMMANDS = {"validate-pipeline"}

#: 命令行里允许出现的占位符（README 用它们示意"上一次 run 的产物"，不是仓库文件）。
PLACEHOLDERS = {"<run_id>", "<k>", "<tag>", "..."}

#: 命令**产出**的落点前缀（gitignore 里的临时/运行目录，不要求先存在）。
OUTPUT_PREFIXES = (".tmp/", "runs/", "dist/", "verify/")


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


def _commands(text: str) -> list[list[str]]:
    """把 bash 代码块里的命令拆成 token 列表（续行 `\\` 先拼起来，`#` 注释行丢掉）。"""
    out: list[list[str]] = []
    for block in _bash_blocks(text):
        joined = block.replace("\\\n", " ")
        for raw in joined.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            if tokens and tokens[0] in {"tripwire", "python", "py", "cd", "gh"}:
                out.append(tokens)
    return out


def _path_args(tokens: list[str]) -> list[str]:
    """抽出命令里所有**被当作文件路径**的实参：选项式 + 位置参数式。"""
    values: list[str] = []
    for index, token in enumerate(tokens):
        if token in PATH_ARGS and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        elif any(token.startswith(arg + "=") for arg in PATH_ARGS):
            values.append(token.split("=", 1)[1])

    # 位置参数式：`tripwire validate-pipeline a.json b.json` —— 子命令之后所有不带 `-`
    # 且形似路径的 token 都要查。
    if len(tokens) > 1 and tokens[0] == "tripwire" and tokens[1] in POSITIONAL_PATH_COMMANDS:
        for token in tokens[2:]:
            if not token.startswith("-") and "/" in token:
                values.append(token)
    return values


def test_readme_path_args_exist_or_are_documented_placeholders():
    """README 的每条文件实参：要么真在仓库里，要么是显式占位符。"""
    text = _readme_text()
    commands = _commands(text)
    assert commands, "README 里没有可解析的命令块——守门空跑"

    missing: list[str] = []
    checked = 0
    for tokens in commands:
        for value in _path_args(tokens):
            if value in PLACEHOLDERS or "<" in value or "*" in value:
                continue
            # 命令自己**产出**的落点（`.tmp/` / `runs/` / `dist/`）不要求先存在：
            # 判据是"README 让用户**读**的输入存在"，不是"它写的目录已建好"。
            if value.startswith(OUTPUT_PREFIXES):
                continue
            checked += 1
            if not (REPO_ROOT / value).exists():
                missing.append(value)

    assert checked > 0, "没有抽到任何文件实参——判据空跑（README 结构变了？）"
    assert not missing, "README 点名的输入/产物在仓库里不存在：%s" % sorted(set(missing))


def test_readme_artifact_names_match_setuptools_normalization():
    """README 写的发布产物名必须是 setuptools 规范化后的形态（下划线，不是连字符）。"""
    from tripwire import __version__

    text = _readme_text()
    mentioned = set(re.findall(r"tripwire-[A-Za-z0-9._+-]+\.(?:tar\.gz|whl)", text))
    assert mentioned, "README 没有提任何发布产物名——复验一节被删了？"

    expected = {
        "tripwire-%s.tar.gz" % __version__,
        "tripwire-%s-py3-none-any.whl" % __version__,
    }
    unknown = mentioned - expected
    assert not unknown, (
        "README 点名的产物与 setuptools 实际产出的名字不符（分发名会规范化）：%s；"
        "本版本 CI 实际产出：%s" % (sorted(unknown), sorted(expected))
    )


def test_readme_commands_are_real_subcommands():
    """README 里 `tripwire <cmd>` 的每个子命令都必须在 CLI 里存在。"""
    from tripwire.cli import main

    assert main(["--help"]) == 0
    text = _readme_text()
    used = set()
    for tokens in _commands(text):
        if tokens[0] == "tripwire" and len(tokens) > 1 and not tokens[1].startswith("-"):
            used.add(tokens[1])
    assert used, "README 没有点名任何子命令"

    known = {
        "run",
        "diff",
        "attribute",
        "gen-fixture",
        "gate",
        "report",
        "rules",
        "validate-pipeline",
        "selftest",
    }
    assert used <= known, "README 点名了不存在的子命令：%s" % sorted(used - known)


def test_readme_report_example_has_required_expected_flag():
    """`report` 的 `--expected` 是必填（D19）；README 的示例不能漏它。"""
    text = _readme_text()
    report_lines = [tokens for tokens in _commands(text) if tokens[:2] == ["tripwire", "report"]]
    assert report_lines, "README 里没有 `tripwire report` 示例"
    for tokens in report_lines:
        assert "--expected" in tokens, "README 的 `report` 示例缺 `--expected`（它必填）：%s" % tokens
