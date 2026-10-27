"""测试公共配置：src 布局下把 src 加入 sys.path（免可编辑安装）。"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
