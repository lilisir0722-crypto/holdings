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

CHAT_SYSTEM = (
    "你是帮助个人投资者看懂持仓现状的助手。"
    "每次提问都会附上当前详情页的数据（数值、涨跌幅、点位、算法测量结果），不是现成的结论。"
    "请根据这些数据和用户的问题回答。不要编造没有的数据。"
    "用 Markdown 排版：小标题、列表、加粗重点；需要分层时分段写，不要挤成一段。"
    "不能保证后面还会不会继续亏。"
)

CHAT_MODELS = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash-vision-exp",
)


def resolve_model(name: str | None) -> str:
    raw = (name or "").strip()
    if raw in CHAT_MODELS:
        return raw
    cfg = _settings()
    if cfg is not None and cfg[2] in CHAT_MODELS:
        return cfg[2]
    return "deepseek-v4-flash"


def _settings() -> tuple[str, str, str] | None:
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        return None
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash").strip()
    return api_key, base, model


def _complete(
    messages: list[dict], *, code: str, model: str | None = None
) -> tuple[str | None, str, str]:
    cfg = _settings()
    if cfg is None:
        return None, "skipped", ""
    api_key, base, _env_model = cfg
    use_model = resolve_model(model)
    url = f"{base}/v1/chat/completions"
    body = {
        "model": use_model,
        "messages": messages,
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
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        msg = raw.get("choices", [{}])[0].get("message", {}) or {}
        text = str(msg.get("content") or "").strip()
        reasoning = str(msg.get("reasoning_content") or "").strip()
        if not text and reasoning:
            text, reasoning = reasoning, ""
        if not text:
            log.warning("DeepSeek 返回空（耗时 %.1fs）", time.monotonic() - t0)
            return None, "error", ""
        log.info(
            "模型回复成功（%s，%s，%d 字，耗时 %.1fs）",
            code or "?",
            use_model,
            len(text),
            time.monotonic() - t0,
        )
        return text, "ok", reasoning
    except Exception as exc:
        log.warning(
            "DeepSeek 调用失败（%s，耗时 %.1fs）：%s",
            code or "?",
            time.monotonic() - t0,
            exc,
        )
        return f"模型没写出来：{exc}", "error", ""


def explain_tech(payload: dict[str, Any]) -> tuple[str | None, str]:
    """Call DeepSeek to narrate tech context. Returns (text, status).

    status: skipped | ok | error
    """
    cfg = _settings()
    if cfg is None:
        return None, "skipped"
    _, _, model = cfg
    key = _cache_key(payload, model)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached
    user = "依据如下（JSON）：\n" + json.dumps(payload, ensure_ascii=False)
    text, status, _reason = _complete(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        code=str(payload.get("代码") or ""),
    )
    if status == "ok" and text:
        _CACHE[key] = (text, "ok")
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return text, status


def chat_with_page(
    payload: dict[str, Any],
    history: list[dict] | None,
    message: str,
    model: str | None = None,
) -> tuple[str | None, str, str]:
    """多轮对话。每轮 system 都带上当前详情页数据。"""
    text = (message or "").strip()
    if not text:
        return "先写一句要问的。", "error", ""
    messages: list[dict] = [
        {
            "role": "system",
            "content": CHAT_SYSTEM
            + "\n\n当前详情页数据（JSON）：\n"
            + json.dumps(payload, ensure_ascii=False),
        }
    ]
    for item in (history or [])[-20:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})
    return _complete(messages, code=str(payload.get("代码") or ""), model=model)
