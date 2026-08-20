from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

from holdings.log import get_logger

log = get_logger("llm")

_CACHE: OrderedDict[tuple, tuple[str, str]] = OrderedDict()
_CACHE_MAX = 64


def clear_explain_cache() -> None:
    _CACHE.clear()


def _cache_key(payload: dict[str, Any], model: str) -> tuple:
    code = str(payload.get("代码") or "")
    price = payload.get("现价")
    if isinstance(price, (int, float)):
        price_s = f"{float(price):.4f}"
    else:
        price_s = str(price)
    return (model, code, price_s)


SYSTEM_PROMPT = (
    "你是帮助个人投资者看懂持仓现状的助手。"
    "给你的依据是数据和事实（数值、涨跌幅、点位、算法测量结果），不是现成的结论；"
    "请自己根据这些数据做论证，再给出偏买、偏卖或观望的判断。"
    "判断必须先写论证：用到了哪些数据、这些数据在说什么、和成本/现金怎么连起来。"
    "不要只丢一句「立即买入」或「立即卖出」当全文。"
    "不要编造没有的数据。用白话。不能保证后面还会不会继续亏。"
    "控制在 220 字以内。"
)


def explain_tech(payload: dict[str, Any]) -> tuple[str | None, str]:
    """Call DeepSeek to narrate tech context. Returns (text, status).

    status: skipped | ok | error
    """
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        return None, "skipped"

    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat").strip()
    key = _cache_key(payload, model)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached
    url = f"{base}/v1/chat/completions"

    system = SYSTEM_PROMPT
    user = "依据如下（JSON）：\n" + json.dumps(payload, ensure_ascii=False)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = (
            raw.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not text:
            log.warning("DeepSeek 返回空（耗时 %.1fs）", time.monotonic() - t0)
            return None, "error"
        _CACHE[key] = (text, "ok")
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
        log.info(
            "说明生成成功（%s，%d 字，耗时 %.1fs）",
            payload.get("代码") or "?",
            len(text),
            time.monotonic() - t0,
        )
        return text, "ok"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        log.warning(
            "DeepSeek 调用失败（%s，耗时 %.1fs）：%s",
            payload.get("代码") or "?",
            time.monotonic() - t0,
            exc,
        )
        return f"模型没写出来：{exc}", "error"
