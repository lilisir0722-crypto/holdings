import logging
from pathlib import Path

import pytest

import holdings.log as logmod
from holdings.log import get_logger


def _our_handlers(root):
    return [h for h in root.handlers if getattr(h, "_holdings_own", False)]


@pytest.fixture(autouse=True)
def fresh_root(tmp_path, monkeypatch):
    """只摘掉我们自己的 handler（pytest 会往 logger 上加它自己的，不能动）。"""
    root = logging.getLogger("holdings")
    for h in _our_handlers(root):
        root.removeHandler(h)
    monkeypatch.setattr(root, "_holdings_ready", False, raising=False)
    monkeypatch.setattr(logmod, "LOG_DIR", tmp_path)
    yield tmp_path
    for h in _our_handlers(root):
        root.removeHandler(h)


def test_writes_to_file_and_console(fresh_root, capsys):
    log = get_logger("web")
    log.info("测试消息 %s", "甲")
    for h in _our_handlers(logging.getLogger("holdings")):
        h.flush()
    content = (fresh_root / "holdings.log").read_text(encoding="utf-8")
    assert "测试消息 甲" in content
    assert "INFO holdings.web" in content
    assert "测试消息 甲" in capsys.readouterr().err  # 控制台走 stderr


def test_handlers_not_duplicated(fresh_root):
    get_logger("a")
    get_logger("b")
    root = logging.getLogger("holdings")
    assert len(_our_handlers(root)) == 2  # 文件 + 控制台，重复取 logger 不叠加


def test_log_dir_failure_does_not_break(monkeypatch):
    root = logging.getLogger("holdings")
    for h in _our_handlers(root):
        root.removeHandler(h)
    monkeypatch.setattr(root, "_holdings_ready", False, raising=False)
    monkeypatch.setattr(logmod, "LOG_DIR", Path("/proc/不可能存在"))
    log = get_logger("x")  # 文件出口建不起来时只剩控制台，不抛异常
    log.info("仍然能记")
    assert len(_our_handlers(root)) == 1
