# 技术页：资金 / 板块 / 量价信号 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 点持仓名称进入独立技术页（非弹层），并按 A→B→C 加上资金流向、所属板块摘要、OBV/MFI/DMI/VR 量价信号。

**Architecture:** `GET /tech/{code}` 返回整页 HTML；`market.fetch_market_context` 在同一 MacClient 连接上取资金+板块；`tech` 解析成 `CapitalBlock` / `BoardBlock` 并扩展量价 handlers；总倾向仍由技术信号+成本/现金主导，A/B 只追加依据句。

**Tech Stack:** FastAPI、Jinja2、easy-tdx MacClient、pytest。

**Spec:** `docs/superpowers/specs/2026-08-16-market-context-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `src/holdings/templates/index.html` | 名称链到 `/tech/{code}`；删除 modal DOM/JS |
| `src/holdings/templates/tech.html` | 整页壳（样式复用 index 变量）+ 返回持仓 + 资金/板块节 |
| `src/holdings/market.py` | `fetch_market_context(client, code)` → 原始资金 DF / 板块列表+summary |
| `src/holdings/tech.py` | `CapitalBlock`/`BoardBlock`、`summarize_capital`/`pick_boards`、OBV/MFI/DMI/VR handlers、`TechReport` 新字段 |
| `src/holdings/web.py` | `/tech` 拉 context、挂到 report、整页 TemplateResponse |
| `tests/test_tech.py` | 量价信号 + capital/board 纯函数 |
| `tests/test_market_context.py` | 资金/板块选择与空数据处理（假 DataFrame） |

---

### Task 0: 弹层改为整页

**Files:**
- Modify: `src/holdings/templates/index.html`
- Modify: `src/holdings/templates/tech.html`
- Modify: `src/holdings/web.py`（若需；路由已存在）

- [ ] **Step 1: 持仓名称改为普通链接**

在 `index.html` 把：

```html
<a class="pos-name" href="#" data-tech="{{ p.snapshot.code }}">{{ p.snapshot.name }}</a>
```

改成：

```html
<a class="pos-name" href="/tech/{{ p.snapshot.code }}">{{ p.snapshot.name }}</a>
```

删除整块 `#tech-modal` 与其后 `<script>…</script>`；删除仅给弹层用的 `.modal-*` / `.tech-loading` CSS（技术页样式改放到 `tech.html`）。

把文案「总判断和技术弹层」改成「总判断和技术页」。

- [ ] **Step 2: `tech.html` 改成完整 HTML 页**

包一层与 `index.html` 相同的 `:root` / `body` / `.wrap` / `.lede` / `.evidence` / 技术相关 class；页顶：

```html
<p class="meta"><a href="/">← 返回持仓</a></p>
```

保留现有 stance / 走势 / 说明 / 有信号 / 其余结构（后续任务再插资金、板块）。

- [ ] **Step 3: 本机冒烟**

重启 `uv run holdings`，点一只持仓名称应整页打开 `/tech/…`，能返回持仓；不应再出现遮罩。

- [ ] **Step 4: Commit**（若使用者要求提交时再做）

```bash
git add src/holdings/templates/index.html src/holdings/templates/tech.html
git commit -m "$(cat <<'EOF'
feat: open tech analysis as a full page instead of modal

EOF
)"
```

---

### Task 1: 资金块纯函数 + market 拉取

**Files:**
- Modify: `src/holdings/tech.py`
- Modify: `src/holdings/market.py`
- Create: `tests/test_market_context.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_market_context.py
import pandas as pd
from holdings.tech import summarize_capital


def test_summarize_capital_latest_main_net():
    df = pd.DataFrame(
        [
            {"date": "2026-08-14", "main_net": -1e7, "small_net": 2e6},
            {"date": "2026-08-15", "main_net": 3e7, "small_net": -5e6},
        ]
    )
    block = summarize_capital(df)
    assert block.ok
    assert "主力" in block.title or "净流入" in block.title
    assert any("3" in e or "3000" in e or "流入" in e for e in block.evidence)
    assert "立即买入" not in block.title


def test_summarize_capital_empty():
    block = summarize_capital(pd.DataFrame())
    assert not block.ok
    assert "没有资金流向" in block.title or "暂无" in block.title
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_market_context.py::test_summarize_capital_latest_main_net -v`  
Expected: FAIL（`summarize_capital` 未定义）

- [ ] **Step 3: 实现数据结构与纯函数**

在 `tech.py`：

```python
@dataclass
class CapitalBlock:
    title: str
    evidence: list[str] = field(default_factory=list)
    ok: bool = False
    summary_line: str | None = None  # 可进 stance_evidence


@dataclass
class BoardBlock:
    title: str
    evidence: list[str] = field(default_factory=list)
    ok: bool = False
    summary_line: str | None = None


# TechReport 增加:
#   capital: CapitalBlock | None = None
#   boards: list[BoardBlock] = field(default_factory=list)
```

`summarize_capital(df)`：按 `date` 排序取最后一行；读 `main_net` / `small_net`（元→白话「约 X 亿/万」）；`summary_line` 如「最近一日主力净流入为正/负」。空 DF → `ok=False`。

金额格式辅助：

```python
def _fmt_money(x: float) -> str:
    ax = abs(x)
    if ax >= 1e8:
        return f"{x/1e8:.2f} 亿"
    if ax >= 1e4:
        return f"{x/1e4:.0f} 万"
    return f"{x:.0f} 元"
```

- [ ] **Step 4: market 拉取**

```python
def fetch_market_context(client, code: str) -> dict:
    """Return raw pieces; never raise for soft failures."""
    market = _market_enum(code)
    out = {"capital_df": None, "belong_df": None, "board_summaries": [], "error": None}
    try:
        out["capital_df"] = client.get_capital_flow(market, code)
    except Exception as exc:
        out["error"] = str(exc)
    try:
        out["belong_df"] = client.get_belong_board(market, code)
    except Exception as exc:
        out["error"] = (out["error"] or "") + f"; belong: {exc}"
    return out
```

板块 summary 在 Task 2 补全；此处先只拉 belong + capital。

- [ ] **Step 5: 测试通过**

Run: `uv run pytest tests/test_market_context.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**（若要求）

```bash
git add src/holdings/tech.py src/holdings/market.py tests/test_market_context.py
git commit -m "$(cat <<'EOF'
feat: summarize capital flow for tech page

EOF
)"
```

---

### Task 2: 板块选择 + summary + 接线模板

**Files:**
- Modify: `src/holdings/tech.py`
- Modify: `src/holdings/market.py`
- Modify: `src/holdings/web.py`
- Modify: `src/holdings/templates/tech.html`
- Modify: `tests/test_market_context.py`

- [ ] **Step 1: 写失败测试**

```python
def test_pick_boards_prefers_few():
    from holdings.tech import pick_boards

    belong = pd.DataFrame(
        [
            {"board_code": "880001", "board_name": "半导体", "board_type": 2},
            {"board_code": "880002", "board_name": "机器人概念", "board_type": 3},
            {"board_code": "880003", "board_name": "杂鱼", "board_type": 9},
        ]
    )
    summaries = {
        "880001": {
            "member_count": 40,
            "amount": 1e10,
            "main_net_amount": -2e8,
            "main_net_3d": -1e8,
            "main_net_5d": 5e7,
            "up_count": 10,
            "down_count": 20,
        }
    }
    blocks = pick_boards(belong, summaries, limit=2)
    assert 1 <= len(blocks) <= 2
    assert blocks[0].ok
    assert "半导体" in blocks[0].title
    assert any("主力" in e for e in blocks[0].evidence)
```

`board_type` 数值以 easy-tdx 实际列为准；若列名是字符串类型名，用名称含「行业」优先、其次「概念」，否则按表顺序取前 2。

- [ ] **Step 2: 实现 `pick_boards` + 扩展 `fetch_market_context`**

对选中的每个 `board_code` 调 `client.get_board_summary(board_code)`；捕获异常则该板 `ok=False` 文案「板块暂无」。去掉返回里的巨大 `members` DataFrame，只留标量字段再传入 `pick_boards`。

- [ ] **Step 3: `web.py` `/tech/{code}`**

在已有 `open` 路径上：

```python
with open_mac_client() as client:
    kdf = ...  # 或保持 fetch_kline；优先同连接：在 fetch_kline 旁加 client 版
    ctx = fetch_market_context(client, code)
```

为少开连接：给 `fetch_kline` 增加可选 `client=`，无则自己 `open_mac_client`。同一次连接：`kline` + `fetch_market_context`。

组装：

```python
report.capital = summarize_capital(ctx.get("capital_df"))
report.boards = pick_boards(ctx.get("belong_df"), ctx.get("board_summaries") or {})
for line in [report.capital.summary_line if report.capital else None] + [
    b.summary_line for b in report.boards
]:
    if line:
        report.stance_evidence.append(line)
```

（在 `enrich_with_account` 之后或之前追加均可，保持依据可读。）

LLM payload 可附带 `"资金"` / `"板块"` 摘要字符串。

- [ ] **Step 4: 模板**

在走势与说明之后、「有信号」之前：

```html
{% if report.capital %}
<section class="tech-group">
  <h4>资金</h4>
  <p><strong>{{ report.capital.title }}</strong></p>
  <ul class="evidence">{% for e in report.capital.evidence %}<li>{{ e }}</li>{% endfor %}</ul>
</section>
{% endif %}
{% if report.boards %}
<section class="tech-group">
  <h4>板块</h4>
  {% for b in report.boards %}
  <article class="tech-item">
    <strong>{{ b.title }}</strong>
    <ul class="evidence">{% for e in b.evidence %}<li>{{ e }}</li>{% endfor %}</ul>
  </article>
  {% endfor %}
</section>
{% endif %}
```

无数据时仍渲染一块 `title` 为「这只暂时没有资金流向」等（`summarize_capital` / `pick_boards` 保证至少一条说明）。

- [ ] **Step 5: 测试通过**

Run: `uv run pytest tests/test_market_context.py tests/test_tech.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**（若要求）

```bash
git add src/holdings/tech.py src/holdings/market.py src/holdings/web.py src/holdings/templates/tech.html tests/test_market_context.py
git commit -m "$(cat <<'EOF'
feat: show board summary and capital on tech page

EOF
)"
```

---

### Task 3: OBV / MFI / DMI / VR 有信号规则

**Files:**
- Modify: `src/holdings/tech.py`
- Modify: `tests/test_tech.py`

- [ ] **Step 1: 写失败测试**

```python
def test_mfi_overbought_is_signal():
    series = {"MFI": [50.0, 85.0], "close": [1.0, 1.02]}
    report = analyze_indicators(series)
    mfi = next(s for s in report.signals if s.name == "MFI")
    assert mfi.side == "空"
    assert "偏热" in mfi.reading or "超买" in mfi.reading


def test_obv_diverges_from_price_is_signal():
    # 价涨、OBV 明显走低
    series = {
        "close": [1.0, 1.01, 1.02, 1.03, 1.05, 1.08],
        "OBV": [100.0, 99.0, 98.0, 97.0, 96.0, 90.0],
    }
    report = analyze_indicators(series)
    obv = next(s for s in report.signals if s.name == "OBV")
    assert "背离" in obv.reading or "量价" in obv.reading


def test_dmi_pdi_cross_up_is_bullish():
    series = {
        "DMI_PDI": [20.0, 28.0],
        "DMI_MDI": [25.0, 22.0],
        "DMI_ADX": [18.0, 26.0],
        "close": [1.0, 1.02],
    }
    report = analyze_indicators(series)
    dmi = next(s for s in report.signals if s.name == "DMI")
    assert dmi.side == "多"
    assert dmi.signal


def test_vr_extreme_is_signal():
    series = {"VR": [100.0, 460.0], "close": [1.0, 1.02]}
    report = analyze_indicators(series)
    vr = next(s for s in report.signals if s.name == "VR")
    assert vr.signal
    assert "偏热" in vr.reading or "偏高" in vr.reading
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_tech.py::test_mfi_overbought_is_signal tests/test_tech.py::test_obv_diverges_from_price_is_signal -v`  
Expected: FAIL

- [ ] **Step 3: 实现 handlers 并挂入 `_HANDLERS`；从 `_QUIET_MAP` 去掉已处理前缀以免重复**

规则（写死）：

| 指标 | 有信号 |
|------|--------|
| MFI | >80 空偏热；<20 多偏冷 |
| VR | >450 偏热；<40 偏冷（常见经验区） |
| DMI | PDI/MDI 金叉或死叉；或 ADX≥25 且 PDI>MDI / 反之 |
| OBV | 近 5 日 close 变化方向与 OBV 变化方向相反，且 \|ΔOBV\| 相对明显 |

`INDICATOR_ABOUT` 为四者补白话。

- [ ] **Step 4: 测试全绿**

Run: `uv run pytest tests/test_tech.py tests/test_market_context.py -v`  
Expected: PASS

再跑：`uv run pytest -q`  
Expected: 全绿

- [ ] **Step 5: Commit**（若要求）

```bash
git add src/holdings/tech.py tests/test_tech.py
git commit -m "$(cat <<'EOF'
feat: add OBV MFI DMI VR signal readings

EOF
)"
```

---

### Task 4: 验收

- [ ] 重启服务；点持仓名称 → 整页；有返回；有资金/板块节（或明确暂无）
- [ ] 有信号中可见量价类（若当日触发）
- [ ] 断网或接口失败时指标/走势仍在
- [ ] 无「立即买入/卖出」
- [ ] `uv run pytest -q` 全绿

---

## Spec coverage check

| Spec 项 | Task |
|---------|------|
| 整页非弹层 | Task 0 |
| A 资金 | Task 1 |
| B 板块 | Task 2 |
| C OBV/MFI/DMI/VR | Task 3 |
| A/B 失败不拖垮 | Task 1–2 soft fail |
| A/B 不单独改买卖口令 | 只 `summary_line` 进依据 |
| 异动/缠论不做 | 无对应 task |
