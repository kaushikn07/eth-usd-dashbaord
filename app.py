"""
ETHUSD Quant Dashboard — Streamlit frontend
Fetches live data on every page refresh via collector logic.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone, timedelta
import sys
import os

# ── page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ETHUSD Quant Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── dark theme CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* global dark bg */
html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
    background-color: #0d0f12 !important;
}
[data-testid="stMain"] { background-color: #0d0f12; }
[data-testid="block-container"] { background-color: #0d0f12; padding-top: 1rem; }

/* sidebar */
[data-testid="stSidebar"] { background-color: #151820; }

/* metric cards */
[data-testid="stMetric"] {
    background: #151820;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 14px 16px;
}
[data-testid="stMetricLabel"] { color: #7a8099 !important; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
[data-testid="stMetricValue"] { color: #e8eaf0 !important; font-size: 22px; font-weight: 700; }
[data-testid="stMetricDelta"] { font-size: 11px; }

/* tabs */
[data-testid="stTabs"] button { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #7a8099; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #60a5fa; border-bottom-color: #60a5fa; }

/* dataframe */
[data-testid="stDataFrame"] { background: #151820; }
.stDataFrame thead th { background: #1c2030 !important; color: #7a8099 !important; font-size: 10px; text-transform: uppercase; }
.stDataFrame tbody tr:hover { background: rgba(255,255,255,0.02); }

/* text */
p, label, li { color: #e8eaf0 !important; }
h1, h2, h3, h4 { color: #ffffff !important; }
code { color: #60a5fa !important; background: rgba(96,165,250,0.1) !important; }

/* buttons */
[data-testid="stButton"] > button {
    background: #60a5fa; color: #000; font-weight: 700;
    border: none; border-radius: 5px;
}
[data-testid="stButton"] > button:hover { background: #93c5fd; color: #000; border: none; }

/* alerts / info boxes */
[data-testid="stAlert"] { border-radius: 8px; }

/* divider */
hr { border-color: rgba(255,255,255,0.07); }
</style>
""", unsafe_allow_html=True)

IST = timezone(timedelta(hours=5, minutes=30))

# ── load data (runs collector on every refresh) ─────────────────────────────
@st.cache_data(ttl=0)   # ttl=0 → never cache; always re-run on page refresh
def load_data():
    from collector import build_dataset
    return build_dataset()

# ── helpers ─────────────────────────────────────────────────────────────────
def fmt(v, dec=2, sign=False):
    if v is None or (isinstance(v, float) and (v != v)):
        return "—"
    n = f"{float(v):.{dec}f}"
    return (f"+{n}" if float(v) > 0 else n) if sign else n

def dir_color(v):
    if v is None: return "gray"
    return "#22c55e" if v > 0 else "#ef4444"

def stair_label(r):
    d = r.get("direction", 0) or 0
    clv = r.get("clv", 0) or 0
    eff = r.get("eff_regime", "")
    if d < -80:
        return "Bear Impulse", "#ef4444"
    if d > 80 and clv > 0.65:
        return "Bull Signal", "#2dd4bf"
    if d > 15:
        return "Bull Attempt", "#22c55e"
    if d < -15 and d >= -80:
        return "Rest / Compress", "#60a5fa"
    if abs(d) < 15:
        if eff == "Rotational":
            return "Flat / Exhaust", "#f59e0b"
        return "Fading", "#7a8099"
    return "Mixed", "#a78bfa"

def signal_state(rows):
    if len(rows) < 2:
        return "wait"
    def is_bull(r):
        return (
            (r.get("direction") or 0) > 30 and
            (r.get("clv") or 0) > 0.55 and
            (r.get("rvol") or 0) > 1.20 and
            r.get("eff_regime") in ("Trend", "Mixed") and
            r.get("atr_regime") != "Contracting"
        )
    def is_bear(r):
        return (
            (r.get("direction") or 0) < -40 and
            (r.get("clv") or 0) < 0.45 and
            (r.get("rvol") or 0) > 1.20
        )
    last2 = rows[-2:]
    if all(is_bull(r) for r in last2):
        return "bull"
    if all(is_bear(r) for r in last2):
        return "bear"
    return "wait"

def plotly_dark_layout(height=280):
    return dict(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#151820",
        font=dict(color="#7a8099", size=10, family="monospace"),
        margin=dict(l=0, r=0, t=20, b=0),
        xaxis=dict(gridcolor="rgba(255,255,255,0.04)", tickfont=dict(size=9)),
        yaxis=dict(gridcolor="rgba(255,255,255,0.06)", tickfont=dict(size=9)),
        showlegend=False,
    )

# ── fetch data ──────────────────────────────────────────────────────────────
with st.spinner("Pulling latest ETH data from Delta Exchange…"):
    try:
        dataset = load_data()
        rows    = dataset["rows"]
        latest  = dataset.get("latest", rows[-1] if rows else {})
        collected_at = dataset.get("collected_at", "—")
        data_error = None
    except Exception as e:
        data_error = str(e)
        rows, latest, collected_at = [], {}, "—"

df = pd.DataFrame(rows) if rows else pd.DataFrame()

# ── sidebar: window size ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    window = st.number_input("Window (days)", min_value=1, value=30, step=1)

last30 = rows[-window:] if len(rows) >= window else rows

# ── top bar ─────────────────────────────────────────────────────────────────
col_sym, col_mid, col_right = st.columns([3, 4, 3])
with col_sym:
    st.markdown("### 📊 ETHUSD.P")
    st.caption("Perpetual · Delta Exchange India · Daily")

with col_mid:
    ist_now = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    st.markdown(f"**{ist_now}**")
    st.caption(f"Data collected: {collected_at}")

with col_right:
    state = signal_state(rows)
    if state == "bull":
        st.success("🟢 BULL CONFIRMED")
    elif state == "bear":
        st.error("🔴 BEAR CONFIRMED")
    else:
        st.warning("⚠️ OBSERVATION — NO TRADE")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

if data_error:
    st.error(f"Failed to fetch data: {data_error}")
    st.stop()

st.divider()

# ── tabs ────────────────────────────────────────────────────────────────────
tab_ov, tab_analysis, tab_stair, tab_charts, tab_signal, tab_rsi = st.tabs([
    "Overview", "Daily Analysis", "Staircase", "Charts", "Signal State", "RSI Cloud"
])

# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_ov:
    if not latest:
        st.warning("No data available.")
    else:
        # row 1 metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latest Date",       latest.get("date", "—"), latest.get("dow", ""))
        c2.metric("Direction Score",   fmt(latest.get("direction"), 2, sign=True),
                  latest.get("eff_regime", "—"))
        c3.metric("CLV",               fmt(latest.get("clv"), 3),
                  latest.get("close_regime", "—"))
        c4.metric("RVOL",              fmt(latest.get("rvol"), 2),
                  latest.get("participation", "—") + " participation")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("ATR 14",            fmt(latest.get("atr14"), 2),
                  latest.get("atr_regime", "—"))
        c6.metric("Efficiency",        latest.get("eff_regime", "—"),
                  "R/ATR " + fmt(latest.get("range_atr"), 2))
        peak_bear = min(rows, key=lambda r: r.get("direction") or 0) if rows else {}
        peak_bull = max(rows, key=lambda r: r.get("direction") or 0) if rows else {}
        c7.metric("Peak Bear Day",     fmt(peak_bear.get("direction"), 1, sign=True),
                  peak_bear.get("date", "—"))
        c8.metric("Peak Bull Day",     fmt(peak_bull.get("direction"), 1, sign=True),
                  peak_bull.get("date", "—"))

        # alert box
        st.markdown("")
        if state == "bull":
            st.success("**↑ BULL CONFIRMED** — Two consecutive aligned bull days. Direction, CLV, and Efficiency all agree. The climb has started. Watch RVOL for crowd participation.")
        elif state == "bear":
            st.error("**↓ BEAR CONFIRMED** — Two consecutive aligned bear days. Sellers in control with volume. The staircase is descending.")
        else:
            st.warning(f"**⚠ Observation phase — no trade** — Latest: Direction {fmt(latest.get('direction'),2,True)}, CLV {fmt(latest.get('clv'),3)}, RVOL {fmt(latest.get('rvol'),2)}, {latest.get('eff_regime','—')} efficiency, ATR {latest.get('atr_regime','—')}. Need two consecutive days of full alignment before a trade.")

        # charts
        if last30:
            col_l, col_r = st.columns([2, 1])
            with col_l:
                st.markdown(f"##### Direction Score — last {window} days")
                labels = [r["date"][5:] for r in last30]
                vals   = [r.get("direction") or 0 for r in last30]
                colors = ["rgba(34,197,94,0.7)" if v >= 0 else "rgba(239,68,68,0.7)" for v in vals]
                fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=colors))
                fig.update_layout(**plotly_dark_layout(200))
                st.plotly_chart(fig, use_container_width=True)

            with col_r:
                st.markdown("##### Phase Distribution")
                labels_p = ["Bear Impulse", "Rest", "Flat/Exhaust", "Bull Signal", "Fading", "Bull Attempt"]
                vals_p = [
                    len([r for r in last30 if (r.get("direction") or 0) < -80]),
                    len([r for r in last30 if -80 <= (r.get("direction") or 0) < -15 and r.get("eff_regime") in ("Mixed", "Rotational")]),
                    len([r for r in last30 if -15 <= (r.get("direction") or 0) < -5 and r.get("eff_regime") == "Rotational"]),
                    len([r for r in last30 if (r.get("direction") or 0) > 80 and (r.get("clv") or 0) > 0.65]),
                    len([r for r in last30 if abs(r.get("direction") or 0) < 15]),
                    len([r for r in last30 if 15 < (r.get("direction") or 0) <= 80]),
                ]
                phase_colors = ["rgba(239,68,68,0.7)", "rgba(96,165,250,0.7)", "rgba(167,139,250,0.7)",
                                "rgba(45,212,191,0.7)", "rgba(122,128,153,0.4)", "rgba(34,197,94,0.7)"]
                fig2 = go.Figure(go.Pie(labels=labels_p, values=vals_p, marker_colors=phase_colors,
                                        hole=0.4, textinfo="percent"))
                fig2.update_layout(**plotly_dark_layout(200))
                st.plotly_chart(fig2, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# DAILY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
with tab_analysis:
    st.caption(f"Synthesises Direction + CLV + RVOL + Efficiency + ATR into a single read per day. Last {window} rows, newest first.")
    if not rows:
        st.info("No data.")
    else:
        disp = list(reversed(last30))
        table_rows = []
        for r in disp:
            lbl, col = stair_label(r)
            d = r.get("direction") or 0
            table_rows.append({
                "Date":          r.get("date", "—"),
                "DOW":           r.get("dow", "—"),
                "Phase":         lbl,
                "Range":         fmt(r.get("range"), 2),
                "ATR 14":        fmt(r.get("atr14"), 2),
                "Range/ATR":     fmt(r.get("range_atr"), 2),
                "Return%":       fmt(r.get("return_pct"), 2, sign=True),
                "Direction":     fmt(d, 2, sign=True),
                "Efficiency":    fmt(r.get("efficiency"), 3),
                "Eff Regime":    r.get("eff_regime", "—"),
                "CLV":           fmt(r.get("clv"), 3),
                "RVOL":          fmt(r.get("rvol"), 2),
                "Volatility":    r.get("volatility", "—"),
                "Participation": r.get("participation", "—"),
                "Close":         r.get("close_regime", "—"),
                "ATR State":     r.get("atr_regime", "—"),
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# STAIRCASE
# ══════════════════════════════════════════════════════════════════════════════
with tab_stair:
    st.caption(f"Each day labelled by staircase position. Last {window} days, newest first.")
    if not last30:
        st.info("No data.")
    else:
        for r in reversed(last30):
            lbl, col = stair_label(r)
            d = r.get("direction") or 0
            dir_col = "#22c55e" if d >= 0 else "#ef4444"
            st.markdown(f"""
<div style="display:flex;align-items:center;gap:12px;border-bottom:1px solid rgba(255,255,255,0.05);padding:7px 0;font-family:monospace">
  <span style="color:#4a5068;min-width:80px;font-size:11px">{r.get('date','')[5:]} {r.get('dow','')}</span>
  <span style="display:inline-block;width:3px;height:28px;background:{col};border-radius:2px;flex-shrink:0"></span>
  <span style="color:#e8eaf0;min-width:130px;font-size:11px;font-weight:700">{lbl}</span>
  <span style="color:{dir_col};min-width:80px;font-size:11px">Dir {fmt(d,2,sign=True)}</span>
  <span style="color:#7a8099;min-width:70px;font-size:11px">CLV {fmt(r.get('clv'),3)}</span>
  <span style="color:#7a8099;min-width:70px;font-size:11px">RVOL {fmt(r.get('rvol'),2)}</span>
  <span style="color:#7a8099;font-size:11px">{r.get('eff_regime','—')}</span>
</div>""", unsafe_allow_html=True)

        st.markdown("")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### RVOL Trajectory")
            fig = go.Figure(go.Scatter(
                x=[r["date"][5:] for r in last30],
                y=[r.get("rvol") for r in last30],
                fill="tozeroy", line_color="#60a5fa",
                fillcolor="rgba(96,165,250,0.1)", mode="lines+markers",
            ))
            fig.update_layout(**plotly_dark_layout(180))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.markdown("##### CLV Trajectory")
            fig = go.Figure(go.Scatter(
                x=[r["date"][5:] for r in last30],
                y=[r.get("clv") for r in last30],
                fill="tozeroy", line_color="#2dd4bf",
                fillcolor="rgba(45,212,191,0.1)", mode="lines+markers",
            ))
            fig.update_layout(**{**plotly_dark_layout(180), "yaxis": dict(range=[0, 1], gridcolor="rgba(255,255,255,0.04)")})
            st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# CHARTS
# ══════════════════════════════════════════════════════════════════════════════
with tab_charts:
    if not last30:
        st.info("No data.")
    else:
        labels = [r["date"][5:] for r in last30]
        c1, c2 = st.columns(2)

        with c1:
            st.markdown("##### Range / ATR Ratio")
            ratr = [r.get("range_atr") or 0 for r in last30]
            colors = ["rgba(239,68,68,0.8)" if v > 2 else "rgba(245,158,11,0.7)" if v > 1.3 else "rgba(96,165,250,0.5)" for v in ratr]
            fig = go.Figure(go.Bar(x=labels, y=ratr, marker_color=colors))
            fig.update_layout(**plotly_dark_layout(200))
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.markdown("##### ATR 14")
            fig = go.Figure(go.Scatter(
                x=labels, y=[r.get("atr14") for r in last30],
                fill="tozeroy", line_color="#a78bfa",
                fillcolor="rgba(167,139,250,0.1)", mode="lines+markers",
            ))
            fig.update_layout(**plotly_dark_layout(200))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### Normalised Multi-Metric (CLV · RVOL · R/ATR)")
        mx_rv = max((r.get("rvol") or 0) for r in last30) or 1
        mx_ra = max((r.get("range_atr") or 0) for r in last30) or 1
        fig = go.Figure([
            go.Scatter(x=labels, y=[r.get("clv") for r in last30], name="CLV", line=dict(color="#60a5fa", width=2), mode="lines+markers"),
            go.Scatter(x=labels, y=[(r.get("rvol") or 0)/mx_rv for r in last30], name="RVOL (norm)", line=dict(color="#22c55e", width=1.5, dash="dash"), mode="lines+markers"),
            go.Scatter(x=labels, y=[(r.get("range_atr") or 0)/mx_ra for r in last30], name="R/ATR (norm)", line=dict(color="#f59e0b", width=1.5, dash="dot"), mode="lines+markers"),
        ])
        fig.update_layout(**{**plotly_dark_layout(240), "showlegend": True,
                              "legend": dict(font=dict(color="#7a8099", size=10), bgcolor="rgba(0,0,0,0)"),
                              "yaxis": dict(range=[0, 1], gridcolor="rgba(255,255,255,0.04)")})
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### Return % per Day")
        rets = [r.get("return_pct") or 0 for r in last30]
        fig = go.Figure(go.Bar(x=labels, y=rets,
            marker_color=["rgba(34,197,94,0.7)" if v >= 0 else "rgba(239,68,68,0.7)" for v in rets]))
        fig.update_layout(**plotly_dark_layout(160))
        st.plotly_chart(fig, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL STATE
# ══════════════════════════════════════════════════════════════════════════════
with tab_signal:
    if not latest:
        st.info("No data.")
    else:
        bull_checks = [
            (latest.get("direction") or 0) > 30,
            (latest.get("clv") or 0) > 0.55,
            (latest.get("rvol") or 0) > 1.2,
            latest.get("eff_regime") in ("Trend", "Mixed"),
            latest.get("atr_regime") != "Contracting",
        ]
        score = sum(bull_checks)

        c1, c2, c3 = st.columns(3)
        state_label = "BULL ✓" if state=="bull" else ("BEAR ✓" if state=="bear" else "NO TRADE")
        c1.metric("Trade Signal",         state_label,  "Based on last 2 sessions")
        c2.metric("Bull Alignment Score", f"{score} / 5", "Strong" if score>=4 else "Moderate" if score>=3 else "Weak — watch")
        c3.metric("RVOL vs threshold",    fmt(latest.get("rvol"),2),
                  "Sufficient ✓" if (latest.get("rvol") or 0)>=1.4 else "Below 1.40 — critical gap")

        st.markdown("")
        st.markdown("##### Confirmation Checklist — Next Session")
        checks = [
            ("Direction",  ">+30, strengthening",      "<−40 two days",       fmt(latest.get("direction"),2,True), (latest.get("direction") or 0)>30),
            ("CLV",        ">0.65, Upper",              "<0.35, Lower",        fmt(latest.get("clv"),3),            (latest.get("clv") or 0)>0.65),
            ("RVOL",       ">1.40, crowd joining",      ">1.40 on down day",   fmt(latest.get("rvol"),2),           (latest.get("rvol") or 0)>1.4),
            ("Efficiency", "Trend or Mixed",            "Trend bear direction", latest.get("eff_regime","—"),        latest.get("eff_regime")=="Trend"),
            ("ATR State",  "Stable → Expanding",        "Expanding",           latest.get("atr_regime","—"),        latest.get("atr_regime")!="Contracting"),
        ]
        tbl = []
        for metric, bull_needs, bear_needs, current, ok in checks:
            tbl.append({
                "Metric":    metric,
                "Bull Needs": bull_needs,
                "Bear Needs": bear_needs,
                f"Latest ({latest.get('date','—')})": f"{'✓' if ok else '✗'} {current}",
            })
        st.dataframe(pd.DataFrame(tbl), use_container_width=True, hide_index=True)

        st.markdown("")
        st.success("**↑ Bull Confirmation** — Direction positive, CLV above 0.65, RVOL above 1.40, Efficiency Trend or Mixed — all on the same day, repeated the next day. Two days of alignment = the climb has started.")
        st.error("**↓ Bear Invalidation** — Direction turns negative, CLV drops below 0.35, RVOL rises above 1.60 on that day — for two consecutive sessions. The bull thesis is broken.")

# ══════════════════════════════════════════════════════════════════════════════
# RSI CLOUD
# ══════════════════════════════════════════════════════════════════════════════
with tab_rsi:
    st.caption(f"RSI Momentum Structure Cloud metrics (Sheet 2) — last {window} days, newest first.")
    if not rows:
        st.info("No data.")
    else:
        rsi_rows = []
        for r in reversed(last30):
            rc = r.get("rsi_cloud", {}) or {}
            rsi_rows.append({
                "Date":               r.get("date","—"),
                "DOW":                r.get("dow","—"),
                "Regime":             rc.get("regime","—"),
                "Cloud %ile":         fmt(rc.get("cloud_percentile"),1),
                "Cloud Width":        fmt(rc.get("cloud_width"),2),
                "Max Width":          fmt(rc.get("max_width"),2),
                "Regime Strength":    fmt(rc.get("regime_strength"),2),
                "Expansion":          "✓" if rc.get("is_expansion") else "—",
                "Contraction":        "✓" if rc.get("is_contraction") else "—",
                "Bull Flip":          "✓" if rc.get("bull_flip") else "—",
                "Bear Flip":          "✓" if rc.get("bear_flip") else "—",
            })
        st.dataframe(pd.DataFrame(rsi_rows), use_container_width=True, hide_index=True)
