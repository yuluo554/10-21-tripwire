"""退出码：唯一单点定义（语义文本定义在 `data/README.md` §6.3，代码只引用不复述）。

判定通道 = 0/1/2；用法通道 = 3。两者不混用：
- `argparse` 对未知子命令/缺必填参数是 `SystemExit(2)`，必须在 `cli.main()` 内捕获并**转成 3**，
  否则"参数写错"会被读成"门禁失败"。
"""

LOSSLESS = 0
LOSSY = 1
GATE_FAILED = 2
USAGE = 3

#: 判定通道（0/1/2）——只有这三个码参与"有损/无损"结论
VERDICT_CODES = (LOSSLESS, LOSSY, GATE_FAILED)

__all__ = ["LOSSLESS", "LOSSY", "GATE_FAILED", "USAGE", "VERDICT_CODES"]
