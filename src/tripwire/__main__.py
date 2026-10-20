"""`python -m tripwire` 入口（与 `tripwire` console script 同语义）。"""

from __future__ import annotations

import sys

from tripwire.cli import main

if __name__ == "__main__":
    sys.exit(main())
