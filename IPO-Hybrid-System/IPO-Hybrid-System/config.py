# =============================================================================
# config.py — IPO Listing Gain Prediction System
# Central configuration for all modules
# =============================================================================

import os

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR     = os.path.join(BASE_DIR, "models")
OUTPUT_DIR    = os.path.join(BASE_DIR, "outputs")
LOG_DIR       = os.path.join(BASE_DIR, "logs")

XGB_MODEL_PATH  = os.path.join(MODEL_DIR, "xgb_model.pkl")
LSTM_MODEL_PATH = os.path.join(MODEL_DIR, "lstm_model.h5")
IMPUTER_PATH    = os.path.join(MODEL_DIR, "imputer.pkl")
SCALER_PATH     = os.path.join(MODEL_DIR, "scaler.pkl")
FEATURES_PATH   = os.path.join(MODEL_DIR, "feature_list.pkl")

# ── Dataset ───────────────────────────────────────────────────────────────────
TARGET_COL      = "listing_gain_"
COMPANY_COL     = "company"
DATE_COL        = "listing_date"

# Columns to always exclude (identifiers + leakage)
EXCLUDE_COLS = [
     "listing_date", "lead_manager",
    # Post-listing leakage — would cause data leakage if used
    "listing_price", "bse_open", "bse_high", "bse_low",
    "nse_open", "nse_open_", "nse_high", "nse_low", "last_trade",
]

# PAT sequence columns for LSTM (in chronological order: oldest → newest)
PAT_SEQ_COLS = [
    "log_pat_2nd_previous_year__cr",
    "log_pat_previous_year__cr",
    "log_pat_current_year__cr",
]

# ── Feature Groups (for importance colouring & reasoning) ─────────────────────
PAT_KEYWORDS  = ["pat", "log_pat", "lstm"]
GMP_KEYWORDS  = ["gmp"]
SUB_KEYWORDS  = ["demand", "qib", "nii", "retail"]

# Features that are better when HIGHER
POS_HIGHER = {
    "roe_", "roce_", "pat_margin_", "pat_yoy_growth", "pat_2y_growth",
    "gmp_", "gmp_percent", "retail_demand_x", "qib_vs_retail",
    "eps_pre_ipo_", "log_pat_current_year__cr", "lstm_pat_score",
    "promoter_holding_pre_ipo_",
}
# Features that are better when LOWER
NEG_HIGHER = {
    "debtequity", "pe_pre_ipo_x", "pe_post_ipo_x", "price_to_book_value",
}

# ── LSTM Hyperparameters ──────────────────────────────────────────────────────
LSTM_UNITS       = 32
LSTM_DROPOUT     = 0.25
LSTM_DENSE_UNITS = 16
LSTM_DENSE_DROP  = 0.15
LSTM_EPOCHS      = 150
LSTM_BATCH_SIZE  = 16
LSTM_PATIENCE    = 20
LSTM_VAL_SPLIT   = 0.20
LSTM_SEED        = 42

# ── XGBoost Hyperparameters ───────────────────────────────────────────────────
XGB_PARAMS = {
    "n_estimators"    : 250,
    "learning_rate"   : 0.04,
    "max_depth"       : 3,
    "subsample"       : 0.75,
    "colsample_bytree": 0.65,
    "reg_alpha"       : 0.8,
    "reg_lambda"      : 4.0,
    "min_child_weight": 8,
    "gamma"           : 0.3,
    "random_state"    : 42,
    "n_jobs"          : -1,
    "verbosity"       : 0,
}
XGB_VAL_SPLIT = 0.20
XGB_SEED      = 42

# ── Prediction Categories ─────────────────────────────────────────────────────
CATEGORIES = [
    (0.10,  "Strong Profit (>10%)",    "🟢"),
    (0.03,  "Moderate Profit (3–10%)", "🟡"),
    (0.00,  "Low/Uncertain (0–3%)",    "⚪"),
    (-9999, "Loss Risk (<0%)",         "🔴"),
]

# ── Chart Colours ─────────────────────────────────────────────────────────────
PALETTE = {
    "blue"  : "#2563EB",
    "green" : "#059669",
    "orange": "#F59E0B",
    "red"   : "#DC2626",
    "gray"  : "#6B7280",
    "purple": "#7C3AED",
    "teal"  : "#0D9488",
    "bg"    : "#F8FAFC",
    "card"  : "#FFFFFF",
    "text"  : "#111827",
    "sub"   : "#6B7280",
}