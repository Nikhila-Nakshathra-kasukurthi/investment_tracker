# IPO Listing Gain Prediction System
### LSTM + XGBoost Hybrid | Production-Ready | AWS-Deployable

---

## Architecture

```
PAT 3-Year Sequence ──► LSTM(32) ──► lstm_pat_score ──┐
                                                        ▼
All Fundamentals + GMP + Subscriptions + lstm_pat_score ──► XGBoost ──► Predicted Gain %
```

---

## Project Structure

```
ipo_prediction_system/
│
├── config.py            ← All settings, paths, hyperparameters
├── train_model.py       ← Full training pipeline (LSTM + XGBoost)
├── predict.py           ← Load saved models, predict new IPOs
├── colab_notebook.py    ← Single-file Colab-compatible version
├── requirements.txt     ← Python dependencies
├── README.md            ← This file
│
├── models/              ← Saved model artifacts (auto-created)
│   ├── xgb_model.pkl
│   ├── lstm_model.h5
│   ├── imputer.pkl
│   ├── imputer_xgb.pkl
│   ├── scaler.pkl
│   └── feature_list.pkl
│
├── outputs/             ← Charts and predictions (auto-created)
│   ├── fig1_performance_dashboard.png
│   ├── fig2_feature_importance.png
│   ├── fig3_predictions.png
│   ├── fig4_accuracy_dashboard.png
│   └── predictions.csv
│
└── logs/                ← Training and prediction logs (auto-created)
    ├── train.log
    └── predict.log
```

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Train the model
```bash
python train_model.py --data path/to/your_dataset.xlsx
```

### 3. Predict for new IPOs
```bash
python predict.py --data path/to/new_data.xlsx --output outputs/predictions.csv
```

### 4. Run in Google Colab
Upload `colab_notebook.py` to Colab and run all cells.

---

## Dataset Requirements

Your Excel file must contain:

| Column | Description |
|---|---|
| `company` | IPO name |
| `listing_gain_` | Target — **NaN for ongoing IPOs** |
| `log_pat_2nd_previous_year__cr` | PAT log (oldest) |
| `log_pat_previous_year__cr` | PAT log (previous) |
| `log_pat_current_year__cr` | PAT log (current) |
| `gmp_` | Grey Market Premium |
| `retail_demand_x` | Retail subscription demand |
| `qib_vs_retail` | QIB/Retail demand ratio |
| `pat_yoy_growth` | PAT year-on-year growth |

Ongoing IPOs = rows where `listing_gain_` is **NaN**.

---

## AWS Deployment

### Option A — EC2
```bash
# On your EC2 instance
git clone <your-repo>
cd ipo_prediction_system
pip install -r requirements.txt
python train_model.py --data s3://your-bucket/dataset.xlsx
```

### Option B — SageMaker
Use `train_model.py` as a SageMaker training script.
Set `MODEL_DIR` to `/opt/ml/model` in `config.py`.

### Option C — Lambda + API Gateway
Wrap `predict.py` in a Lambda handler.
Load models from S3 at cold start.

---

## Model Performance

| Metric | Typical Value |
|---|---|
| Direction Accuracy | ~81% |
| ±10% Tolerance Accuracy | ~51% |
| Category Accuracy | ~46% |
| R² Score | ~0.38 |
| Overfit Gap | <0.01 ✅ |

---

## Notes

- **No data leakage** — post-listing columns are excluded automatically
- **Overfitting controlled** — strict XGBoost hyperparameters (max_depth=3, reg_lambda=4.0)
- **LSTM is lightweight** — 32 units only, designed for ~389 row datasets
- Predictions are **directional guidance**, not financial advice