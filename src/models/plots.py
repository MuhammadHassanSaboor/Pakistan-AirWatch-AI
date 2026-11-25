"""Diagnostic plots logged as MLflow artifacts.

Every run produces the same four plots so runs can be compared
visually, not just numerically. Uses a non-interactive backend so it
works inside Docker, CI and Kubeflow pods with no display.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Consistent, print-friendly styling.
plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": 110,
        "figure.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 9,
    }
)

ACCENT = "#0F766E"
WARN = "#B91C1C"


def _save(fig, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


def residual_plot(y_true, y_pred, path: str | Path, title: str = "") -> Path:
    """Predicted vs actual, plus the residual distribution."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    resid = y_true - y_pred

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))

    # Scatter (subsampled — millions of points render as a blob).
    n = min(len(y_true), 20_000)
    idx = np.random.default_rng(42).choice(len(y_true), n, replace=False)
    axes[0].scatter(
        y_true[idx], y_pred[idx], s=3, alpha=0.18, color=ACCENT, edgecolors="none"
    )
    lim = float(np.nanpercentile(y_true, 99.5))
    axes[0].plot([0, lim], [0, lim], color=WARN, lw=1.2, ls="--", label="perfect")
    axes[0].set_xlim(0, lim)
    axes[0].set_ylim(0, lim)
    axes[0].set_xlabel("Actual PM2.5 (µg/m³)")
    axes[0].set_ylabel("Predicted PM2.5 (µg/m³)")
    axes[0].set_title("Predicted vs actual")
    axes[0].legend(frameon=False, fontsize=8)

    # Residual histogram.
    axes[1].hist(
        resid,
        bins=80,
        color=ACCENT,
        alpha=0.8,
        range=(
            float(np.nanpercentile(resid, 0.5)),
            float(np.nanpercentile(resid, 99.5)),
        ),
    )
    axes[1].axvline(0, color=WARN, lw=1.2, ls="--")
    axes[1].set_xlabel("Residual (actual − predicted)")
    axes[1].set_ylabel("Count")
    axes[1].set_title(f"Residuals (mean={resid.mean():.2f})")

    # Error vs magnitude — does the model fail on high-pollution days?
    bins = [0, 25, 50, 75, 100, 150, 200, 300, 1e9]
    labels = [
        "0-25",
        "25-50",
        "50-75",
        "75-100",
        "100-150",
        "150-200",
        "200-300",
        "300+",
    ]
    cut = pd.cut(y_true, bins=bins, labels=labels, right=False)
    err = pd.DataFrame({"bin": cut, "abs_err": np.abs(resid)})
    grp = err.groupby("bin", observed=True)["abs_err"].mean()
    axes[2].bar(range(len(grp)), grp.to_numpy(), color=ACCENT, alpha=0.85)
    axes[2].set_xticks(range(len(grp)))
    axes[2].set_xticklabels(grp.index.astype(str), rotation=45, ha="right", fontsize=7)
    axes[2].set_xlabel("Actual PM2.5 band (µg/m³)")
    axes[2].set_ylabel("Mean absolute error")
    axes[2].set_title("Error by pollution level")

    if title:
        fig.suptitle(title, fontsize=11, y=1.04)
    return _save(fig, path)


def feature_importance_plot(
    model, feature_names: list[str], path: str | Path, top_n: int = 25
) -> Path | None:
    """Top-N most influential features."""
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        coef = getattr(model, "coef_", None)
        if coef is None:
            log.debug("Model exposes no importances; skipping plot")
            return None
        importances = np.abs(np.asarray(coef).ravel())

    imp = (
        pd.Series(importances, index=feature_names)
        .sort_values(ascending=False)
        .head(top_n)
        .iloc[::-1]
    )

    fig, ax = plt.subplots(figsize=(7, max(4.0, 0.26 * len(imp))))
    ax.barh(range(len(imp)), imp.to_numpy(), color=ACCENT, alpha=0.88)
    ax.set_yticks(range(len(imp)))
    ax.set_yticklabels(imp.index, fontsize=8)
    ax.set_xlabel("Importance")
    ax.set_title(f"Top {len(imp)} features")
    return _save(fig, path)


def horizon_error_plot(metrics: dict, path: str | Path) -> Path | None:
    """MAE against forecast lead time — the headline accuracy story."""
    pairs = sorted(
        (int(k.split("_h")[1]), v) for k, v in metrics.items() if k.startswith("mae_h")
    )
    if not pairs:
        return None
    hs, maes = zip(*pairs, strict=False)

    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    ax.plot(hs, maes, marker="o", color=ACCENT, lw=2, label="model")
    if "baseline_mae" in metrics:
        ax.axhline(
            metrics["baseline_mae"],
            color=WARN,
            ls="--",
            lw=1.2,
            label="persistence baseline",
        )
    ax.set_xlabel("Forecast horizon (hours ahead)")
    ax.set_ylabel("MAE (µg/m³)")
    ax.set_title("Accuracy by lead time")
    ax.set_xticks(hs)
    ax.legend(frameon=False, fontsize=8)
    return _save(fig, path)


def timeseries_plot(
    df: pd.DataFrame, y_pred, city_id: str, path: str | Path, horizon: int = 24
) -> Path | None:
    """Actual vs predicted over time for one city — the intuitive check."""
    tmp = df[["city_id", "timestamp", "horizon", "y"]].copy()
    tmp["pred"] = np.asarray(y_pred, dtype=float)
    sel = tmp[(tmp.city_id == city_id) & (tmp.horizon == horizon)]
    if sel.empty:
        return None
    sel = sel.sort_values("timestamp").tail(24 * 30)  # last 30 days

    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.plot(sel.timestamp, sel.y, color="#334155", lw=1.1, label="actual")
    ax.plot(
        sel.timestamp,
        sel.pred,
        color=ACCENT,
        lw=1.4,
        alpha=0.9,
        label=f"predicted (+{horizon}h)",
    )
    ax.fill_between(sel.timestamp, sel.y, sel.pred, color=ACCENT, alpha=0.12)
    ax.set_ylabel("PM2.5 (µg/m³)")
    ax.set_title(f"{city_id} — last 30 days of the test period")
    ax.legend(frameon=False, fontsize=8)
    fig.autofmt_xdate()
    return _save(fig, path)


__all__ = [
    "residual_plot",
    "feature_importance_plot",
    "horizon_error_plot",
    "timeseries_plot",
]
