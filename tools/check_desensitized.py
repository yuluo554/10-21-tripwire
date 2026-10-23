#!/usr/bin/env python3
"""脱敏门（发布前必跑）：本机盘符路径 / 本机用户名 / 回环代理端口。

为什么是常驻门而不是发布前 grep 一次：这些字面量在每一次续接对话里都会被重新追加
（HANDOFF 的环境坑章节尤其），发布之后任何一次改动都可能把它们带回来。

四条规则（与 ai-tool-project-sprint `references/templates/check-desensitized.mjs` 同构）：
  R1 盘符绝对路径   D:/ProgramData/... / C:\\Users\\...（`<user>` 这类占位符放行）
  R2 MSYS 用户路径  /c/Users/<name>/...
  R3 本机用户名     ASUS
  R4 回环代理端口   127.0.0.1:<port>
退出码：0 零命中 / 1 有命中 / 2 用法错误。

变异验证（每条规则一组，必须逐组变红）：
  V1 任意文档写 `D:/ProgramData/x`        -> R1
  V2 任意文档写 `C:\\Users\\realname\\x`  -> R1 + R3
  V3 任意文档写 `/c/Users/realname/x`     -> R2
  V4 任意文档写 `127.0.0.1:7897`          -> R4
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 自豁免：门的规则本身、以及变异脚本的注入样本，都必须写出被判据禁止的字面量。
# 豁免面显式列在这里（不按前缀模糊跳过），并把份数打进结论行。
SELF_EXEMPT = ("tools/check_desensitized.py", "tools/verify_gate_mutations.py")

SKIP_DIRS = {".git", ".tmp", "dist", "dist-release", "node_modules", ".cache", ".venv", "venv", "build", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "runs", "out", "update"}
# `update/` = 迭代交接物（诊断 / 路线 / 提示词 / 执行记录）。它与 `.tmp/`、`runs/` 同族：
# 不是交付面、已进 .gitignore、发布树里根本不存在。而它的**用途**就是记录本机路径与命令，
# 所以它必然命中 R1–R4——不排除就等于"门被自己的交接物判红"。
# ⚠ 排除的是**目录**，不是判据：同一条泄漏搬进 plan/ docs/ src/ 仍会被 R1–R4 抓到（见变异组 D1–D4）。
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".tar", ".exe", ".dll", ".pdf",
    ".woff", ".woff2", ".pyc", ".so", ".xlsx", ".xls", ".xlsm",
}

RULES = [
    ("drive-absolute-path", re.compile(r"\b[A-Za-z]:[\\/](?:ProgramData|Users|zcode|repos?|projects?)[\\/](?!<)")),
    ("msys-user-path", re.compile(r"/[a-z]/Users/(?!<)[A-Za-z0-9._-]+/")),
    ("host-username", re.compile(r"\bASUS\b")),
    ("loopback-proxy", re.compile(r"\b127\.0\.0\.1:\d{2,5}\b")),
]


def walk(directory):
    for entry in sorted(os.scandir(directory), key=lambda e: e.name):
        if entry.name == ".git":  # worktree 里 .git 是文件，两态一起挡
            continue
        if entry.is_dir(follow_symlinks=False):
            if entry.name in SKIP_DIRS:
                continue
            yield from walk(entry.path)
            continue
        if not entry.is_file(follow_symlinks=False):
            continue
        _, ext = os.path.splitext(entry.name)
        if ext.lower() in SKIP_EXTS:
            continue
        yield entry.path


def main():
    if len(sys.argv) > 1:
        sys.stderr.write("check_desensitized: unknown argument %s\n" % sys.argv[1])
        return 2

    hits = []
    scanned = 0
    for path in walk(ROOT):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if rel in SELF_EXEMPT:
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except (UnicodeDecodeError, OSError):
            continue
        if "\u0000" in text:
            continue
        scanned += 1
        for lineno, line in enumerate(text.split("\n"), start=1):
            for rule_id, pattern in RULES:
                if pattern.search(line):
                    hits.append("%s:%d: [%s] %s" % (rel, lineno, rule_id, line.strip()[:160]))

    if hits:
        sys.stdout.write(
            "脱敏门：%d 处命中（扫了 %d 个文本文件，豁免 %d 份: %s）\n"
            % (len(hits), scanned, len(SELF_EXEMPT), ", ".join(SELF_EXEMPT))
        )
        for hit in hits:
            sys.stdout.write("FAIL  %s\n" % hit)
        return 1
    sys.stdout.write(
        "脱敏门：扫了 %d 个文本文件，0 命中（豁免 %d 份: %s）\n"
        % (scanned, len(SELF_EXEMPT), ", ".join(SELF_EXEMPT))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
