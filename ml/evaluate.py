"""
ml/evaluate.py
===============
Model Evaluation — Metrics, Plots, and Comparison Table

Thesis Reference: Chapter 3, Section 3.9 — Evaluation Metrics
                  Table 7 — Model Performance Comparison

Computes on the held-out TEST SET ONLY:
  - Precision, Recall, F1-score (minority class = fraud)
  - ROC-AUC
  - Matthews Correlation Coefficient (MCC)
  - Confusion Matrix
  - Comparison table: Hybrid Fusion vs XGBoost-only vs IF-only

Plots produced:
  - ROC curve (hybrid fusion)
  - Precision-Recall curve
  - Confusion matrix heatmap
  - SHAP summary plot (top 10 features, global)
  - Model comparison bar chart

All metrics saved to evaluation_report.json.
All plots saved to models/plots/ as PNG files.

Every metric shown in the frontend Model Performance Dashboard comes from
this evaluation_report.json — NEVER hardcoded.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend (Colab + server compatible)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
# shap is imported lazily inside _plot_shap_summary() to avoid crashing on
# machines where numba's DLL is blocked by Windows Application Control.
from sklearn.metrics import (
    auc,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from xgboost import XGBClassifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def _metrics_at_threshold(
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float = 0.5,
    model_name: str = "model",
) -> dict:
    """Compute classification metrics at a given decision threshold."""
    y_pred = (scores >= threshold).astype(int)
    cm = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel() if cm.shape == (2, 2) else (0, 0, 0, 0)

    precision = float(precision_score(y_true, y_pred, pos_label=1, zero_division=0))
    recall = float(recall_score(y_true, y_pred, pos_label=1, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, pos_label=1, zero_division=0))
    mcc = float(matthews_corrcoef(y_true, y_pred))
    try:
        roc_auc = float(roc_auc_score(y_true, scores))
    except ValueError:
        roc_auc = 0.0

    return {
        "model": model_name,
        "threshold": threshold,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1_score": round(f1, 6),
        "roc_auc": round(roc_auc, 6),
        "mcc": round(mcc, 6),
        "confusion_matrix": {
            "true_negatives": int(tn),
            "false_positives": int(fp),
            "false_negatives": int(fn),
            "true_positives": int(tp),
        },
        "support_fraud": int(y_true.sum()),
        "support_legitimate": int((y_true == 0).sum()),
    }


def compute_all_metrics(
    y_test: np.ndarray,
    xgb_probs: np.ndarray,
    if_normalized: np.ndarray,
    fused_scores: np.ndarray,
    block_threshold: float = 0.85,
    review_threshold: float = 0.50,
    output_dir: Optional[Path] = None,
    feature_names: Optional[List[str]] = None,
    xgb_model: Optional[XGBClassifier] = None,
    X_test: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Compute all evaluation metrics and produce all plots.

    Evaluates three model configurations for comparison (thesis Table 7):
    1. Hybrid Fusion (0.70 XGB + 0.30 IF)
    2. XGBoost-only
    3. Isolation Forest-only

    Returns comprehensive metrics dict that becomes evaluation_report.json.
    """
    if output_dir is not None:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("EVALUATING ON HELD-OUT TEST SET (%d samples)", len(y_test))
    logger.info("  Fraud samples: %d (%.4f%%)", y_test.sum(), 100 * y_test.mean())
    logger.info("=" * 60)

    # --- Metrics at REVIEW threshold (0.50) for primary decision ---
    hybrid_metrics = _metrics_at_threshold(y_test, fused_scores, review_threshold, "Hybrid Fusion")
    xgb_metrics = _metrics_at_threshold(y_test, xgb_probs, review_threshold, "XGBoost Only")
    if_metrics = _metrics_at_threshold(y_test, if_normalized, review_threshold, "Isolation Forest Only")

    # --- Metrics at BLOCK threshold (0.85) for blocked transactions ---
    hybrid_block_metrics = _metrics_at_threshold(y_test, fused_scores, block_threshold, "Hybrid (block tier)")

    # --- ROC curve data ---
    fpr_h, tpr_h, thresh_h = roc_curve(y_test, fused_scores)
    fpr_x, tpr_x, thresh_x = roc_curve(y_test, xgb_probs)
    fpr_i, tpr_i, thresh_i = roc_curve(y_test, if_normalized)

    roc_data = {
        "hybrid": {"fpr": fpr_h.tolist(), "tpr": tpr_h.tolist(), "auc": float(auc(fpr_h, tpr_h))},
        "xgb":    {"fpr": fpr_x.tolist(), "tpr": tpr_x.tolist(), "auc": float(auc(fpr_x, tpr_x))},
        "if":     {"fpr": fpr_i.tolist(), "tpr": tpr_i.tolist(), "auc": float(auc(fpr_i, tpr_i))},
    }

    # --- Precision-Recall curve data ---
    prec_h, rec_h, _ = precision_recall_curve(y_test, fused_scores)
    pr_data = {
        "precision": prec_h.tolist(),
        "recall": rec_h.tolist(),
    }

    # Log comparison table
    logger.info("\n" + "=" * 70)
    logger.info("MODEL COMPARISON TABLE (Test Set, threshold=%.2f)", review_threshold)
    logger.info("%-30s %-10s %-10s %-10s %-10s %-10s", "Model", "Precision", "Recall", "F1", "ROC-AUC", "MCC")
    logger.info("-" * 70)
    for m in [hybrid_metrics, xgb_metrics, if_metrics]:
        logger.info(
            "%-30s %-10.4f %-10.4f %-10.4f %-10.4f %-10.4f",
            m["model"], m["precision"], m["recall"], m["f1_score"], m["roc_auc"], m["mcc"],
        )
    logger.info("=" * 70)

    # --- Produce plots ---
    if output_dir is not None:
        _plot_roc_curve(roc_data, output_dir)
        _plot_pr_curve(prec_h, rec_h, output_dir)
        _plot_confusion_matrix(hybrid_metrics["confusion_matrix"], output_dir)
        _plot_model_comparison(
            [hybrid_metrics, xgb_metrics, if_metrics], output_dir
        )
        if xgb_model is not None and X_test is not None and feature_names is not None:
            _plot_shap_summary(xgb_model, X_test, feature_names, output_dir)

    # --- Assemble full report ---
    report = {
        "evaluation_version": "1.0.0",
        "test_set_size": len(y_test),
        "test_fraud_count": int(y_test.sum()),
        "test_fraud_pct": round(100 * y_test.mean(), 6),
        "primary_metrics": hybrid_metrics,
        "block_tier_metrics": hybrid_block_metrics,
        "model_comparison": {
            "hybrid_fusion": hybrid_metrics,
            "xgboost_only": xgb_metrics,
            "isolation_forest_only": if_metrics,
        },
        "roc_curve_data": roc_data,
        "precision_recall_curve_data": pr_data,
        "decision_thresholds": {
            "block": block_threshold,
            "review": review_threshold,
        },
    }

    return report


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def _plot_roc_curve(roc_data: dict, output_dir: Path) -> None:
    """Plot ROC curves for all three model configurations."""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")

    colors = {"hybrid": "#00d4ff", "xgb": "#39ff14", "if": "#ff6b35"}
    labels = {
        "hybrid": f"Hybrid Fusion (AUC={roc_data['hybrid']['auc']:.4f})",
        "xgb": f"XGBoost Only (AUC={roc_data['xgb']['auc']:.4f})",
        "if": f"Isolation Forest Only (AUC={roc_data['if']['auc']:.4f})",
    }
    for key in ["hybrid", "xgb", "if"]:
        ax.plot(
            roc_data[key]["fpr"], roc_data[key]["tpr"],
            color=colors[key], linewidth=2.5 if key == "hybrid" else 1.5,
            label=labels[key], alpha=0.9,
        )

    ax.plot([0, 1], [0, 1], color="#555", linestyle="--", linewidth=1, label="Random (AUC=0.50)")
    ax.set_xlabel("False Positive Rate", color="white", fontsize=12)
    ax.set_ylabel("True Positive Rate", color="white", fontsize=12)
    ax.set_title("ROC Curve — Hybrid vs XGBoost vs Isolation Forest", color="white", fontsize=13, fontweight="bold")
    ax.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=10)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    plt.tight_layout()
    path = output_dir / "roc_curve.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("ROC curve saved to %s", path)


def _plot_pr_curve(precision: np.ndarray, recall: np.ndarray, output_dir: Path) -> None:
    """Plot Precision-Recall curve for the hybrid model."""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")

    pr_auc = auc(recall, precision)
    ax.plot(recall, precision, color="#00d4ff", linewidth=2.5, label=f"Hybrid Fusion (PR-AUC={pr_auc:.4f})")
    ax.fill_between(recall, precision, alpha=0.15, color="#00d4ff")
    ax.set_xlabel("Recall", color="white", fontsize=12)
    ax.set_ylabel("Precision", color="white", fontsize=12)
    ax.set_title("Precision-Recall Curve — Hybrid Fusion Model", color="white", fontsize=13, fontweight="bold")
    ax.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=10)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    plt.tight_layout()
    path = output_dir / "precision_recall_curve.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("PR curve saved to %s", path)


def _plot_confusion_matrix(cm_dict: dict, output_dir: Path) -> None:
    """Plot confusion matrix heatmap for the hybrid model."""
    cm = np.array([
        [cm_dict["true_negatives"], cm_dict["false_positives"]],
        [cm_dict["false_negatives"], cm_dict["true_positives"]],
    ])

    fig, ax = plt.subplots(figsize=(7, 5))
    fig.patch.set_facecolor("#1a1a2e")

    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=["Predicted Legit", "Predicted Fraud"],
        yticklabels=["Actual Legit", "Actual Fraud"],
        ax=ax,
        linewidths=0.5,
        annot_kws={"size": 14, "weight": "bold"},
    )
    ax.set_title("Confusion Matrix — Hybrid Fusion (review threshold=0.50)", color="white", fontsize=12, fontweight="bold")
    ax.set_facecolor("#1a1a2e")
    ax.tick_params(colors="white")
    ax.xaxis.label.set_color("white")
    ax.yaxis.label.set_color("white")

    plt.tight_layout()
    path = output_dir / "confusion_matrix.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Confusion matrix saved to %s", path)


def _plot_model_comparison(metrics_list: list, output_dir: Path) -> None:
    """Plot bar chart comparing Precision, Recall, F1, AUC across three models."""
    models = [m["model"] for m in metrics_list]
    metric_keys = ["precision", "recall", "f1_score", "roc_auc", "mcc"]
    metric_labels = ["Precision", "Recall", "F1", "ROC-AUC", "MCC"]
    colors = ["#00d4ff", "#39ff14", "#ff6b35"]

    x = np.arange(len(metric_keys))
    width = 0.22
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")

    for i, (model_metrics, color) in enumerate(zip(metrics_list, colors)):
        values = [model_metrics[k] for k in metric_keys]
        bars = ax.bar(x + i * width, values, width, label=models[i], color=color, alpha=0.85)
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"{val:.3f}", ha="center", va="bottom", color="white", fontsize=8,
            )

    ax.set_xticks(x + width)
    ax.set_xticklabels(metric_labels, color="white", fontsize=11)
    ax.set_ylabel("Score", color="white", fontsize=12)
    ax.set_title("Model Comparison: Hybrid vs XGBoost-Only vs Isolation Forest-Only", color="white", fontsize=12, fontweight="bold")
    ax.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=10)
    ax.set_ylim(0, 1.1)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    plt.tight_layout()
    path = output_dir / "model_comparison.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Model comparison chart saved to %s", path)


def _plot_shap_summary(
    xgb_model: XGBClassifier,
    X_test: pd.DataFrame,
    feature_names: List[str],
    output_dir: Path,
    max_samples: int = 500,
    top_n: int = 10,
) -> None:
    """Plot SHAP summary plot (beeswarm) for top N features."""
    logger.info("Computing SHAP values for summary plot (max %d samples)...", max_samples)
    if len(X_test) > max_samples:
        X_sample = X_test.sample(n=max_samples, random_state=42)
    else:
        X_sample = X_test

    explainer = shap.TreeExplainer(xgb_model)
    shap_values = explainer.shap_values(X_sample.values)

    if isinstance(shap_values, list):
        sv = shap_values[1]
    else:
        sv = shap_values

    # Get mean |SHAP| per feature for top N selection
    mean_abs_shap = np.abs(sv).mean(axis=0)
    top_indices = np.argsort(mean_abs_shap)[::-1][:top_n]
    top_names = [feature_names[i] for i in top_indices]
    top_sv = sv[:, top_indices]
    top_vals = X_sample.values[:, top_indices]

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")

    # Beeswarm-style: scatter SHAP values, colored by feature value
    cmap = plt.get_cmap("coolwarm")
    for i, (feat_name, shap_col, val_col) in enumerate(
        zip(reversed(top_names), top_sv.T[::-1], top_vals.T[::-1])
    ):
        # Normalize feature values to [0, 1] for color
        val_norm = (val_col - val_col.min()) / (val_col.max() - val_col.min() + 1e-10)
        colors_scatter = cmap(val_norm)
        y_jitter = i + np.random.normal(0, 0.08, size=len(shap_col))
        ax.scatter(shap_col, y_jitter, c=colors_scatter, alpha=0.5, s=15)

    ax.set_yticks(range(top_n))
    ax.set_yticklabels(list(reversed(top_names)), color="white", fontsize=10)
    ax.axvline(0, color="#666", linewidth=1, linestyle="--")
    ax.set_xlabel("SHAP Value (impact on fraud probability)", color="white", fontsize=11)
    ax.set_title(f"SHAP Summary — Top {top_n} Features", color="white", fontsize=13, fontweight="bold")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    # Add colorbar annotation
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=1))
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.5)
    cbar.ax.set_ylabel("Feature value\n(low → high)", color="white", fontsize=9)
    cbar.ax.tick_params(colors="white")

    plt.tight_layout()
    path = output_dir / "shap_summary.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("SHAP summary plot saved to %s", path)


# ---------------------------------------------------------------------------
# Save/Load Evaluation Report
# ---------------------------------------------------------------------------

def save_evaluation_report(report: Dict[str, Any], path: str | Path) -> None:
    """Save evaluation_report.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Evaluation report saved to %s", path)


def load_evaluation_report(path: str | Path) -> Dict[str, Any]:
    """Load evaluation_report.json."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Evaluation report not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_metrics_summary(report: Dict[str, Any]) -> None:
    """Print a clean summary of key metrics to stdout (for Colab final cell output)."""
    pm = report.get("primary_metrics", {})
    comparison = report.get("model_comparison", {})

    print("\n" + "=" * 70)
    print("FRAUD DETECTION MODEL — EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Test set: {report.get('test_set_size', 'N/A')} rows "
          f"({report.get('test_fraud_count', 'N/A')} fraud, "
          f"{report.get('test_fraud_pct', 'N/A'):.4f}%)")
    print(f"\nDecision threshold for metrics: REVIEW ({report['decision_thresholds']['review']})")
    print("-" * 70)
    print(f"{'Model':<35} {'Precision':>10} {'Recall':>10} {'F1':>10} {'AUC':>10} {'MCC':>10}")
    print("-" * 70)
    for key, name in [
        ("hybrid_fusion", "Hybrid Fusion (thesis model)"),
        ("xgboost_only", "XGBoost Only"),
        ("isolation_forest_only", "Isolation Forest Only"),
    ]:
        m = comparison.get(key, {})
        print(
            f"{name:<35} {m.get('precision', 0):>10.4f} {m.get('recall', 0):>10.4f} "
            f"{m.get('f1_score', 0):>10.4f} {m.get('roc_auc', 0):>10.4f} {m.get('mcc', 0):>10.4f}"
        )
    print("=" * 70)
    print(f"\n✓ Hybrid Fusion ROC-AUC: {report['model_comparison']['hybrid_fusion']['roc_auc']:.4f}")
    print(f"✓ Hybrid Fusion F1 (fraud): {report['model_comparison']['hybrid_fusion']['f1_score']:.4f}")
    print(f"✓ MCC: {report['model_comparison']['hybrid_fusion']['mcc']:.4f}")
    cm = pm.get("confusion_matrix", {})
    print(f"\nConfusion Matrix (Hybrid, threshold=0.50):")
    print(f"  True Positives  (fraud caught):     {cm.get('true_positives', 'N/A')}")
    print(f"  True Negatives  (legit approved):   {cm.get('true_negatives', 'N/A')}")
    print(f"  False Positives (legit flagged):    {cm.get('false_positives', 'N/A')}")
    print(f"  False Negatives (fraud missed):     {cm.get('false_negatives', 'N/A')}")
    print("=" * 70)
