"""运行日志：data/logs/holdings.log（滚动保留 3 份）+ 控制台。

和分析快照（journal）互补：journal 记"当时看到了什么数据"，这里记"系统做了什么、
哪一步失败了、有多慢"。抓取失败这类以前被静默吞掉的情况，现在都留痕。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_ROOT = "holdings"


def get_logger(name: str) -> logging.Logger:
    """取 holdings 命名空间下的 logger；首次调用时配置文件/控制台两个出口。

    配置与否看自己的标记（_holdings_ready），不看 handlers 是否为空——
    pytest 等环境会往 logger 上加它们自己的 handler，不能当成"已配置"。
    """
    root = logging.getLogger(_ROOT)
    if not getattr(root, "_holdings_ready", False):
        root.setLevel(logging.INFO)
        root.propagate = False
        fmt = logging.Formatter(_FORMAT)
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                LOG_DIR / "holdings.log",
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            fh.setFormatter(fmt)
            fh._holdings_own = True  # type: ignore[attr-defined]
            root.addHandler(fh)
        except OSError:
            pass  # 日志目录建不起来也不许影响主流程
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        sh._holdings_own = True  # type: ignore[attr-defined]
        root.addHandler(sh)
        root._holdings_ready = True  # type: ignore[attr-defined]
    return root.getChild(name) if not name.startswith(_ROOT) else logging.getLogger(name)
