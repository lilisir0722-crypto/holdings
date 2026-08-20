"""收盘记账、盘前推送。页面按钮和 `python -m holdings.jobs close|open` 都走这里。

crontab 示例（本机，工作日）：
  35 15 * * 1-5  cd /path/to/holdings && PYTHONPATH=src .venv/bin/python -m holdings.jobs close
  25 8 * * 1-5   cd /path/to/holdings && PYTHONPATH=src .venv/bin/python -m holdings.jobs open

盘前推送走 Server 酱（环境变量 SERVERCHAN_SENDKEY）；没配 key 就只写日志+标准输出。
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

from holdings.log import get_logger
from holdings.market import fetch_all
from holdings.pipeline import persist_run, run_tech
from holdings.store import Store

log = get_logger("jobs")


def _sendkey() -> str:
    return (os.environ.get("SERVERCHAN_SENDKEY") or os.environ.get("SCKEY") or "").strip()


def push_wechat(title: str, body: str, sendkey: str | None = None) -> bool:
    """Server 酱 SCT。失败打日志，不抛。"""
    key = (sendkey if sendkey is not None else _sendkey()).strip()
    if not key:
        log.info("未配置 SERVERCHAN_SENDKEY，推送只打到日志")
        log.info("%s\n%s", title, body)
        return False
    url = f"https://sctapi.ftqq.com/{key}.send"
    data = urllib.parse.urlencode({"title": title[:32], "desp": body}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
        if raw.get("code") not in (0, None) and raw.get("errno") not in (0, None):
            log.warning("Server 酱返回异常：%s", raw)
            return False
        log.info("盘前推送已发出：%s", title)
        return True
    except Exception as exc:
        log.warning("盘前推送失败：%s", exc)
        return False


def _plan_lines(run) -> list[str]:
    lines = [f"### {run.name} `{run.code}`"]
    if run.error:
        lines.append(f"失败：{run.error}")
        return lines
    report = run.report
    if report:
        lines.append(f"规则：{report.stance}")
        if report.overseas and report.overseas.ok:
            lines.append(f"外部：{report.overseas.title}")
    plan = run.plan
    if plan and plan.has:
        defs = " → ".join(f"{d.level:.3f}（{d.label}）" for d in plan.defenses)
        lines.append(f"防守：{defs}")
        if plan.confirm:
            lines.append(plan.confirm)
        for p in plan.principles[:3]:
            lines.append(f"- {p}")
    return lines


def job_close(store: Store) -> dict:
    """刷新行情后，给每只持仓跑完整分析并记快照。"""
    holdings = store.list()
    try:
        quotes, market = fetch_all(holdings)
        store.save_quotes(quotes)
        store.save_market(market)
    except Exception as exc:
        log.warning("收盘记账刷新行情失败，继续用已有报价：%s", exc)
        holdings = store.list()
    results = []
    for h in holdings:
        run = run_tech(store, h, holdings, mode="full")
        wrote = persist_run(run, h, source="close")
        results.append(
            {
                "code": h.code,
                "name": run.name,
                "wrote": wrote,
                "error": run.error,
                "stance": run.report.stance if run.report else "",
            }
        )
    log.info("收盘记账完成，%d 只", len(results))
    return {"ok": True, "kind": "close", "items": results}


def job_open(store: Store) -> dict:
    """盘前：预案+外部参照，推微信。不跑 LLM。"""
    holdings = store.list()
    runs = [run_tech(store, h, holdings, mode="plan") for h in holdings]
    today = datetime.now().strftime("%m-%d")
    chunks: list[str] = [f"盘前 {today}（规则预案，没跑说明）"]
    overseas_titles = []
    for run in runs:
        if run.report and run.report.overseas and run.report.overseas.ok:
            overseas_titles.append(run.report.overseas.title)
        chunks.extend(_plan_lines(run))
        chunks.append("")
    # 标题取第一条外部参照，没有就用「盘前」
    title = f"盘前 {today}"
    if overseas_titles:
        title = f"盘前 {today} · {overseas_titles[0][:18]}"
    body = "\n".join(chunks).strip()
    pushed = push_wechat(title, body)
    return {
        "ok": True,
        "kind": "open",
        "pushed": pushed,
        "title": title,
        "body": body,
        "items": [{"code": r.code, "name": r.name, "error": r.error} for r in runs],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    p = argparse.ArgumentParser(description="持仓定时任务：close 收盘记账，open 盘前推送")
    p.add_argument("job", choices=["close", "open"])
    p.add_argument(
        "--data",
        default=str(Path.cwd() / "data" / "holdings.json"),
        help="holdings.json 路径",
    )
    args = p.parse_args(argv)
    store = Store(Path(args.data))
    if args.job == "close":
        out = job_close(store)
        for it in out["items"]:
            mark = "已记" if it["wrote"] else ("失败" if it["error"] else "未变")
            print(f"{it['code']} {mark} {it.get('stance') or it.get('error') or ''}")
    else:
        out = job_open(store)
        print(out["title"])
        print(out["body"])
        print("已推送" if out["pushed"] else "未推送（没配 SERVERCHAN_SENDKEY 或接口失败）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
