# 持仓技术指标弹层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 点击已持仓名称弹出技术指标分析：全算、有信号展开解读、其余折叠、顶部带依据的总倾向。

**Architecture:** 纯函数 `tech.py` 吃日 K → 指标值与信号/解读/总倾向；`market` 复用拉 K；`web` 提供 `GET /tech/{code}`（仅已持仓）与页面弹层 JS。

**Tech Stack:** FastAPI、Jinja2、easy-tdx（K 线 + compute_indicators / MyTT）、pytest。

---

### Task 1: 信号与总倾向纯函数

**Files:**
- Create: `src/holdings/tech.py`
- Test: `tests/test_tech.py`

- [ ] 写失败测试：MACD 金叉 → 有信号；多空打架 → 更宜观望；无「立即买入」
- [ ] 实现 `analyze_kline(df) -> TechReport`（signals / quiet / stance）
- [ ] 测试通过

### Task 2: 行情取 K + 路由

**Files:**
- Modify: `src/holdings/market.py`
- Modify: `src/holdings/web.py`

- [ ] `fetch_kline(code, kind)` 
- [ ] `GET /tech/{code}` 校验持仓，返回 HTML 片段或 JSON
- [ ] 未持仓 404；无 K 线明确文案

### Task 3: 页面弹层

**Files:**
- Modify: `src/holdings/templates/index.html`

- [ ] 名称可点 → fetch `/tech/{code}` → 弹层
- [ ] 有信号展开、其余折叠、关闭

### Task 4: 验收

- [ ] pytest 全绿
- [ ] 本机点半导体设备ETF 能出弹层
