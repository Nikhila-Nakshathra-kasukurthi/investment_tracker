# =============================================================================
# predict.py — IPO Listing Gain Prediction System
# Loads saved models and generates predictions for new/ongoing IPOs
#
# Usage:
#   python predict.py --data path/to/new_data.xlsx
#   python predict.py --data path/to/new_data.xlsx --output predictions.csv
# =============================================================================

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

from tensorflow.keras.models import load_model

from config import (
    TARGET_COL, COMPANY_COL, EXCLUDE_COLS, PAT_SEQ_COLS,
    POS_HIGHER, NEG_HIGHER,
    XGB_MODEL_PATH, LSTM_MODEL_PATH, IMPUTER_PATH, SCALER_PATH, FEATURES_PATH,
    MODEL_DIR, OUTPUT_DIR, LOG_DIR,
)
from train_model import feature_group, categorise

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "predict.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def load_artifacts():
    """Load all saved model artifacts."""
    log.info("Loading model artifacts...")

    for path in [XGB_MODEL_PATH, LSTM_MODEL_PATH, IMPUTER_PATH, SCALER_PATH, FEATURES_PATH]:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Artifact not found: {path}\n"
                "Run train_model.py first to generate model artifacts."
            )

    xgb_model  = joblib.load(XGB_MODEL_PATH)
    lstm_model = load_model(LSTM_MODEL_PATH)
    imp_lstm   = joblib.load(IMPUTER_PATH)
    sc_lstm    = joblib.load(SCALER_PATH)
    imp_xgb    = joblib.load(os.path.join(MODEL_DIR, "imputer_xgb.pkl"))
    feats      = joblib.load(FEATURES_PATH)

    log.info("✅ All artifacts loaded successfully")
    return xgb_model, lstm_model, imp_lstm, sc_lstm, imp_xgb, feats


def load_prediction_data(data_path: str) -> pd.DataFrame:
    """Load and preprocess new data for prediction."""
    log.info(f"Loading data: {data_path}")
    df = pd.read_excel(data_path)

    # Remove leakage columns
    drop = [c for c in EXCLUDE_COLS if c in df.columns]
    df.drop(columns=drop, inplace=True)

    # Convert numerics
    non_num = [COMPANY_COL, "listing_date", "lead_manager"]
    for col in [c for c in df.columns if c not in non_num]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    for col in ["pat_yoy_growth", "pat_2y_growth"]:
        if col in df.columns:
            df[col] = df[col].clip(-500, 500)

    # Use only rows where listing_gain_ is NaN (ongoing IPOs)
    if TARGET_COL in df.columns:
        pred_df = df[df[TARGET_COL].isna()].copy().reset_index(drop=True)
        log.info(f"Found {len(pred_df)} ongoing IPOs (NaN in {TARGET_COL})")
    else:
        pred_df = df.copy()
        log.info(f"No target column found — predicting all {len(pred_df)} rows")

    if len(pred_df) == 0:
        raise ValueError("No ongoing IPOs found. Ensure rows have NaN in listing_gain_.")

    return pred_df


def run_predictions(pred_df, xgb_model, lstm_model, imp_lstm, sc_lstm, imp_xgb, feats):
    """Generate LSTM scores then XGBoost predictions."""

    # Step 1: LSTM pat score
    missing_pat = [c for c in PAT_SEQ_COLS if c not in pred_df.columns]
    if missing_pat:
        raise ValueError(f"Missing PAT columns: {missing_pat}")

    v = pred_df[PAT_SEQ_COLS].values
    v = imp_lstm.transform(v)
    v = sc_lstm.transform(v)
    X_seq = v.reshape(len(v), 3, 1)
    pred_df = pred_df.copy()
    pred_df["lstm_pat_score"] = lstm_model.predict(X_seq, verbose=0).flatten()

    # Step 2: XGBoost prediction
    missing_feats = [f for f in feats if f not in pred_df.columns]
    if missing_feats:
        raise ValueError(f"Missing XGBoost features: {missing_feats}")

    X_pred = imp_xgb.transform(pred_df[feats])
    pred_df["Predicted Gain"] = xgb_model.predict(X_pred)

    return pred_df


def print_predictions(pred_df, feats, train_medians=None):
    """Print formatted predictions with reasoning."""
    print("\n" + "═" * 72)
    print("  LSTM + XGBoost HYBRID — ONGOING IPO PREDICTIONS")
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
        print(f"  ╚══════════════════════════════════════════════════════════╝")

    return pred_df


def main():
    parser = argparse.ArgumentParser(description="Predict IPO Listing Gains")
    parser.add_argument("--data",   type=str, required=True, help="Path to Excel dataset")
    parser.add_argument("--output", type=str, default=os.path.join(OUTPUT_DIR, "predictions.csv"),
                        help="Path to save predictions CSV")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load artifacts
    xgb_model, lstm_model, imp_lstm, sc_lstm, imp_xgb, feats = load_artifacts()

    # Load data
    pred_df = load_prediction_data(args.data)

    # Predict
    pred_df = run_predictions(pred_df, xgb_model, lstm_model, imp_lstm, sc_lstm, imp_xgb, feats)

    # Print
    print_predictions(pred_df, feats)

    # Save
    out_cols = [COMPANY_COL, "Predicted Gain", "gmp_", "retail_demand_x", "qib_vs_retail"]
    out_cols = [c for c in out_cols if c in pred_df.columns]
    pred_df[out_cols].to_csv(args.output, index=False)
    log.info(f"✅ Predictions saved to: {args.output}")


if __name__ == "__main__":
    main()