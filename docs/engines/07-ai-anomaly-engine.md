# Engine 7: AI Anomaly Engine

> **Learn what "normal" looks like, then notice when it isn't.** The Anomaly
> Engine builds per-series baselines, forecasts future behavior, and flags
> deviations — the intelligence behind DockIQ's baseline-aware alerting.

Inspired by Netdata's baseline learning + anomaly detection, generalized across
the fleet.

---

## Purpose

- Learn a **baseline** (expected value + normal variation, including seasonality)
  for each important metric series.
- **Forecast** short-horizon values to catch problems *before* they breach (e.g.
  disk will fill in 3 hours).
- Emit **anomaly scores** and predicted breaches to the [Alert Engine](06-alert-engine.md).
- Provide the "CPU normally 20%, now 70% → abnormal" signal.

---

## What it models

| Signal | Modeled as |
|---|---|
| Per-container CPU/mem/net/disk | baseline + seasonal band |
| Request/error/latency (where available) | baseline + trend |
| Disk usage growth | trend → time-to-full forecast |
| Restart/OOM cadence | rate baseline |
| LLM tokens/cost/latency | baseline (feeds LLM engine) |

---

## Approach (pragmatic, layered)

Start simple and robust; add ML where it earns its keep.

1. **Rolling statistics + robust z-score:** median/MAD over sliding windows →
   deviation score. Cheap, resilient to outliers, good first line.
2. **Seasonal decomposition (STL) / Holt-Winters:** capture daily/weekly cycles
   so "high at 9am" isn't flagged every morning.
3. **Forecasting (Prophet / Holt-Winters / ARIMA):** short-horizon prediction →
   forecasted-breach alerts and time-to-full.
4. **Online learning (`river`):** update baselines incrementally per new sample —
   no nightly batch; adapts to legitimate regime changes.
5. **`[FUTURE]`** ML models (isolation forest, autoencoders) for multivariate
   anomalies across correlated series.

> Philosophy: **explainable first.** Operators must trust why an alert fired.
> Statistical baselines are explainable ("70% vs baseline 20±5%, z=8"); black-box
> ML is added only where it clearly beats that.

---

## Internals

```
metrics (VictoriaMetrics / stream)
        │
        ▼
┌────────────────────┐
│  Baseline learner   │  per-series model (stats/seasonal/online)
│  (warmup + update)  │  stored model state
└─────────┬──────────┘
          ▼
┌────────────────────┐
│  Scorer / forecaster│  anomaly score + short-horizon forecast
└─────────┬──────────┘
          ▼
  anomaly signals / forecasts ──▶ Alert Engine, UI (bands), Deployment (regression)
```

- **Warmup:** a new series has no baseline; the engine collects a warmup window
  before scoring, and the Alert Engine falls back to thresholds meanwhile.
- **Seasonality:** models include daily/weekly components so periodic load isn't
  false-positived.
- **Sensitivity:** per-rule sensitivity (low/med/high) maps to score thresholds;
  tunable to trade noise vs recall.
- **Regime change:** deploys/config changes shift "normal"; the engine is told
  about deploys (from the Deployment layer) so it can reset/relearn a baseline
  instead of alerting forever on the new normal.
- **Bands for UI:** exposes the expected band so charts show "normal range" behind
  the actual line.

---

## What it feeds

| Consumer | Signal |
|---|---|
| **Alert Engine** | anomaly score → baseline-deviation alerts; forecasted breach |
| **Deployment** | post-deploy regression detection (error/latency vs pre-deploy baseline) → rollback trigger |
| **Self-Healing** | crash-loop/memory-leak trend detection |
| **UI** | expected bands on charts; anomaly markers |
| **Dashboards** | annotate anomalies |

---

## Data

Model state persisted per series (compact params, not raw history) so restarts
don't lose learned baselines. Anomaly events recorded for history/tuning.

---

## Interfaces

- Consumes: metric streams / VictoriaMetrics queries; deploy events (for regime
  reset).
- Emits: `anomaly.detected`, `forecast.breach` → Alert/Deployment/UI.
- API: `GET /anomaly/series/{id}` (baseline + score), `GET /forecast/{metric}`.

---

## Failure modes

| Failure | Handling |
|---|---|
| Cold start (no baseline) | Warmup window; thresholds cover the gap |
| Legitimate regime change | Deploy-aware relearn; manual "accept new normal" |
| Seasonal false positives | Seasonal models; sensitivity tuning |
| Sparse/gappy data | Ignore gaps; require min samples before scoring |
| Compute cost at scale | Prioritize important series; sample; extract to service |

---

## Phase

- **`[MVP-lite]`** Rolling robust z-score baselines on key metrics feeding
  optional baseline alerts; expected bands in UI.
- **`[FUTURE]`** Seasonal models, forecasting/time-to-full, online learning,
  deploy-aware relearn, multivariate ML anomalies, dedicated service.
