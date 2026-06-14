"""
ETH Quant Research Collector
Replicates:
  - ETH Quant Research Collector v3 (Sheet 1 metrics)
  - RSI Momentum Structure Cloud Research v2 (Sheet 2 metrics)

Run manually or schedule via cron/Task Scheduler at 05:35 IST daily.
Writes data.json — the dashboard reads this file.
"""

import requests
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
DATA_FILE  = BASE_DIR / "data.json"

# ── Delta Exchange public API ─────────────────────────────────────────────────
# No API key required for market data.
BASE_URL   = "https://api.india.delta.exchange"
SYMBOL     = "ETHUSD"          # perpetual futures symbol on Delta Exchange India
CANDLE_RES = "1d"              # daily candles

IST = timezone(timedelta(hours=5, minutes=30))

# ═════════════════════════════════════════════════════════════════════════════
# 1.  FETCH CANDLES FROM DELTA EXCHANGE
# ═════════════════════════════════════════════════════════════════════════════

def fetch_candles(symbol: str, resolution: str, count: int = 60) -> list[dict]:
    """
    Fetch the last `count` completed daily candles from Delta Exchange.
    Returns list of dicts with keys: time, open, high, low, close, volume.
    Sorted oldest → newest.
    """
    end_ts   = int(datetime.now(timezone.utc).timestamp())
    # Request extra days to cover weekends / gaps; filter to `count` later.
    start_ts = end_ts - (count + 10) * 86400

    url = f"{BASE_URL}/v2/history/candles"
    params = {
        "resolution": resolution,
        "symbol":     symbol,
        "start":      start_ts,
        "end":        end_ts,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw  = resp.json()

    candles = []
    for c in raw.get("result", []):
        # API returns list [time, open, high, low, close, volume]
        # or dict with named keys — handle both
        if isinstance(c, (list, tuple)):
            candles.append({
                "time":   int(c[0]),
                "open":   float(c[1]),
                "high":   float(c[2]),
                "low":    float(c[3]),
                "close":  float(c[4]),
                "volume": float(c[5]),
            })
        else:
            candles.append({
                "time":   int(c["time"]),
                "open":   float(c["open"]),
                "high":   float(c["high"]),
                "low":    float(c["low"]),
                "close":  float(c["close"]),
                "volume": float(c["volume"]),
            })

    candles.sort(key=lambda x: x["time"])
    return candles[-count:]


# ═════════════════════════════════════════════════════════════════════════════
# 2.  INDICATOR HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def sma(values: list[float], period: int) -> list[float | None]:
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1: i + 1]) / period)
    return result


def ema(values: list[float | None], period: int) -> list[float | None]:
    result = []
    k = 2.0 / (period + 1)
    prev = None
    for v in values:
        if v is None:
            result.append(None)
            continue
        if prev is None:
            prev = v
        prev = v * k + prev * (1 - k)
        result.append(prev)
    return result


def atr(highs, lows, closes, period: int) -> list[float | None]:
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i]  - closes[i - 1]),
            )
            trs.append(tr)
    # Wilder smoothing (same as Pine ta.atr)
    result = []
    wilder = None
    for i, tr in enumerate(trs):
        if i < period - 1:
            result.append(None)
        elif i == period - 1:
            wilder = sum(trs[:period]) / period
            result.append(wilder)
        else:
            wilder = (wilder * (period - 1) + tr) / period
            result.append(wilder)
    return result


def rsi(closes: list[float], period: int) -> list[float | None]:
    # Prepend one None so output length == input length (same as Pine ta.rsi).
    # The price-change loop starts at index 1, producing len-1 deltas,
    # so without this the series is one element short.
    result = [None] * (period + 1)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    if len(gains) < period:
        return [None] * len(closes)
    # Wilder init
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    return result


def roc(closes: list[float], period: int = 1) -> list[float | None]:
    result = [None] * period
    for i in range(period, len(closes)):
        prev = closes[i - period]
        result.append((closes[i] - prev) / prev * 100 if prev != 0 else None)
    return result


def lowest(values, period):
    result = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - period + 1):i + 1] if v is not None]
        result.append(min(window) if window else None)
    return result


def highest(values, period):
    result = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - period + 1):i + 1] if v is not None]
        result.append(max(window) if window else None)
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 3.  SCRIPT 1 — ETH QUANT RESEARCH COLLECTOR v3
#     Replicates every metric and regime label exactly as in the Pine Script.
#     Uses [1] offset (previous completed candle) as Pine does.
# ═════════════════════════════════════════════════════════════════════════════

def compute_sheet1(candles: list[dict]) -> list[dict]:
    opens   = [c["open"]   for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    times   = [c["time"]   for c in candles]

    atr14_series = atr(highs, lows, closes, 14)

    # RVOL: volume / sma(volume, 20)
    vol_sma20 = sma(volumes, 20)

    rows = []
    # Pine uses [1] — so the "current bar" in Pine = index i, but it reads
    # the previous completed daily candle. We iterate i from 1..N-1 and
    # treat candles[i-1] as the "completed" candle being reported.
    for i in range(1, len(candles)):
        prev = candles[i - 1]
        o, h, l, c_ = prev["open"], prev["high"], prev["low"], prev["close"]
        vol = prev["volume"]
        ts  = times[i - 1]

        range_day = h - l
        atr14     = atr14_series[i - 1]

        # atr5ago: atr14[6] in Pine = 5 bars before the previous bar
        atr5ago_idx = i - 1 - 5
        atr5ago = atr14_series[atr5ago_idx] if atr5ago_idx >= 0 else None

        range_atr = range_day / atr14 if atr14 and atr14 > 0 else None
        ret_pct   = ((c_ - o) / o) * 100 if o != 0 else None
        direction = c_ - o
        efficiency = abs(c_ - o) / range_day if range_day > 0 else None
        clv        = (c_ - l) / range_day if range_day > 0 else None
        atr_ratio  = atr14 / atr5ago if atr5ago and atr5ago > 0 else None

        avg_vol20 = vol_sma20[i - 1]
        rvol = vol / avg_vol20 if avg_vol20 and avg_vol20 > 0 else None

        # Date from timestamp (ms)
        dt  = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST)
        dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        dow = dow_map[dt.weekday()]
        date_str = dt.strftime("%Y-%m-%d")

        # ── Regimes ──────────────────────────────────────────────────────────
        if range_atr is None:
            vol_regime = "—"
        elif range_atr < 0.70:
            vol_regime = "Compression"
        elif range_atr > 1.30:
            vol_regime = "Expansion"
        else:
            vol_regime = "Normal"

        if efficiency is None:
            eff_regime = "—"
        elif efficiency < 0.15:
            eff_regime = "Rotational"
        elif efficiency > 0.50:
            eff_regime = "Trend"
        else:
            eff_regime = "Mixed"

        if rvol is None:
            part_regime = "—"
        elif rvol < 0.80:
            part_regime = "Low"
        elif rvol > 1.20:
            part_regime = "High"
        else:
            part_regime = "Normal"

        if clv is None:
            close_regime = "—"
        elif clv >= 0.80:
            close_regime = "Upper"
        elif clv <= 0.20:
            close_regime = "Lower"
        else:
            close_regime = "Middle"

        if atr_ratio is None:
            atr_regime = "—"
        elif atr_ratio > 1.10:
            atr_regime = "Expanding"
        elif atr_ratio < 0.90:
            atr_regime = "Contracting"
        else:
            atr_regime = "Stable"

        rows.append({
            "date":          date_str,
            "dow":           dow,
            "open":          round(o, 2),
            "high":          round(h, 2),
            "low":           round(l, 2),
            "close":         round(c_, 2),
            "range":         round(range_day, 2),
            "atr14":         round(atr14, 2) if atr14 else None,
            "range_atr":     round(range_atr, 2) if range_atr else None,
            "return_pct":    round(ret_pct, 2) if ret_pct is not None else None,
            "direction":     round(direction, 2),
            "efficiency":    round(efficiency, 3) if efficiency else None,
            "clv":           round(clv, 3) if clv else None,
            "rvol":          round(rvol, 2) if rvol else None,
            "atr_ratio":     round(atr_ratio, 3) if atr_ratio else None,
            "volatility":    vol_regime,
            "eff_regime":    eff_regime,
            "participation": part_regime,
            "close_regime":  close_regime,
            "atr_regime":    atr_regime,
        })

    return rows


# ═════════════════════════════════════════════════════════════════════════════
# 4.  SCRIPT 2 — RSI MOMENTUM STRUCTURE CLOUD RESEARCH v2
#     Computes the previous-day RSI cloud metrics exactly as Pine does.
#     The "previous day" snapshot is what appears in your Sheet 2.
# ═════════════════════════════════════════════════════════════════════════════

def compute_sheet2(candles: list[dict]) -> list[dict]:
    closes  = [c["close"] for c in candles]
    highs   = [c["high"]  for c in candles]
    lows    = [c["low"]   for c in candles]
    times   = [c["time"]  for c in candles]

    RSI_LEN           = 14
    ATR_LEN           = 14
    MOM_SMOOTH        = 5
    DIV_SMOOTH        = 8
    CLOUD_LOOKBACK    = 250
    EXPAND_THRESHOLD  = 1.05

    atr_series  = atr(highs, lows, closes, ATR_LEN)
    rsi_series  = rsi(closes, RSI_LEN)
    roc_series  = roc(closes, 1)

    # rsiCentered = (rsi - 50) / 50
    rsi_centered = [
        (r - 50.0) / 50.0 if r is not None else None
        for r in rsi_series
    ]
    rsi_momentum = ema(rsi_centered, MOM_SMOOTH)

    # priceMomentum = ema(roc / atr, MOM_SMOOTH)
    roc_over_atr = []
    for i in range(len(closes)):
        r = roc_series[i]
        a = atr_series[i]
        if r is not None and a is not None and a > 1e-10:
            roc_over_atr.append(r / a)
        else:
            roc_over_atr.append(None)
    price_momentum = ema(roc_over_atr, MOM_SMOOTH)

    # divPressure = ema(priceMomentum - rsiMomentum, DIV_SMOOTH)
    div_pressure_raw = []
    for pm, rm in zip(price_momentum, rsi_momentum):
        if pm is not None and rm is not None:
            div_pressure_raw.append(pm - rm)
        else:
            div_pressure_raw.append(None)
    div_pressure = ema(div_pressure_raw, DIV_SMOOTH)

    # price-space transform
    momentum_line   = []
    divergence_line = []
    for i in range(len(closes)):
        a  = atr_series[i]
        rm = rsi_momentum[i]
        dp = div_pressure[i]
        if a is not None and rm is not None:
            momentum_line.append(closes[i] + rm * a * 5.0)
        else:
            momentum_line.append(None)
        if a is not None and dp is not None:
            divergence_line.append(closes[i] + dp * a * 5.0)
        else:
            divergence_line.append(None)

    # cloud width
    cloud_width = []
    for ml, dl in zip(momentum_line, divergence_line):
        if ml is not None and dl is not None:
            cloud_width.append(abs(ml - dl))
        else:
            cloud_width.append(None)

    cloud_width_sma20 = sma([v if v is not None else 0 for v in cloud_width], 20)

    is_expansion   = []
    is_contraction = []
    for cw, sma20 in zip(cloud_width, cloud_width_sma20):
        safe_sma = max(sma20, 1e-10) if sma20 else 1e-10
        if cw is not None:
            is_expansion.append(cw > safe_sma * EXPAND_THRESHOLD)
            is_contraction.append(cw < safe_sma / EXPAND_THRESHOLD)
        else:
            is_expansion.append(False)
            is_contraction.append(False)

    cloud_min = lowest(cloud_width, CLOUD_LOOKBACK)
    cloud_max = highest(cloud_width, CLOUD_LOOKBACK)

    bull_regime = [
        (ml > dl) if (ml is not None and dl is not None) else None
        for ml, dl in zip(momentum_line, divergence_line)
    ]

    # ── IST boundary accumulation ─────────────────────────────────────────
    # For daily candles the "5:30am boundary" maps simply to each candle
    # representing one completed trading day. We accumulate per-candle and
    # snapshot at the end of each day.

    rows = []

    for i in range(len(candles)):
        cw   = cloud_width[i]
        bull = bull_regime[i]
        is_exp  = is_expansion[i]
        is_cont = is_contraction[i]
        ts  = times[i]
        dt  = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST)
        date_str = dt.strftime("%Y-%m-%d")
        dow_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        dow = dow_map[dt.weekday()]

        # prev day bull/bear flip
        prev_bull = bull_regime[i - 1] if i > 0 else None
        bull_flip = (bull == True and prev_bull == False) if prev_bull is not None else False
        bear_flip = (bull == False and prev_bull == True) if prev_bull is not None else False

        # prev expansion/contraction flip
        prev_exp  = is_expansion[i - 1]  if i > 0 else False
        prev_cont = is_contraction[i - 1] if i > 0 else False
        exp_entry  = is_exp  and not prev_exp
        cont_entry = is_cont and not prev_cont

        cm = cloud_min[i]
        cx = cloud_max[i]
        if cm is not None and cx is not None and (cx - cm) > 1e-10 and cw is not None:
            cloud_pct = ((cw - cm) / (cx - cm)) * 100.0
        else:
            cloud_pct = 50.0

        a = atr_series[i]
        regime_strength = min(cw / a, 10.0) if (cw is not None and a and a > 1e-10) else None

        dominant = "BULL" if bull else ("BEAR" if bull is not None else "—")

        rows.append({
            "date":             date_str,
            "dow":              dow,
            "bull_flip":        int(bull_flip),
            "bear_flip":        int(bear_flip),
            "expansion_entry":  int(exp_entry),
            "contraction_entry":int(cont_entry),
            "cloud_width":      round(cw, 2) if cw else None,
            "cloud_percentile": round(cloud_pct, 1),
            "max_width":        round(cx, 2) if cx else None,
            "avg_width":        None,    # rolling; Pine accumulates intrabar
            "regime":           dominant,
            "regime_strength":  round(regime_strength, 2) if regime_strength else None,
            "is_expansion":     is_exp,
            "is_contraction":   is_cont,
        })

    return rows


# ═════════════════════════════════════════════════════════════════════════════
# 5.  MERGE AND SAVE
# ═════════════════════════════════════════════════════════════════════════════

def build_dataset() -> dict:
    print("Fetching candles from Delta Exchange...")
    candles = fetch_candles(SYMBOL, CANDLE_RES, count=510)
    print(f"  Received {len(candles)} candles.")

    sheet1 = compute_sheet1(candles)
    sheet2 = compute_sheet2(candles)

    # Align by date
    s2_map = {r["date"]: r for r in sheet2}
    for row in sheet1:
        s2 = s2_map.get(row["date"], {})
        row["rsi_cloud"] = {
            "bull_flip":         s2.get("bull_flip"),
            "bear_flip":         s2.get("bear_flip"),
            "expansion_entry":   s2.get("expansion_entry"),
            "contraction_entry": s2.get("contraction_entry"),
            "cloud_width":       s2.get("cloud_width"),
            "cloud_percentile":  s2.get("cloud_percentile"),
            "max_width":         s2.get("max_width"),
            "regime":            s2.get("regime"),
            "regime_strength":   s2.get("regime_strength"),
            "is_expansion":      s2.get("is_expansion"),
            "is_contraction":    s2.get("is_contraction"),
        }

    collected_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    latest = sheet1[-1] if sheet1 else {}

    return {
        "collected_at": collected_at,
        "symbol":       SYMBOL,
        "latest":       latest,
        "rows":         sheet1,
    }


def inject_into_dashboard(dataset: dict) -> None:
    """
    Writes the dataset directly into the HTML dashboard as an inline
    JS variable, so the file works from a plain double-click with no
    server and no fetch() needed.
    """
    html_file = BASE_DIR / "eth_trading_dashboard.html"
    if not html_file.exists():
        print(f"  Dashboard HTML not found at {html_file} — skipping inject.")
        return

    html = html_file.read_text(encoding="utf-8")

    data_json = json.dumps(dataset, separators=(",", ":"))

    # Replace everything between the two sentinel comments
    start_marker = "/* __INJECTED_DATA_START__ */"
    end_marker   = "/* __INJECTED_DATA_END__ */"
    nl = "\n"
    replacement = start_marker + nl + "const LIVE_DATA = " + data_json + ";" + nl + end_marker

    if start_marker in html:
        import re
        html = re.sub(
            r"/\* __INJECTED_DATA_START__ \*/.*?/\* __INJECTED_DATA_END__ \*/",
            replacement,
            html,
            flags=re.DOTALL,
        )
    else:
        # First run — insert before the INIT comment
        html = html.replace(
            "// ─── INIT",
            replacement + nl + "// ─── INIT",
            1,
        )

    html_file.write_text(html, encoding="utf-8")
    print(f"  Injected {len(dataset['rows'])} rows into {html_file.name}")


def run():
    dataset = build_dataset()

    # 1. Write data.json as before (backup / server use)
    with open(DATA_FILE, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"Saved {len(dataset['rows'])} rows → {DATA_FILE}")

    # 2. Inject directly into the HTML — works with plain double-click
    inject_into_dashboard(dataset)

    print(f"Latest date: {dataset['latest'].get('date')} | Direction: {dataset['latest'].get('direction')} | CLV: {dataset['latest'].get('clv')}")


if __name__ == "__main__":
    run()
