from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


SYSTEM_PROMPT = (
    "你是帮助个人投资者看懂持仓现状的助手。"
    "只根据用户给出的依据说话，不要编造没有的行情或数字。"
    "可以给出偏买或偏卖的判断，但必须先写论证：用到了哪些依据、这些依据在说什么、和成本/现金怎么连起来。"
    "不要只丢一句「立即买入」或「立即卖出」当全文。"
    "用白话。不能保证后面还会不会继续亏。"
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
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        text = (
            raw.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not text:
            return None, "error"
        return text, "ok"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        return f"模型没写出来：{exc}", "error"
