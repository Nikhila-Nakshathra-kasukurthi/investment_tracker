
# train_model.py — IPO Listing Gain Prediction System
# Trains LSTM + XGBoost hybrid model and saves artifacts
#
# Usage:
#   python train_model.py --data path/to/dataset.xlsx
#   python train_model.py --data path/to/dataset.xlsx --output_dir ./outputs


import os
import sys
import argparse
import warnings
import logging
warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Patch

import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping

from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import xgboost as xgb

from config import (
    TARGET_COL, COMPANY_COL, EXCLUDE_COLS, PAT_SEQ_COLS,
    PAT_KEYWORDS, GMP_KEYWORDS, SUB_KEYWORDS,
    POS_HIGHER, NEG_HIGHER, PALETTE,
    LSTM_UNITS, LSTM_DROPOUT, LSTM_DENSE_UNITS, LSTM_DENSE_DROP,
    LSTM_EPOCHS, LSTM_BATCH_SIZE, LSTM_PATIENCE, LSTM_VAL_SPLIT, LSTM_SEED,
    XGB_PARAMS, XGB_VAL_SPLIT, XGB_SEED,
    MODEL_DIR, OUTPUT_DIR, LOG_DIR,
    XGB_MODEL_PATH, LSTM_MODEL_PATH, IMPUTER_PATH, SCALER_PATH, FEATURES_PATH,
)


os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "train.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)



# Utilities


def feature_group(name: str) -> str:
    n = name.lower()
    if any(k in n for k in GMP_KEYWORDS):  return "gmp"
    if any(k in n for k in PAT_KEYWORDS):  return "pat"
    if any(k in n for k in SUB_KEYWORDS):  return "sub"
    return "other"


def feature_color(name: str) -> str:
    g = feature_group(name)
    return {
        "gmp"  : PALETTE["purple"],
        "pat"  : PALETTE["orange"],
        "sub"  : PALETTE["teal"],
        "other": PALETTE["blue"],
    }[g]


def categorise(g: float):
    if g > 0.10:   return "Strong Profit (>10%)",    "🟢"
    if g > 0.03:   return "Moderate Profit (3–10%)", "🟡"
    if g >= 0:     return "Low/Uncertain (0–3%)",    "⚪"
    return               "Loss Risk (<0%)",           "🔴"


def accuracy_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2   = r2_score(y_true, y_pred)
    dir_acc = np.mean(np.sign(y_pred) == np.sign(y_true)) * 100
    tol_acc = np.mean(np.abs(y_pred - y_true) <= 0.10) * 100
    cat_true = np.array([categorise(g)[0] for g in y_true])
    cat_pred = np.array([categorise(g)[0] for g in y_pred])
    cat_acc  = np.mean(cat_true == cat_pred) * 100
    return dict(mae=mae, rmse=rmse, r2=r2,
                dir_acc=dir_acc, tol_acc=tol_acc, cat_acc=cat_acc)



# Data Loading & Splitting


def load_and_split(data_path: str):
    log.info(f"Loading dataset: {data_path}")
    df = pd.read_excel(data_path)
    log.info(f"Dataset shape: {df.shape}")

    # Remove leakage columns
    drop = [c for c in EXCLUDE_COLS if c in df.columns]
    df.drop(columns=drop, inplace=True)
    if drop:
        log.info(f"Removed leakage columns: {drop}")

    # Convert numerics
    non_num = [COMPANY_COL, "listing_date", "lead_manager"]
    for col in [c for c in df.columns if c not in non_num]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # Clip extreme growth values
    for col in ["pat_yoy_growth", "pat_2y_growth"]:
        if col in df.columns:
            df[col] = df[col].clip(-500, 500)

    # Split
    train_df = df[df[TARGET_COL].notna()].copy().reset_index(drop=True)
    pred_df  = df[df[TARGET_COL].isna()].copy().reset_index(drop=True)

    log.info(f"Training rows  : {len(train_df)}")
    log.info(f"Prediction rows: {len(pred_df)}")

    if len(pred_df) == 0:
        raise ValueError(
            f"No ongoing IPOs found (no NaN in '{TARGET_COL}'). "
            "Ensure ongoing IPO rows have NaN in the target column."
        )

    log.info("Ongoing IPOs:")
    for name in pred_df[COMPANY_COL].tolist():
        log.info(f"  → {name.title().strip()}")

    return train_df, pred_df



# Part 1 — LSTM: PAT Profitability Sequence Learning


def train_lstm(train_df: pd.DataFrame, pred_df: pd.DataFrame):
    log.info("=" * 60)
    log.info("PART 1: Training LSTM on PAT sequence...")
    log.info("=" * 60)

    missing = [c for c in PAT_SEQ_COLS if c not in train_df.columns]
    if missing:
        raise ValueError(f"Missing PAT sequence columns: {missing}")

    imp_lstm = SimpleImputer(strategy="median")
    sc_lstm  = StandardScaler()

    def make_sequences(data, fit=False):
        v = data[PAT_SEQ_COLS].values
        v = imp_lstm.fit_transform(v) if fit else imp_lstm.transform(v)
        v = sc_lstm.fit_transform(v)  if fit else sc_lstm.transform(v)
        return v.reshape(len(v), 3, 1)   # (n, 3 timesteps, 1 feature)

    X_seq_tr = make_sequences(train_df, fit=True)
    X_seq_pr = make_sequences(pred_df,  fit=False)
    y_lstm   = train_df[TARGET_COL].values

    Xls_tr, Xls_val, yls_tr, yls_val = train_test_split(
        X_seq_tr, y_lstm,
        test_size=LSTM_VAL_SPLIT,
        random_state=LSTM_SEED,
    )

    tf.random.set_seed(LSTM_SEED)
    model = Sequential([
        LSTM(LSTM_UNITS, input_shape=(3, 1)),
        Dropout(LSTM_DROPOUT),
        Dense(LSTM_DENSE_UNITS, activation="relu"),
        Dropout(LSTM_DENSE_DROP),
        Dense(1),
    ])
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])

    es = EarlyStopping(
        monitor="val_loss",
        patience=LSTM_PATIENCE,
        restore_best_weights=True,
        verbose=0,
    )

    history = model.fit(
        Xls_tr, yls_tr,
        validation_data=(Xls_val, yls_val),
        epochs=LSTM_EPOCHS,
        batch_size=LSTM_BATCH_SIZE,
        callbacks=[es],
        verbose=0,
    )
    log.info(f"LSTM training complete — {len(history.history['loss'])} epochs")

    # Generate lstm_pat_score for all rows
    train_df = train_df.copy()
    pred_df  = pred_df.copy()
    train_df["lstm_pat_score"] = model.predict(X_seq_tr, verbose=0).flatten()
    pred_df["lstm_pat_score"]  = model.predict(X_seq_pr, verbose=0).flatten()

    # Save LSTM artifacts
    os.makedirs(MODEL_DIR, exist_ok=True)
    model.save(LSTM_MODEL_PATH)
    joblib.dump(imp_lstm, IMPUTER_PATH)
    joblib.dump(sc_lstm,  SCALER_PATH)
    log.info(f"LSTM saved to: {LSTM_MODEL_PATH}")

    return train_df, pred_df, history



# Part 2 — XGBoost: Main Prediction Engine


def train_xgboost(train_df: pd.DataFrame, pred_df: pd.DataFrame):
    log.info("=" * 60)
    log.info("PART 2: Training XGBoost...")
    log.info("=" * 60)

    # Build feature list
    exclude = set(EXCLUDE_COLS) | {
    TARGET_COL,
    "lstm_pat_score",
    COMPANY_COL
}
    feats   = [c for c in train_df.columns if c not in exclude] + ["lstm_pat_score"]
    log.info(f"XGBoost features ({len(feats)}): {feats}")

    imp_xgb = SimpleImputer(strategy="median")
    X_xgb   = imp_xgb.fit_transform(train_df[feats])
    y_xgb   = train_df[TARGET_COL].values
    X_pred  = imp_xgb.transform(pred_df[feats])

    Xx_tr, Xx_val, yx_tr, yx_val = train_test_split(
        X_xgb, y_xgb,
        test_size=XGB_VAL_SPLIT,
        random_state=XGB_SEED,
    )

    model = xgb.XGBRegressor(**XGB_PARAMS)
    model.fit(
        Xx_tr, yx_tr,
        eval_set=[(Xx_val, yx_val)],
        verbose=False,
    )

    # Metrics
    y_val_pred = model.predict(Xx_val)
    y_tr_pred  = model.predict(Xx_tr)
    val_metrics = accuracy_metrics(yx_val, y_val_pred)
    r2_train    = r2_score(yx_tr, y_tr_pred)
    gap         = r2_train - val_metrics["r2"]

    log.info(f"  MAE              : {val_metrics['mae']*100:.2f}%")
    log.info(f"  RMSE             : {val_metrics['rmse']*100:.2f}%")
    log.info(f"  R² (Validation)  : {val_metrics['r2']:.4f}")
    log.info(f"  R² (Train)       : {r2_train:.4f}")
    log.info(f"  Overfit Gap      : {gap:.4f}")
    log.info(f"  Direction Acc    : {val_metrics['dir_acc']:.1f}%")
    log.info(f"  Category Acc     : {val_metrics['cat_acc']:.1f}%")
    log.info(f"  Tolerance Acc    : {val_metrics['tol_acc']:.1f}%")

    # Feature importance
    feat_imp = pd.Series(
        model.feature_importances_, index=feats
    ).sort_values(ascending=False)

    # Save XGBoost + imputer + features
    joblib.dump(model,    XGB_MODEL_PATH)
    joblib.dump(imp_xgb,  os.path.join(MODEL_DIR, "imputer_xgb.pkl"))
    joblib.dump(feats,    FEATURES_PATH)
    log.info(f"XGBoost saved to: {XGB_MODEL_PATH}")

    return (model, X_pred, feats, feat_imp,
            yx_val, y_val_pred, yx_tr, y_tr_pred,
            val_metrics, r2_train, gap)



# Predictions


def generate_predictions(pred_df, xgb_model, X_pred, feats, feat_imp, train_df):
    pred_df = pred_df.copy()
    pred_df["Predicted Gain"] = xgb_model.predict(X_pred)
    medians = train_df[feats].median()

    def reason(row):
        lines = []
        for feat in feat_imp.index[:4]:
            val = row.get(feat, np.nan)
            med = medians.get(feat, np.nan)
            if pd.isna(val) or pd.isna(med):
                continue
            direction = "above" if val > med else "below"
            if feat in POS_HIGHER:
                sig = "✅ positive signal" if val > med else "⚠️ below median"
            elif feat in NEG_HIGHER:
                sig = "⚠️ elevated" if val > med else "✅ low — positive"
            else:
                sig = f"{direction} dataset median"
            g = feature_group(feat)
            tag = {"gmp": "  🟣 GMP", "pat": "  🟠 PAT/LSTM",
                   "sub": "  🟢 Subscription", "other": ""}.get(g, "")
            lines.append(f"  - {feat}: {val:.3f} (median={med:.3f}) → {sig}{tag}")
        return "\n".join(lines) if lines else "  - Based on available fundamentals"

    print("\n" + "═" * 72)
    print("  HYBRID MODEL — PREDICTIONS FOR ONGOING IPOs")
    print("═" * 72)

    for _, row in pred_df.iterrows():
        name  = str(row[COMPANY_COL]).title().strip()
        g     = row["Predicted Gain"]
        cat, emoji = categorise(g)
        gmp_s = f"₹{row['gmp_']:.0f}"             if not pd.isna(row.get("gmp_", np.nan)) else "N/A"
        qib_s = f"{row['qib_vs_retail']:.2f}"      if not pd.isna(row.get("qib_vs_retail", np.nan)) else "N/A"
        ret_s = f"{row['retail_demand_x']:.2f}x"   if not pd.isna(row.get("retail_demand_x", np.nan)) else "N/A"
        pat_g = f"{row['pat_yoy_growth']*100:.1f}%" if not pd.isna(row.get("pat_yoy_growth", np.nan)) else "N/A"

        print(f"\n  ╔══════════════════════════════════════════════════════════╗")
        print(f"  ║  IPO        : {name}")
        print(f"  ║  Pred. Gain : {g*100:+.2f}%  {emoji}  |  {cat}")
        print(f"  ║  GMP: {gmp_s}  |  QIB/Retail: {qib_s}  |  Retail: {ret_s}")
        print(f"  ║  PAT YoY Growth: {pat_g}")
        print(f"  ╠══════════════════════════════════════════════════════════╣")
        print(f"  ║  Key Drivers:")
        for line in reason(row).split("\n"):
            print(f"  ║{line}")
        print(f"  ╚══════════════════════════════════════════════════════════╝")

    return pred_df



# Visualisations


def generate_charts(
    yx_val, y_val_pred, yx_tr, y_tr_pred,
    val_metrics, r2_train, gap, feat_imp,
    history, pred_df, output_dir,
):
    os.makedirs(output_dir, exist_ok=True)
    P   = PALETTE
    plt.style.use("seaborn-v0_8-whitegrid")

    def fcol(f): return feature_color(f)
    legend_patches = [
        Patch(facecolor=P["orange"], label="PAT / LSTM"),
        Patch(facecolor=P["purple"], label="GMP"),
        Patch(facecolor=P["teal"],   label="Subscription"),
        Patch(facecolor=P["blue"],   label="Other"),
    ]

    mae  = val_metrics["mae"]
    rmse = val_metrics["rmse"]
    r2   = val_metrics["r2"]

    #  FIG 1: Performance Dashboard 
    fig1 = plt.figure(figsize=(22, 16))
    fig1.patch.set_facecolor(P["bg"])
    gs1  = gridspec.GridSpec(2, 3, figure=fig1, hspace=0.50, wspace=0.38)

    # Actual vs Predicted
    ax1 = fig1.add_subplot(gs1[0, :2]); ax1.set_facecolor(P["card"])
    sc  = ax1.scatter(yx_val*100, y_val_pred*100, alpha=0.55,
                      c=abs(y_val_pred-yx_val)*100, cmap="RdYlGn_r",
                      edgecolors="white", s=65, zorder=3)
    plt.colorbar(sc, ax=ax1, label="Absolute Error (%)", shrink=0.85)
    lo = min(float(yx_val.min()), float(y_val_pred.min()))*100 - 5
    hi = max(float(yx_val.max()), float(y_val_pred.max()))*100 + 5
    ax1.plot([lo, hi], [lo, hi], "--", color=P["red"], lw=2, label="Perfect Prediction")
    ax1.fill_between([lo, hi], [lo-mae*100, hi-mae*100], [lo+mae*100, hi+mae*100],
                     alpha=0.07, color=P["blue"], label=f"±{mae*100:.1f}% MAE band")
    ax1.set_xlim(lo, hi); ax1.set_ylim(lo, hi)
    ax1.set_xlabel("Actual Listing Gain (%)", fontsize=12)
    ax1.set_ylabel("Predicted Listing Gain (%)", fontsize=12)
    ax1.set_title("Validation — Actual vs Predicted\n(LSTM + XGBoost Hybrid)",
                  fontsize=14, fontweight="bold", pad=12)
    ax1.legend(fontsize=10)
    ax1.text(0.04, 0.93, f"R² = {r2:.3f}", transform=ax1.transAxes, fontsize=13,
             color=P["green"], fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.35", facecolor="#DCFCE7",
                       edgecolor=P["green"], alpha=0.85))
    ax1.text(0.04, 0.84, f"MAE = {mae*100:.1f}%", transform=ax1.transAxes, fontsize=11,
             color=P["orange"], fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="#FEF3C7",
                       edgecolor=P["orange"], alpha=0.85))

    # Overfit check
    ax2 = fig1.add_subplot(gs1[0, 2]); ax2.set_facecolor(P["card"])
    b2  = ax2.bar(["Train R²", "Val R²"], [r2_train, r2],
                  color=[P["blue"], P["green"]], width=0.45, edgecolor="white",
                  linewidth=2, zorder=3)
    for bar, val in zip(b2, [r2_train, r2]):
        ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.01,
                 f"{val:.3f}", ha="center", fontsize=13, fontweight="bold")
    ax2.set_ylim(0, max(r2_train, r2)*1.35)
    ax2.set_title("Overfit Check — Train vs Val R²", fontsize=13, fontweight="bold", pad=12)
    ax2.text(0.5, -0.13,
             f"Gap = {gap:.3f}  →  {'✅ Low' if abs(gap) < 0.15 else '⚠️ Moderate'}",
             transform=ax2.transAxes, ha="center", fontsize=10,
             color=P["green"] if abs(gap) < 0.15 else P["orange"], fontweight="bold")

    # Metrics bar
    ax3 = fig1.add_subplot(gs1[1, :2]); ax3.set_facecolor(P["card"])
    b3  = ax3.bar(["MAE", "RMSE", "R² Score"], [mae, rmse, r2],
                  color=[P["orange"], P["red"], P["green"]],
                  width=0.4, edgecolor="white", linewidth=2, zorder=3)
    for bar, val, lbl in zip(b3, [mae, rmse, r2], ["MAE", "RMSE", "R²"]):
        ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.005,
                 f"{val:.4f}", ha="center", fontsize=13, fontweight="bold")
        if lbl != "R²":
            ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()/2,
                     f"{val*100:.1f}%", ha="center", fontsize=11,
                     color="white", fontweight="bold")
    ax3.set_ylim(0, max(mae, rmse, r2)*1.3)
    ax3.set_title("Performance Metrics (Validation Set)", fontsize=13, fontweight="bold", pad=12)

    # LSTM curve
    ax4 = fig1.add_subplot(gs1[1, 2]); ax4.set_facecolor(P["card"])
    ax4.plot(history.history["loss"],     color=P["blue"],   lw=2, label="Train Loss")
    ax4.plot(history.history["val_loss"], color=P["orange"], lw=2,
             label="Val Loss", linestyle="--")
    ax4.set_xlabel("Epoch", fontsize=11); ax4.set_ylabel("MSE Loss", fontsize=11)
    ax4.set_title("LSTM Training Curve\nPAT Profitability Learning",
                  fontsize=13, fontweight="bold", pad=12)
    ax4.legend(fontsize=10)
    ax4.text(0.5, -0.12, f"Early stopped at epoch {len(history.history['loss'])}",
             transform=ax4.transAxes, ha="center", fontsize=9,
             color=P["sub"], style="italic")

    fig1.suptitle("LSTM + XGBoost Hybrid — Performance Dashboard",
                  fontsize=18, fontweight="bold", y=0.99, color=P["text"])
    p1 = os.path.join(output_dir, "fig1_performance_dashboard.png")
    plt.savefig(p1, dpi=150, bbox_inches="tight", facecolor=P["bg"])
    plt.close()
    log.info(f"Saved: {p1}")

    #  FIG 2: Feature Importance
    fig2 = plt.figure(figsize=(22, 13))
    fig2.patch.set_facecolor(P["bg"])
    gs2  = gridspec.GridSpec(1, 3, figure=fig2, wspace=0.42)

    ax5 = fig2.add_subplot(gs2[0, :2]); ax5.set_facecolor(P["card"])
    fi  = feat_imp
    bc  = [fcol(f) for f in fi.index]
    ax5.barh(range(len(fi)), fi.values, color=bc, edgecolor="white", height=0.70, zorder=3)
    ax5.set_yticks(range(len(fi)))
    ax5.set_yticklabels(fi.index, fontsize=9)
    ax5.invert_yaxis()
    ax5.set_xlabel("Importance Score", fontsize=11)
    ax5.set_title("XGBoost Feature Importance\n"
                  "🟠 PAT/LSTM   🟣 GMP   🟢 Subscription   🔵 Other",
                  fontsize=13, fontweight="bold", pad=12)
    for bar, val in zip(ax5.patches, fi.values):
        ax5.text(bar.get_width()+0.001, bar.get_y()+bar.get_height()/2,
                 f"{val:.4f}", va="center", fontsize=8)
    ax5.legend(handles=legend_patches, fontsize=9, loc="lower right")

    # Donut
    groups = {
        "PAT+LSTM": fi[[f for f in fi.index if feature_group(f) == "pat"]].sum(),
        "GMP"     : fi[[f for f in fi.index if feature_group(f) == "gmp"]].sum(),
        "Sub"     : fi[[f for f in fi.index if feature_group(f) == "sub"]].sum(),
        "Other"   : fi[[f for f in fi.index if feature_group(f) == "other"]].sum(),
    }
    ax6 = fig2.add_subplot(gs2[0, 2]); ax6.set_facecolor(P["card"])
    pie_d = [(v, f"{k}\n{v*100:.1f}%", c) for (k, v), c in
             zip(groups.items(), [P["orange"], P["purple"], P["teal"], P["blue"]]) if v > 0.005]
    wedges, texts, ats = ax6.pie(
        [x[0] for x in pie_d], labels=[x[1] for x in pie_d],
        autopct="%1.1f%%", colors=[x[2] for x in pie_d], startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 2, "width": 0.55},
        textprops={"fontsize": 10},
    )
    for at in ats: at.set_fontweight("bold")
    ax6.text(0, 0, "Model\nWeight", ha="center", va="center",
             fontsize=11, fontweight="bold", color=P["text"])
    ax6.set_title("Feature Group Contribution", fontsize=13, fontweight="bold", pad=12)

    fig2.suptitle("LSTM + XGBoost — Feature Importance Analysis",
                  fontsize=18, fontweight="bold", y=1.0, color=P["text"])
    p2 = os.path.join(output_dir, "fig2_feature_importance.png")
    plt.savefig(p2, dpi=150, bbox_inches="tight", facecolor=P["bg"])
    plt.close()
    log.info(f"Saved: {p2}")

    #  FIG 3: Predictions Chart 
    fig3 = plt.figure(figsize=(22, 11))
    fig3.patch.set_facecolor(P["bg"])
    gs3  = gridspec.GridSpec(1, 3, figure=fig3, wspace=0.4)

    names     = [str(r[COMPANY_COL]).title().strip() for _, r in pred_df.iterrows()]
    short     = [n[:30]+"…" if len(n) > 30 else n for n in names]
    gains_pct = pred_df["Predicted Gain"].values * 100
    gmps      = pred_df["gmp_"].values

    ax7 = fig3.add_subplot(gs3[0, :2]); ax7.set_facecolor(P["card"])
    gc  = [P["green"] if g>10 else P["teal"] if g>3 else P["orange"] if g>=0 else P["red"]
           for g in gains_pct]
    ax7.barh(range(len(short)), gains_pct, color=gc, edgecolor="white", height=0.65, zorder=3)
    ax7.set_yticks(range(len(short))); ax7.set_yticklabels(short, fontsize=9.5)
    ax7.axvline(0,  color="black",    linewidth=1.2)
    ax7.axvline(10, color=P["green"], linewidth=1.5, ls="--", alpha=0.6, label=">10% Strong Profit")
    ax7.axvline(3,  color=P["teal"],  linewidth=1.5, ls=":",  alpha=0.6, label=">3% Moderate")
    ax7.set_xlabel("Predicted Listing Gain (%)", fontsize=12)
    ax7.set_title("Predicted Listing Gains — Ongoing / Unlisted IPOs",
                  fontsize=13, fontweight="bold", pad=12)
    ax7.legend(fontsize=9, loc="lower right")
    for i, g in enumerate(gains_pct):
        gn = f" GMP=₹{gmps[i]:.0f}" if not np.isnan(float(gmps[i])) else " GMP=N/A"
        ax7.text(g+(0.6 if g >= 0 else -0.6), i, f"{g:+.1f}%{gn}",
                 va="center", ha="left" if g >= 0 else "right",
                 fontsize=8.5, fontweight="bold", color=P["text"])

    ax8 = fig3.add_subplot(gs3[0, 2]); ax8.set_facecolor(P["card"])
    cat_c = {"Strong\nProfit>10%": 0, "Moderate\n3–10%": 0,
             "Low\n0–3%": 0, "Loss\nRisk<0%": 0}
    for g in gains_pct:
        if g > 10:   cat_c["Strong\nProfit>10%"] += 1
        elif g > 3:  cat_c["Moderate\n3–10%"]    += 1
        elif g >= 0: cat_c["Low\n0–3%"]           += 1
        else:         cat_c["Loss\nRisk<0%"]       += 1
    cat_cm = {"Strong\nProfit>10%": P["green"], "Moderate\n3–10%": P["teal"],
              "Low\n0–3%": P["orange"], "Loss\nRisk<0%": P["red"]}
    nz = {k: v for k, v in cat_c.items() if v > 0}
    ax8.pie(list(nz.values()), labels=list(nz.keys()),
            autopct=lambda p: f"{int(round(p*sum(nz.values())/100))}",
            colors=[cat_cm[k] for k in nz], startangle=90,
            wedgeprops=dict(width=0.55, edgecolor="white", linewidth=2.5),
            textprops={"fontsize": 11, "fontweight": "bold"})
    ax8.text(0, 0, f"{len(gains_pct)}\nIPOs", ha="center", va="center",
             fontsize=14, fontweight="bold", color=P["text"])
    ax8.set_title("Category Distribution", fontsize=13, fontweight="bold", pad=12)

    fig3.suptitle("LSTM + XGBoost — Ongoing IPO Predictions",
                  fontsize=18, fontweight="bold", y=1.01, color=P["text"])
    plt.tight_layout()
    p3 = os.path.join(output_dir, "fig3_predictions.png")
    plt.savefig(p3, dpi=150, bbox_inches="tight", facecolor=P["bg"])
    plt.close()
    log.info(f"Saved: {p3}")

    #  FIG 4: Accuracy Dashboard 
    fig4 = plt.figure(figsize=(22, 12))
    fig4.patch.set_facecolor(P["bg"])
    gs4  = gridspec.GridSpec(1, 2, figure=fig4, wspace=0.42)

    ax9  = fig4.add_subplot(gs4[0, 0]); ax9.set_facecolor(P["card"])
    albl = ["Direction\nAccuracy\n(Profit/Loss)", "±10%\nTolerance\nAccuracy",
            "Category\nAccuracy", "R²\nExplained\n(×100%)"]
    aval = [val_metrics["dir_acc"], val_metrics["tol_acc"],
            val_metrics["cat_acc"], r2*100]
    acol = [P["green"], P["teal"], P["blue"], P["orange"]]
    bars9 = ax9.bar(albl, aval, color=acol, width=0.50, edgecolor="white",
                    linewidth=2.5, zorder=3)
    for bar, val in zip(bars9, aval):
        ax9.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1.0,
                 f"{val:.1f}%", ha="center", fontsize=18, fontweight="bold", color=P["text"])
    ax9.set_ylim(0, 120); ax9.set_ylabel("Accuracy (%)", fontsize=12)
    ax9.set_title("Overall Model Accuracy — Multiple Dimensions\n(Validation Set)",
                  fontsize=14, fontweight="bold", pad=12)
    ax9.axhline(50, color=P["gray"],  lw=1.2, ls="--", alpha=0.4, label="50% baseline")
    ax9.axhline(70, color=P["green"], lw=1.2, ls=":",  alpha=0.5, label="70% good")
    ax9.legend(fontsize=9)
    exp = (f"Direction Accuracy   {val_metrics['dir_acc']:.1f}%  — profit/loss correct\n"
           f"±10% Tolerance       {val_metrics['tol_acc']:.1f}%  — within ±10% of actual\n"
           f"Category Accuracy    {val_metrics['cat_acc']:.1f}%  — correct gain bucket\n"
           f"R² × 100%            {r2*100:.1f}%  — variance explained")
    ax9.text(0.5, -0.20, exp, transform=ax9.transAxes, ha="center", fontsize=11,
             color=P["text"], family="monospace",
             bbox=dict(boxstyle="round,pad=0.5", facecolor="#EFF6FF",
                       edgecolor=P["blue"], alpha=0.85))

    ax10 = fig4.add_subplot(gs4[0, 1]); ax10.set_facecolor(P["card"])
    bc10 = [fcol(f) for f in feat_imp.index]
    ax10.barh(range(len(feat_imp)), feat_imp.values, color=bc10,
              edgecolor="white", height=0.68, zorder=3)
    ax10.set_yticks(range(len(feat_imp)))
    ax10.set_yticklabels(feat_imp.index, fontsize=8.5)
    ax10.invert_yaxis()
    ax10.set_xlabel("Importance Score", fontsize=11)
    ax10.set_title("Complete Feature Importance (All Features)",
                   fontsize=13, fontweight="bold", pad=12)
    ax10.legend(handles=legend_patches, fontsize=9, loc="lower right")
    for bar, val in zip(ax10.patches, feat_imp.values):
        ax10.text(bar.get_width()+0.001, bar.get_y()+bar.get_height()/2,
                  f"{val:.3f}", va="center", fontsize=8)

    fig4.suptitle("LSTM + XGBoost — Overall Accuracy & Feature Importance",
                  fontsize=18, fontweight="bold", y=0.99, color=P["text"])
    p4 = os.path.join(output_dir, "fig4_accuracy_dashboard.png")
    plt.savefig(p4, dpi=150, bbox_inches="tight", facecolor=P["bg"])
    plt.close()
    log.info(f"Saved: {p4}")



# Accuracy Summary


def print_accuracy_summary(val_metrics, r2_train, gap, feat_imp):
    groups = {
        "PAT+LSTM": feat_imp[[f for f in feat_imp.index if feature_group(f) == "pat"]].sum(),
        "GMP"     : feat_imp[[f for f in feat_imp.index if feature_group(f) == "gmp"]].sum(),
        "Sub"     : feat_imp[[f for f in feat_imp.index if feature_group(f) == "sub"]].sum(),
        "Other"   : feat_imp[[f for f in feat_imp.index if feature_group(f) == "other"]].sum(),
    }
    r2 = val_metrics["r2"]
    print(f"\n{'█'*72}")
    print(f"  OVERALL MODEL ACCURACY — LSTM + XGBoost HYBRID")
    print(f"{'█'*72}")
    print(f"")
    print(f"  🎯 ACCURACY IN PERCENTAGE FORM:")
    print(f"  ╔══════════════════════════════════════════════════════════╗")
    print(f"  ║                                                          ║")
    print(f"  ║   Direction Accuracy   :   {val_metrics['dir_acc']:>6.1f}%                    ║")
    print(f"  ║   (correctly predicted profit vs loss direction)         ║")
    print(f"  ║                                                          ║")
    print(f"  ║   ±10% Tolerance Acc   :   {val_metrics['tol_acc']:>6.1f}%                    ║")
    print(f"  ║   (predictions within ±10% of actual gain)              ║")
    print(f"  ║                                                          ║")
    print(f"  ║   Category Accuracy    :   {val_metrics['cat_acc']:>6.1f}%                    ║")
    print(f"  ║   (Strong/Moderate/Low/Loss bucket correct)              ║")
    print(f"  ║                                                          ║")
    print(f"  ║   R² Score × 100       :   {r2*100:>6.1f}%                    ║")
    print(f"  ║   (variance in listing gains explained by model)         ║")
    print(f"  ║                                                          ║")
    print(f"  ╚══════════════════════════════════════════════════════════╝")
    print(f"")
    print(f"  📊 REGRESSION METRICS:")
    print(f"     MAE   : {val_metrics['mae']*100:.2f}%  — average prediction error")
    print(f"     RMSE  : {val_metrics['rmse']*100:.2f}% — penalised error")
    print(f"")
    print(f"  ⚙️  OVERFIT CHECK:")
    print(f"     Train R² : {r2_train:.4f}  |  Val R² : {r2:.4f}  |  Gap : {gap:.4f}")
    status = "✅ Low — generalises well" if abs(gap) < 0.15 else "⚠️ Use for direction only"
    print(f"     Status   : {status}")
    print(f"")
    print(f"  📈 FEATURE GROUP IMPORTANCE:")
    for k, v in groups.items():
        print(f"     {k:<12} : {v*100:.1f}%")
    print(f"{'█'*72}")



# Main Entry Point


def main():
    parser = argparse.ArgumentParser(description="Train IPO Hybrid Model")
    parser.add_argument("--data",       type=str, required=True, help="Path to Excel dataset")
    parser.add_argument("--output_dir", type=str, default=OUTPUT_DIR, help="Output directory for charts")
    args = parser.parse_args()

    os.makedirs(MODEL_DIR,        exist_ok=True)
    os.makedirs(args.output_dir,  exist_ok=True)

    # Load
    train_df, pred_df = load_and_split(args.data)

    # LSTM
    train_df, pred_df, history = train_lstm(train_df, pred_df)

    # XGBoost
    (xgb_model, X_pred, feats, feat_imp,
     yx_val, y_val_pred, yx_tr, y_tr_pred,
     val_metrics, r2_train, gap) = train_xgboost(train_df, pred_df)

    # Predictions
    pred_df = generate_predictions(pred_df, xgb_model, X_pred, feats, feat_imp, train_df)

    # Charts
    generate_charts(
        yx_val, y_val_pred, yx_tr, y_tr_pred,
        val_metrics, r2_train, gap, feat_imp,
        history, pred_df, args.output_dir,
    )

    # Accuracy summary
    print_accuracy_summary(val_metrics, r2_train, gap, feat_imp)

    log.info("✅ Training complete. All artifacts saved.")


if __name__ == "__main__":
    main()