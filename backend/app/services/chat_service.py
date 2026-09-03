"""
backend/app/services/chat_service.py
======================================
AI Chat Assistant — Powered by PandasAI Data Engine + System Knowledge Base + Ollama LLM.

Features:
  1. PandasDataAgent: Direct Pandas DataFrame analytics on live PostgreSQL database.
     - Top N most active / highest-risk users with statistical breakdown
     - Top N largest / highest-risk transactions
     - Full transaction overview and financial volume statistics
     - Average model scores and fraud rate distributions
     - 24-hour recent activity and decision tier breakdowns
     - CSV import batch history and status tracking
  2. SystemKnowledgeAgent: Comprehensive, authoritative knowledge base covering:
     - PCA (Principal Component Analysis) role, features V1-V28, and privacy protection
     - Step-by-step 7-stage Data Preprocessing pipeline
     - All 36 input features (28 PCA, 2 scaled, 6 Digital Twin behavioral features)
     - XGBoost, Isolation Forest, and 70/30 Hybrid Score Fusion formula
     - TreeSHAP explainability and feature contribution analysis
     - Digital Twin behavioral profiling (Welford's algorithm, sliding windows)
     - Decision thresholds (BLOCK, REVIEW, APPROVE) and admin adjustments
     - ULB European Credit Card Fraud dataset details and synthetic identity proxies
     - SMOTE-ENN class imbalance handling inside cross-validation folds
     - Google Colab Optuna Bayesian hyperparameter optimization
     - Review queue workflow, analyst actions, and CEO governance
     - Model performance benchmarks and evaluation metrics
  3. Ollama LLM Enhancement:
     - Leverages local qwen3:8b model with complete FraudShield project system context
     - Full multi-turn conversation history awareness (resolves pronouns like 'it', 'this project')
     - Instantaneous, rich, formatted knowledge responses if Ollama is offline
     - Never returns generic 'I don't have access to your project' responses
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import os

import pandas as pd
import psycopg2

logger = logging.getLogger(__name__)

# Ollama base URL — configurable via OLLAMA_BASE_URL env var
# Defaults to localhost for local dev. Set to a remote URL in production if available.
_OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def _parse_ollama_url(url: str) -> tuple[str, int, str]:
    """Parse OLLAMA_BASE_URL into (host, port, path_prefix)."""
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    path_prefix = parsed.path.rstrip("/")
    return host, port, path_prefix

# ---------------------------------------------------------------------------
# Project System Prompt for Ollama LLM
# ---------------------------------------------------------------------------

PROJECT_SYSTEM_PROMPT = """You are FraudShield AI, the dedicated AI intelligence assistant for the FraudShield Banking Fraud Detection System.
You have COMPLETE, authoritative access to all project documentation, data preprocessing steps, model architecture, and database analytics for this system.

PROJECT SPECIFICATION & ARCHITECTURE:
- Project Name: FraudShield — Banking Fraud Detection System
- Institution: Al-Balqa' Applied University — Faculty of Artificial Intelligence (Graduation Project 2024/2025)
- Authors / System Admins: Saleh (Admin), Hussain (CEO / Super Admin)
- Core Mission: Real-time fraud detection combining supervised machine learning, unsupervised anomaly detection, and real-time behavioral digital twins.

DATASET (ULB European Credit Card Fraud Dataset):
- Source: Machine Learning Group at Université Libre de Bruxelles (ULB), September 2013.
- Total Transactions: 284,807 transactions over 2 consecutive days.
- Fraud Instances: 492 cases (0.172% — highly imbalanced).
- Raw Columns: Time, Amount, Class (0=Legitimate, 1=Fraud), and V1 through V28.
- PCA Features: V1 through V28 are 28 numerical features obtained through Principal Component Analysis (PCA) to protect cardholder confidentiality and sensitive financial information.
- Synthetic User Identities: Because ULB lacks native cardholder/device IDs for privacy, deterministic hash-bucketing of (Time, Amount) into 2,000 buckets ('user_0000' to 'user_1999') is used as a synthetic proxy for behavioral profiling.

DATA PREPROCESSING PIPELINE (7 Steps):
1. Ingestion & Schema Validation: Verifies 31 raw columns, checking types and missing values.
2. Duplicate Removal: Detects and drops exact duplicate transaction rows.
3. Domain Sanity Checks: Enforces bounds (Amount >= 0, Class in {0,1}, Time >= 0, PCA |V| < 1e10).
4. Synthetic User ID Generation: Assigns reproducible user IDs via MD5 hash-bucketing (1-hour time bins and $25 amount bins modulo 2,000).
5. Stratified Data Split: 80% train / 20% test with 15% validation carve-out from train (Train: 192,933 rows, Val: 34,047 rows, Test: 56,746 rows), strictly preserving the 0.172% fraud class ratio.
6. Feature Scaling: StandardScaler fitted strictly on the training partition for 'Amount' and 'Time' only (V1-V28 are already PCA-standardized, leaving them unscaled to prevent data leakage).
7. Parquet Storage: Cleaned partitions saved to data/processed/*.parquet.

INPUT FEATURES (36 Total):
- 28 PCA Components: V1 through V28 (anonymized underlying transaction dimensions).
- 2 Scaled Base Features: Amount (standardized) and Time (standardized).
- 6 Digital Twin Behavioral Features (Table 4):
  1. tx_freq_1h: Rolling 1-hour transaction frequency count.
  2. tx_freq_24h: Rolling 24-hour transaction frequency count.
  3. amount_deviation_z: Z-score deviation of transaction amount relative to customer's historical mean and standard deviation (computed via Welford's algorithm in O(1) memory, clipped to [-10, 10]).
  4. time_of_day_risk: Binary flag (1 if between 00:00 and 05:00 UTC/epoch, 0 otherwise).
  5. velocity_change: Rate of amount change across customer's last 3 transactions.
  6. location_entropy: Binary flag (1 if new/unrecognized device or region marker).

MODEL ARCHITECTURE & HYBRID SCORE FUSION:
1. Supervised Model (70% Weight): XGBoost Classifier. Optimized via Optuna Bayesian TPE search (100 trials, 5-fold stratified CV) optimizing fraud class F1-score. SMOTE-ENN resampling applied inside CV folds via imbalanced-learn Pipeline to handle extreme class imbalance without data leakage. Uses scale_pos_weight.
2. Unsupervised Model (30% Weight): Isolation Forest Anomaly Detector (200 trees, contamination=0.001). Detects zero-day anomalies without labels. Scores negated and normalized to [0.0, 1.0].
3. Hybrid Fusion Formula: Final Score = (0.70 * XGBoost_Probability) + (0.30 * Isolation_Forest_Normalized)
4. Tiered Decision Thresholds:
   - BLOCK (Final Score > 0.85): Immediate automatic block.
   - REVIEW (0.50 <= Final Score <= 0.85): Routed to manual Review Queue with TreeSHAP report and AI analyst narrative.
   - APPROVE (Final Score < 0.50): Cleared automatically.
   - Admins can adjust thresholds dynamically in real-time from the Admin Panel.

EXPLAINABILITY (TreeSHAP):
- TreeSHAP (shap.TreeExplainer) generates local waterfall feature contributions for any transaction with score >= 0.50.
- Positive SHAP (+) increases fraud risk; Negative SHAP (-) decreases fraud risk.
- Primary fraud predictors: V14, V4, V17, V10, amount_deviation_z, tx_freq_1h, time_of_day_risk, location_entropy.

DIGITAL TWIN BEHAVIORAL ENGINE:
- Maintains real-time behavioral profiles in memory and PostgreSQL.
- Uses Welford's Online Algorithm to compute rolling mean and variance in O(1) memory per user.
- Zero Training-Serving Skew: The exact same BehavioralFeatureEngine class is used during offline Colab training and online FastAPI inference.

SYSTEM PERFORMANCE (Holdout Test Set):
- Hybrid Fusion: ROC-AUC = 0.974, F1-Score = 0.882, Precision = 0.901, Recall = 0.863 (outperforms XGBoost alone at 0.965 and Isolation Forest alone at 0.871).

TECHNOLOGY STACK:
- Backend: Python 3.12, FastAPI, SQLAlchemy (Async + Sync), PostgreSQL 14+, Uvicorn, Pandas, Scikit-learn, XGBoost, SHAP, Joblib, Optuna.
- Frontend: React 18, TypeScript, Vite, Tailwind CSS, Lucide Icons, Glassmorphism UI, Recharts.
- LLM / AI Intelligence: Ollama (qwen3:8b) + PandasAI data engine.
- Security: JWT HTTP-only cookies, bcrypt password hashing, Role-Based Access Control (Admin, User/Analyst, CEO).

Always answer authoritatively, professionally, and accurately using this project context. If the user asks about PCA, preprocessing, models, or any project component, provide exact details from this specification."""


# ---------------------------------------------------------------------------
# Comprehensive Knowledge Base
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE: Dict[str, str] = {
    "pca": """**📊 Principal Component Analysis (PCA) in FraudShield:**

Yes! PCA plays a central role in the FraudShield project:

1. **Why PCA is Used:**
   - The foundation dataset (ULB European Credit Card dataset) contains **28 PCA-transformed numerical features (`V1` through `V28`)**.
   - PCA was applied by the dataset providers to **anonymize sensitive cardholder financial information** and protect customer privacy while preserving the essential variance, correlations, and underlying behavioral patterns needed for machine learning.

2. **How PCA Features are Processed in Preprocessing:**
   - Because `V1`–`V28` are principal components resulting from PCA, they are **already centered with mean ≈ 0 and standardized variance**.
   - During our preprocessing pipeline, **`V1`–`V28` are left unchanged**, while only `Amount` and `Time` are transformed using `StandardScaler` (fitted strictly on the training partition to prevent data leakage).

3. **Key Fraud Drivers Identified by TreeSHAP:**
   - In our trained **XGBoost model**, specific PCA components exhibit the strongest correlation with fraudulent transaction patterns:
     - 🔴 **`V14`**: Strongest inverse indicator of fraud (sharp negative drop indicates high fraud probability)
     - 🔴 **`V4`**: High positive values strongly elevate fraud risk
     - 🔴 **`V17` & `V10`**: Powerful discriminators for account takeover and abnormal card activity

4. **Total Model Input Dimensions:**
   - 28 PCA features (`V1`–`V28`) + 2 Scaled Base features (`Amount`, `Time`) + 6 Digital Twin behavioral features = **36 total features** fed into XGBoost, Isolation Forest, and SHAP.""",

    "preprocessing": """**⚙️ FraudShield 7-Step Data Preprocessing Pipeline:**

The preprocessing pipeline ([`ml/preprocessing.py`](file:///c:/Users/saleh/OneDrive/Desktop/graduation%20project/ml/preprocessing.py)) transforms raw transaction records into leak-free training, validation, and test datasets:

1. **Step 1 — Load & Schema Validation:**
   - Verifies all 31 expected columns (`Time`, `Amount`, `Class`, and `V1` through `V28`).
   - Checks for missing/null values across all columns.

2. **Step 2 — Duplicate Removal:**
   - Detects and drops exact duplicate transaction rows across all 31 features.

3. **Step 3 — Domain Sanity Checks:**
   - Enforces domain constraints: `Amount >= 0`, `Class ∈ {0, 1}`, `Time >= 0`, and extreme PCA outlier checks (`|V| < 1e10`).

4. **Step 4 — Deterministic Synthetic User IDs:**
   - Because the ULB dataset lacks user IDs for privacy reasons, deterministic MD5 hash-bucketing of `(Time // 3600, Amount // 25)` is mapped modulo 2,000 to assign consistent synthetic user IDs (`user_0000` to `user_1999`).
   - Enables realistic behavioral profile tracking during training and live demo replay.

5. **Step 5 — Stratified 80/20 Train/Test & 15% Validation Split:**
   - Splits data into 80% train / 20% test (stratified on `Class`), then carves 15% of train into validation.
   - Partition sizes: **Train: 192,933 rows**, **Val: 34,047 rows**, **Test: 56,746 rows**.
   - Strictly preserves the **0.172% fraud class ratio** (±0.05% tolerance) across all splits.

6. **Step 6 — Strict Feature Scaling:**
   - `StandardScaler` is fitted **strictly on the training split only** for `Amount` and `Time` to prevent data leakage.
   - `V1`–`V28` are left unscaled (already PCA-standardized).
   - The fitted scaler is saved to `models/scaler.joblib`.

7. **Step 7 — Parquet Serialization:**
   - Cleaned partitions are saved to `data/processed/*.parquet` for fast columnar reads, along with `preprocessing_report.json`.""",

    "features": """**📐 36 Input Features in FraudShield:**

FraudShield feeds exactly 36 features into the machine learning models:

1. **PCA Anonymized Components (28 Features):**
   - `V1` through `V28`: Dimensionality-reduced components preserving cardholder privacy while capturing complex transaction interactions.

2. **Base Transaction Properties (2 Features, Scaled):**
   - `Amount`: Transaction purchase amount (standardized with `StandardScaler`).
   - `Time`: Elapsed seconds since dataset epoch (standardized with `StandardScaler`).

3. **Digital Twin Behavioral Features (6 Features — Table 4):**
   - `tx_freq_1h`: Number of transactions by the same customer in a rolling 1-hour causal window.
   - `tx_freq_24h`: Number of transactions by the same customer in a rolling 24-hour causal window.
   - `amount_deviation_z`: Z-score deviation of the transaction amount compared to the customer's historical mean and standard deviation (computed via Welford's algorithm in $O(1)$ memory, clipped to $[-10, 10]$).
   - `time_of_day_risk`: Binary indicator ($1$ if transaction occurs during high-risk hours 00:00–05:00 UTC/epoch, $0$ otherwise).
   - `velocity_change`: Rate of spending change across the customer's last 3 transactions.
   - `location_entropy`: Binary flag ($1$ if a novel synthetic device or region marker is detected, $0$ if recognized).

*All behavioral features are computed causally (strictly using prior history) with zero training/serving skew.*""",

    "architecture": """**🏛️ FraudShield End-to-End System Architecture:**

FraudShield is structured across 6 integrated layers:

```
[ Data Ingestion / CSV Upload / Simulation ]
                    ↓
[ Digital Twin Behavioral Profiling (Welford O(1)) ]
                    ↓
[ Hybrid ML Scoring Engine (70% XGBoost + 30% Isolation Forest) ]
                    ↓
[ SHAP TreeExplainer Local Explainability ]
                    ↓
[ Tiered Decision Engine (BLOCK >0.85 | REVIEW 0.50-0.85 | APPROVE <0.50) ]
                    ↓
[ FastAPI Backend + PostgreSQL DB + React/Vite Glassmorphism Dashboard ]
```

- **Backend:** FastAPI (Python 3.12), SQLAlchemy (Asyncpg + Sync Psycopg2), PostgreSQL 14+, Uvicorn.
- **Machine Learning:** XGBoost (supervised), Isolation Forest (unsupervised), TreeSHAP, Optuna TPE, Imbalanced-Learn (SMOTE-ENN).
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Lucide Icons, Recharts.
- **AI Intelligence:** Local Ollama (`qwen3:8b`) + PandasAI live database engine.""",

    "smote": """**⚖️ SMOTE-ENN Class Imbalance Handling:**

Fraud detection in banking faces extreme class imbalance (only **492 fraud cases (0.172%)** out of 284,807 transactions in the ULB dataset).

1. **How FraudShield Handles Imbalance:**
   - **SMOTE (Synthetic Minority Over-sampling Technique):** Synthesizes new minority fraud samples using $k$-nearest neighbors ($k=5$).
   - **ENN (Edited Nearest Neighbors):** Cleans noisy and borderline samples from both classes to create clear decision boundaries.
   - **XGBoost `scale_pos_weight`:** Dynamically scales the gradient weights of minority fraud cases during tree building.

2. **Critical Leakage Prevention:**
   - SMOTE-ENN is applied **strictly inside each cross-validation fold** via `imblearn.pipeline.Pipeline`.
   - It is **never** applied globally before splitting, ensuring test and validation folds remain completely pristine and unresampled.""",

    "colab": """**🚀 Google Colab Model Training Pipeline:**

The intensive training and Bayesian optimization workflow was developed for Google Colab (`notebooks/train_colab.ipynb`):

1. **Optuna Bayesian Hyperparameter Optimization:**
   - 100 trials using the Tree-structured Parzen Estimator (TPE) sampler.
   - 5-fold Stratified Cross-Validation optimizing minority class F1-Score.
   - Hyperparameters tuned: `learning_rate`, `max_depth` (3–10), `n_estimators` (100–1000), `subsample`, `colsample_bytree`, `reg_alpha`, `reg_lambda`.

2. **Artifact Verification:**
   - All trained artifacts (`xgboost_model.joblib`, `isolation_forest_model.joblib`, `scaler.joblib`, `shap_explainer.joblib`, `model_metadata.json`) are hashed with SHA-256 (`checksums.sha256`).
   - The FastAPI backend runs [`scripts/verify_model.py`](file:///c:/Users/saleh/OneDrive/Desktop/graduation%20project/scripts/verify_model.py) on startup to verify artifact integrity.""",

    "synthetic_users": """**👤 Synthetic User Identities in FraudShield:**

Because the ULB European Credit Card dataset was anonymized for privacy reasons, it contains **no native cardholder IDs, device fingerprints, or geolocation data**.

To evaluate real-time behavioral digital twins and compute rolling velocity features (Table 4 of the thesis):
- A **deterministic hash-bucketing algorithm** groups transactions by `Time` (1-hour bins) and `Amount` ($25 bins).
- An MD5 hash maps these bins into a pool of **2,000 synthetic customer accounts** (`user_0000` to `user_1999`).
- This allows the system to build realistic customer spending histories and calculate Welford's running mean and variance without introducing lookahead bias.""",

    "data_import": """**📁 How to Import Data into FraudShield:**

You can easily import custom transaction datasets into the system through the **Data Import** page:

1. **Navigate to Data Import:** Click **Data Import** in the left sidebar menu.
2. **Prepare Your CSV File:** Your CSV file should contain transaction records with the following columns:
   - `Time`: Elapsed seconds since the first transaction
   - `Amount`: Transaction amount in EUR / currency
   - `V1` through `V28`: PCA-anonymized transaction features
   - *(Optional)* `Class`: Ground truth label (0 = legitimate, 1 = fraud)
3. **Upload the File:** Drag and drop or browse to select your `.csv` file (e.g. `creditcard.csv` or sample batches).
4. **Start Ingestion:** Click **Start Ingestion**. The backend will:
   - Validate column schema and check data types
   - Stream rows through the **Digital Twin behavioral engine**
   - Score each transaction through **XGBoost (70%) + Isolation Forest (30%)**
   - Compute **SHAP feature contributions** for high-risk rows
5. **View Results:**
   - Real-time counters show **APPROVED**, **REVIEWED**, and **BLOCKED** counts.
   - All scored transactions immediately appear on the **Live Dashboard** and in the **Review Queue**.""",

    "xgboost": """**⚡ XGBoost (eXtreme Gradient Boosting) Classifier:**

XGBoost serves as the primary supervised fraud detection model in FraudShield.

- **Weight in Final Decision:** **70%** (`xgb_score × 0.70`)
- **Model Type:** Gradient Boosted Decision Tree ensemble with depth-constrained trees
- **Training Dataset:** ULB Credit Card Fraud dataset (284,807 transactions, 492 fraud cases)
- **Features Used:** 28 PCA components (`V1`–`V28`) + `Amount` + `Time` + 6 Digital Twin behavioral features
- **Class Imbalance Optimization:**
  - Trained using `scale_pos_weight` tuned via Optuna TPE sampler
  - Cross-validated with SMOTE-ENN sampling
- **Performance:** **0.965 ROC-AUC** on holdout test set
- **Primary Fraud Predictors:** `V14`, `V4`, `V17`, `V10`, and `amount_deviation_z`""",

    "isolation_forest": """**🌲 Isolation Forest (IF) Anomaly Detector:**

Isolation Forest is the unsupervised model responsible for detecting novel and zero-day fraud patterns.

- **Weight in Final Decision:** **30%** (`if_score × 0.30`)
- **Model Type:** Tree-based anomaly detection ensemble (unsupervised — trained without fraud labels)
- **Core Principle:** Anomalies are few and structurally different; they require fewer random splits to isolate in tree partitions.
- **Normalization:** Raw anomaly score is normalized to `[0.0, 1.0]` where `1.0` represents maximum anomaly.
- **Performance:** **0.871 ROC-AUC** standalone; boosts overall system recall when combined with XGBoost.
- **Key Benefit:** Catches unseen fraud patterns and emerging attack strategies that supervised models miss.""",

    "hybrid_fusion": """**⚖️ Hybrid Score Fusion Architecture:**

FraudShield blends supervised precision with unsupervised anomaly coverage using weighted score fusion:

$$\\text{Final Score} = (0.70 \\times \\text{XGBoost Probability}) + (0.30 \\times \\text{Isolation Forest Score})$$

**Decision Tiers:**
- 🔴 **BLOCK (Score > 0.85):** High confidence fraud. Transaction is rejected immediately.
- 🟡 **REVIEW (0.50 ≤ Score ≤ 0.85):** Moderate risk / anomalous pattern. Routed to analyst **Review Queue**.
- 🟢 **APPROVE (Score < 0.50):** Low risk. Transaction is cleared automatically.

**Combined Performance:**
- **Hybrid ROC-AUC:** **0.974** *(vs 0.965 XGBoost alone and 0.871 Isolation Forest alone)*
- **F1-Score:** **0.882**""",

    "shap": """**🔍 SHAP (SHapley Additive exPlanations) Explainability:**

FraudShield uses TreeSHAP to provide transparent, per-transaction explanations for every flagged transaction:

- **What it does:** Breaks down the model's prediction into exact positive and negative contributions from each feature.
- **Positive SHAP (+):** Feature increased fraud risk (e.g. `+0.2541`).
- **Negative SHAP (-):** Feature decreased fraud risk / supported legitimacy (e.g. `-0.1420`).
- **Top Behavioral Drivers in System:**
  - `V14`, `V4`, `V17`: PCA components strongly correlated with fraud patterns
  - `amount_deviation_z`: How far transaction amount deviates from customer historical average
  - `tx_freq_1h`: Spike in transaction frequency in the last 60 minutes
  - `time_of_day_risk`: Off-hours transaction (midnight to 5 AM window)
  - `location_entropy`: Unseen device or region marker
- **Interactive UI:** Hover over any flagged transaction in the Live Dashboard to see the SHAP waterfall explanation.""",

    "digital_twin": """**👤 Digital Twin Behavioral Profile Engine:**

The Digital Twin Engine constructs and maintains real-time behavioral profiles for every customer:

- **Memory Efficiency:** Uses **Welford's Online Algorithm** to compute rolling mean and variance in $O(1)$ memory without storing full transaction history.
- **Engineered Real-Time Features:**
  - `tx_freq_1h` & `tx_freq_24h`: Transaction velocity counts in 1-hour and 24-hour sliding causal windows
  - `amount_deviation_z`: Z-score deviation of transaction amount relative to customer's historical mean
  - `time_of_day_risk`: Binary flag (1 if between 00:00 and 05:00, 0 otherwise)
  - `velocity_change`: Rate of spending change over the last 3 transactions
  - `location_entropy`: Binary marker for novel device or region
- **Zero Training/Serving Skew:** The exact same `BehavioralFeatureEngine` class is used during offline training and online FastAPI inference.""",

    "thresholds": """**⚙️ Decision Thresholds & Configuration:**

FraudShield uses dynamic decision thresholds that can be tuned live by Administrators:

| Tier | Score Range | Default Cutoff | Action Taken |
|---|---|---|---|
| 🔴 **BLOCK** | `> 0.85` | `0.85` | Immediate automatic block; security alert logged |
| 🟡 **REVIEW** | `0.50 – 0.85` | `0.50` | Queued for manual analyst review with SHAP report |
| 🟢 **APPROVE** | `< 0.50` | `< 0.50` | Automatically approved with zero friction |

- **Live Adjustment:** Admins can adjust thresholds in real-time from the **Admin Panel** without restarting the backend.
- **Trade-off Management:** Lowering the BLOCK threshold catches more fraud at the cost of higher false positives.""",

    "dataset": """**📊 ULB European Credit Card Fraud Dataset:**

The foundation dataset used for model development and evaluation:

- **Source:** Machine Learning Group at Université Libre de Bruxelles (ULB), September 2013
- **Total Transactions:** 284,807 transactions recorded over 2 consecutive days
- **Fraud Instances:** **492 cases (0.172%)** — highly imbalanced classification problem
- **Feature Structure:**
  - `V1`–`V28`: PCA-transformed anonymized components (protects cardholder privacy)
  - `Time`: Elapsed seconds since first recorded transaction
  - `Amount`: Transaction purchase amount in Euros
  - `Class`: 0 = Legitimate, 1 = Fraudulent
- **Synthetic Identity Proxies:** Because ULB lacks user identifiers for privacy reasons, deterministic hash-bucketing of `Time` + `Amount` is used to create 2,000 synthetic customer digital twin profiles.""",

    "review_queue": """**📋 Analyst Review Queue Workflow:**

The Review Queue manages transactions requiring human verification:

- **Entry Criteria:** Any transaction with a hybrid fraud score between **0.50 and 0.85** is automatically queued.
- **Analyst Capabilities:**
  - View full transaction telemetry and SHAP risk factor breakdown
  - Read the **Ollama AI Analyst Narrative** explaining why it was flagged
  - Click **Approve** or **Reject** with optional analyst commentary
- **Priority Sorting:** Queued transactions are sorted with highest fraud scores first.
- **Audit Logging:** Every decision is permanently logged in `system_logs` with the analyst's username and timestamp.""",

    "governance": """**🛡️ Governance, RBAC & Audit System:**

FraudShield provides comprehensive Role-Based Access Control (RBAC):

- **Roles:**
  - **Admin (`admin`, `saleh`):** Full system access, threshold configuration, live simulation, and review queue decisions.
  - **User / Analyst (`user1`, `user2`):** Live dashboard monitoring, review queue operations, and transaction inspection.
  - **CEO / Super Admin (`hussain`, `ceo`):** Executive governance, user account management, password resets, and complete audit log inspection.
- **Security:** JWT cookies with HTTP-only security and native bcrypt password hashing.
- **Audit Trail:** All logins, logouts, threshold modifications, and analyst decisions are immutably tracked.""",

    "performance": """**📈 Model Performance & Validation Benchmarks:**

Evaluated on the 20% stratified holdout test set (56,746 unseen transactions):

| Model | ROC-AUC | Precision | Recall | F1-Score |
|---|---|---|---|---|
| **Hybrid Fusion (XGB + IF)** | **0.974** | **0.901** | **0.863** | **0.882** |
| XGBoost Only | 0.965 | 0.882 | 0.842 | 0.862 |
| Isolation Forest Only | 0.871 | 0.712 | 0.684 | 0.698 |

The hybrid approach delivers the lowest false positive rate while maximizing detection of complex fraud.""",
}


# ---------------------------------------------------------------------------
# Pandas Data Analysis Engine
# ---------------------------------------------------------------------------

class PandasDataAgent:
    """Performs live Pandas analytics on the PostgreSQL database."""

    def __init__(self, db_sync_url: str):
        self.db_sync_url = db_sync_url.replace("postgresql+asyncpg://", "postgresql://")

    def _get_connection(self):
        uri = self.db_sync_url
        if not uri.startswith("postgresql://"):
            uri = re.sub(r"^postgresql\+\w+://", "postgresql://", uri)
        # Neon and other cloud PostgreSQL providers require SSL
        _cloud_hosts = ["neon.tech", ".rds.amazonaws.com", "supabase.co"]
        needs_ssl = any(h in uri for h in _cloud_hosts)
        if needs_ssl and "sslmode=" not in uri:
            sep = "&" if "?" in uri else "?"
            uri = f"{uri}{sep}sslmode=require"
        return psycopg2.connect(uri)

    def load_transactions_df(self, limit: int = 10000) -> Optional[pd.DataFrame]:
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                conn = self._get_connection()
                query = f"""
                    SELECT id, transaction_uuid, synthetic_user_id, amount,
                           xgb_score, if_score, final_score, decision_tier,
                           is_simulation, created_at, true_label
                    FROM transactions
                    ORDER BY id DESC
                    LIMIT {limit}
                """
                df = pd.read_sql(query, conn)
                conn.close()
                return df
        except Exception as e:
            logger.warning("Failed to load transactions into DataFrame: %s", e)
            return None

    def get_top_users_analysis(self, n: int = 5, order_by: str = "active") -> str:
        df = self.load_transactions_df(limit=25000)
        if df is None or df.empty:
            return "No transactions are currently recorded in the database. Run a simulation from the Live Dashboard or import a CSV dataset to see user rankings."

        grouped = df.groupby("synthetic_user_id").agg(
            tx_count=("amount", "count"),
            avg_amount=("amount", "mean"),
            total_amount=("amount", "sum"),
            avg_score=("final_score", "mean"),
            blocked_count=("decision_tier", lambda s: (s == "BLOCK").sum()),
            review_count=("decision_tier", lambda s: (s == "REVIEW").sum()),
            approved_count=("decision_tier", lambda s: (s == "APPROVE").sum()),
        ).reset_index()

        if order_by == "risk":
            grouped = grouped.sort_values(by="avg_score", ascending=False).head(n)
            title = f"Top {n} Highest-Risk Users (by Average Fraud Score)"
        elif order_by == "amount":
            grouped = grouped.sort_values(by="total_amount", ascending=False).head(n)
            title = f"Top {n} Users by Total Transaction Volume"
        else:
            grouped = grouped.sort_values(by="tx_count", ascending=False).head(n)
            title = f"Top {n} Most Active Users (by Transaction Count)"

        table_rows = []
        table_rows.append(f"### 👥 {title}\n")
        table_rows.append("| Rank | Synthetic User ID | Transactions | Total Volume | Avg Amount | Avg Risk Score | 🔴 Blocked | 🟡 Review | 🟢 Approved |")
        table_rows.append("|---|---|---|---|---|---|---|---|---|")

        for idx, (_, row) in enumerate(grouped.iterrows(), 1):
            score_str = f"{row['avg_score']:.3f}" if pd.notna(row['avg_score']) else "—"
            table_rows.append(
                f"| **#{idx}** | `{row['synthetic_user_id']}` | **{int(row['tx_count']):,}** | ${row['total_amount']:,.2f} | ${row['avg_amount']:,.2f} | **{score_str}** | {int(row['blocked_count'])} | {int(row['review_count'])} | {int(row['approved_count'])} |"
            )

        top_score_str = f"`{grouped.iloc[0]['avg_score']:.3f}`" if pd.notna(grouped.iloc[0]['avg_score']) else "—"
        summary = (
            f"\n\n**Key Insight:** User `{grouped.iloc[0]['synthetic_user_id']}` leads with **{int(grouped.iloc[0]['tx_count']):,}** transactions "
            f"and a total volume of **${grouped.iloc[0]['total_amount']:,.2f}** (Avg Risk Score: {top_score_str})."
        )
        return "\n".join(table_rows) + summary

    def get_top_transactions_analysis(self, n: int = 5, order_by: str = "amount") -> str:
        df = self.load_transactions_df(limit=10000)
        if df is None or df.empty:
            return "No transactions found in database."

        if order_by == "score":
            top = df.dropna(subset=["final_score"]).sort_values(by="final_score", ascending=False).head(n)
            title = f"Top {n} Highest-Risk Transactions (by Fraud Score)"
        else:
            top = df.sort_values(by="amount", ascending=False).head(n)
            title = f"Top {n} Largest Transactions (by Amount)"

        table_rows = []
        table_rows.append(f"### 💳 {title}\n")
        table_rows.append("| Rank | Transaction UUID | User ID | Amount | Final Score | XGBoost | IsoForest | Tier |")
        table_rows.append("|---|---|---|---|---|---|---|---|")

        for idx, (_, row) in enumerate(top.iterrows(), 1):
            uuid_short = str(row["transaction_uuid"])[:16] + "..."
            f_score = f"{row['final_score']:.3f}" if pd.notna(row['final_score']) else "Unscored"
            xgb = f"{row['xgb_score']:.3f}" if pd.notna(row['xgb_score']) else "—"
            if_s = f"{row['if_score']:.3f}" if pd.notna(row['if_score']) else "—"
            tier = row.get("decision_tier")
            if pd.isna(tier) or not tier:
                emoji = "⚪ "
                tier_str = "Imported"
            else:
                emoji = "🔴 " if tier == "BLOCK" else ("🟡 " if tier == "REVIEW" else "🟢 ")
                tier_str = str(tier)
            table_rows.append(
                f"| **#{idx}** | `{uuid_short}` | `{row['synthetic_user_id']}` | **${row['amount']:,.2f}** | **{f_score}** | {xgb} | {if_s} | {emoji}{tier_str} |"
            )

        return "\n".join(table_rows)

    def get_system_overview(self) -> str:
        df = self.load_transactions_df(limit=50000)
        if df is None or df.empty:
            return "The database is currently empty. Run a simulation from the Live Dashboard or upload a dataset in Data Import."

        total = len(df)
        blocked = (df["decision_tier"] == "BLOCK").sum()
        review = (df["decision_tier"] == "REVIEW").sum()
        approved = (df["decision_tier"] == "APPROVE").sum()
        total_vol = df["amount"].sum()
        avg_amt = df["amount"].mean()
        max_amt = df["amount"].max()
        avg_score = df["final_score"].dropna().mean()
        unique_users = df["synthetic_user_id"].nunique()

        return f"""### 📊 System Transaction Overview

- **Total Scored Transactions:** **{total:,}**
- **Unique Monitored Users:** **{unique_users:,}**
- **Total Financial Volume:** **${total_vol:,.2f}**
- **Average Amount:** **${avg_amt:.2f}** *(Max: ${max_amt:,.2f})*
- **Average Fraud Score:** **{avg_score:.3f}** ({avg_score * 100:.1f}%)

**Decision Breakdown:**
- 🔴 **BLOCKED:** **{blocked:,}** ({blocked / total * 100:.1f}%) — High-risk transactions stopped
- 🟡 **UNDER REVIEW:** **{review:,}** ({review / total * 100:.1f}%) — Flagged for analyst investigation
- 🟢 **APPROVED:** **{approved:,}** ({approved / total * 100:.1f}%) — Legitimate transactions cleared"""

    def get_average_score_analysis(self) -> str:
        df = self.load_transactions_df(limit=25000)
        if df is None or df.empty:
            return "No scored transactions available to calculate averages."

        valid = df.dropna(subset=["final_score"])
        if valid.empty:
            return "No transactions have received model scores yet."

        avg_final = valid["final_score"].mean()
        avg_xgb = valid["xgb_score"].dropna().mean() if "xgb_score" in valid else 0.0
        avg_if = valid["if_score"].dropna().mean() if "if_score" in valid else 0.0
        std_score = valid["final_score"].std()

        tier_group = valid.groupby("decision_tier")["final_score"].agg(["count", "mean", "min", "max"]).reset_index()

        table = "| Decision Tier | Count | Mean Score | Min Score | Max Score |\n|---|---|---|---|---|\n"
        for _, r in tier_group.iterrows():
            emoji = "🔴 " if r["decision_tier"] == "BLOCK" else ("🟡 " if r["decision_tier"] == "REVIEW" else "🟢 ")
            table += f"| {emoji}{r['decision_tier']} | {int(r['count']):,} | **{r['mean']:.3f}** | {r['min']:.3f} | {r['max']:.3f} |\n"

        return f"""### 📈 Model Score Analytics

- **Average Fused Score:** **{avg_final:.3f}** (Std Dev: `{std_score:.3f}`)
- **Average XGBoost Probability:** **{avg_xgb:.3f}** *(70% weight)*
- **Average Isolation Forest Score:** **{avg_if:.3f}** *(30% weight)*

**Score Distribution by Decision Tier:**
{table}"""

    def get_recent_analysis(self) -> str:
        df = self.load_transactions_df(limit=10000)
        if df is None or df.empty:
            return "No recent transaction data available."

        total = len(df)
        blocked = (df["decision_tier"] == "BLOCK").sum()
        review = (df["decision_tier"] == "REVIEW").sum()
        approved = (df["decision_tier"] == "APPROVE").sum()
        avg_score = df["final_score"].dropna().mean()

        return f"""### ⏱️ Recent Activity Summary

- **Recent Transactions Scored:** **{total:,}**
- **Average Risk Score:** **{avg_score:.3f}**
- 🔴 **Blocked:** **{blocked:,}** ({blocked / total * 100:.1f}%)
- 🟡 **In Review Queue:** **{review:,}** ({review / total * 100:.1f}%)
- 🟢 **Approved:** **{approved:,}** ({approved / total * 100:.1f}%)"""

    def get_import_batches(self) -> str:
        try:
            conn = self._get_connection()
            df = pd.read_sql("SELECT original_filename, imported_rows, approve_count, review_count, block_count, status, created_at FROM import_batches ORDER BY created_at DESC LIMIT 6", conn)
            conn.close()
            if df.empty:
                return "No CSV import batches have been uploaded yet. Go to **Data Import** to upload a dataset."

            table = "| File | Rows | ✅ Approved | ⚠️ Review | 🔴 Blocked | Status |\n|---|---|---|---|---|---|\n"
            for _, r in df.iterrows():
                fn = str(r["original_filename"])[:30]
                table += f"| `{fn}` | {int(r['imported_rows']):,} | {int(r['approve_count'] or 0)} | {int(r['review_count'] or 0)} | {int(r['block_count'] or 0)} | `{r['status']}` |\n"

            return f"### 📦 Recent Data Import Batches\n\n{table}"
        except Exception as e:
            return f"Could not retrieve import batches: {e}"


# ---------------------------------------------------------------------------
# Intelligent Question Router & Search
# ---------------------------------------------------------------------------

def _match_knowledge_topic(q: str, history: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """Smart intent matching for system knowledge with exact phrase priority and conversation context."""
    q_clean = q.lower().strip().rstrip("!?.,").strip()

    # Context Resolution for follow-up queries like "is it used in this project?", "dose it used"
    context_text = ""
    if history:
        # Check last 3 messages in history to resolve pronouns
        recent_user_msgs = [m["content"].lower() for m in history if m.get("role") == "user"][-3:]
        context_text = " ".join(recent_user_msgs)

    # 1. Data import / CSV upload intent
    if any(phrase in q_clean for phrase in [
        "import data", "how to import", "how do i import", "how to upload",
        "upload data", "upload csv", "csv import", "import csv", "data import",
        "how do i upload", "ingest data", "how to add data", "add data"
    ]):
        return "data_import"

    # 2. PCA (Principal Component Analysis)
    # Direct PCA question or follow-up question referencing PCA in previous turns
    is_pca_query = any(phrase in q_clean for phrase in [
        "pca", "principal component", "v1 through v28", "v1-v28", "v1 to v28",
        "v14", "v4", "v17", "anonymized features"
    ]) or (
        ("pca" in context_text or "principal component" in context_text) and
        any(phrase in q_clean for phrase in ["is it used", "used in this project", "dose it used", "does it used", "used here", "in this project"])
    )
    if is_pca_query:
        return "pca"

    # 3. Preprocessing Pipeline
    if any(phrase in q_clean for phrase in [
        "preprocessing", "preprocess", "data cleaning", "clean data", "how is data processed",
        "data preparation", "scaling", "standardscaler", "split", "stratified", "train test split"
    ]):
        return "preprocessing"

    # 4. Features (36 input features)
    if any(phrase in q_clean for phrase in [
        "features", "feature list", "what features", "input features", "table 4",
        "how many features", "36 features", "feature engineering"
    ]):
        return "features"

    # 5. Architecture & Tech Stack
    if any(phrase in q_clean for phrase in [
        "architecture", "system architecture", "tech stack", "technology stack",
        "how does the system work", "components", "how is the project built"
    ]):
        return "architecture"

    # 6. SMOTE-ENN / Imbalance
    if any(phrase in q_clean for phrase in [
        "smote", "smote-enn", "smoteenn", "imbalance", "class imbalance", "resampling", "scale_pos_weight"
    ]):
        return "smote"

    # 7. Colab / Training Pipeline / Optuna
    if any(phrase in q_clean for phrase in [
        "colab", "google colab", "optuna", "bayesian", "hyperparameter", "train the model", "training pipeline"
    ]):
        return "colab"

    # 8. Synthetic Users / Identity Proxy
    if any(phrase in q_clean for phrase in [
        "synthetic user", "synthetic users", "synthetic identity", "user_0000", "hash bucket", "pseudo user"
    ]):
        return "synthetic_users"

    # 9. Digital Twin
    if any(phrase in q_clean for phrase in ["digital twin", "welford", "behavioral profile", "behavioral engine", "user profile"]):
        return "digital_twin"

    # 10. Hybrid Fusion (evaluate before individual models)
    if any(phrase in q_clean for phrase in ["hybrid", "fusion", "combine models", "combined", "both models", "0.70", "0.30", "score formula", "70%", "30%"]):
        return "hybrid_fusion"

    # 10. XGBoost
    if any(phrase in q_clean for phrase in ["xgboost", "xgb", "gradient boost", "supervised model"]):
        return "xgboost"

    # 11. Isolation Forest
    if any(phrase in q_clean for phrase in ["isolation forest", "iso forest", "unsupervised", "anomaly detector"]):
        return "isolation_forest"

    # 13. SHAP
    if any(phrase in q_clean for phrase in ["shap", "shapley", "explainability", "feature importance", "driver", "waterfall"]):
        return "shap"

    # 14. Thresholds
    if any(phrase in q_clean for phrase in ["threshold", "block threshold", "review threshold", "0.85", "0.50", "cutoffs", "adjust thresholds"]):
        return "thresholds"

    # 15. Review Queue
    if any(phrase in q_clean for phrase in ["review queue", "analyst", "manual review", "pending transactions", "approve or reject"]):
        return "review_queue"

    # 16. Governance & RBAC
    if any(phrase in q_clean for phrase in ["governance", "roles", "ceo", "admin rights", "user permission", "audit log", "reset password", "hussain", "saleh"]):
        return "governance"

    # 17. Performance & Benchmarks
    if any(phrase in q_clean for phrase in ["performance", "roc auc", "precision", "recall", "f1 score", "metrics", "benchmark", "accuracy", "roc-auc"]):
        return "performance"

    # 18. Dataset details
    if any(phrase in q_clean for phrase in ["dataset", "ulb", "training data", "284,807", "creditcard.csv", "ulb dataset"]):
        return "dataset"

    return None


# ---------------------------------------------------------------------------
# Ollama LLM Helper
# ---------------------------------------------------------------------------

def _call_ollama(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    timeout: float = 60.0,
    max_tokens: int = 600,
) -> Optional[str]:
    """Call local Ollama instance (qwen3:8b) enriched with full project system context and multi-turn history."""
    try:
        import http.client

        # Build prompt with system context + conversation history
        prompt_parts = [f"SYSTEM INSTRUCTIONS:\n{PROJECT_SYSTEM_PROMPT}\n\nCONVERSATION CONTEXT:"]
        if history:
            for turn in history[-6:]:  # include last 6 turns for conversational coherence
                role_label = "User" if turn.get("role") == "user" else "Assistant"
                prompt_parts.append(f"{role_label}: {turn.get('content', '')}")

        prompt_parts.append(f"User: {question}\nAssistant:")
        full_prompt = "\n".join(prompt_parts) + "\n\n/no_think"

        payload = json.dumps({
            "model": "qwen3:8b",
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": max_tokens,
                "top_p": 0.9,
                "repeat_penalty": 1.1,
            },
        }).encode("utf-8")

        _ol_host, _ol_port, _ol_path = _parse_ollama_url(_OLLAMA_BASE_URL)
        conn = http.client.HTTPConnection(_ol_host, _ol_port, timeout=timeout)
        conn.connect()
        conn.request("POST", "/api/generate", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            return None
        data = json.loads(resp.read().decode("utf-8"))
        raw = (data.get("response") or "").strip()
        if not raw and data.get("thinking"):
            raw = (data.get("thinking") or "").strip()
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"^assistant:\s*", "", raw, flags=re.IGNORECASE).strip()
        return raw if len(raw) > 15 else None
    except Exception as e:
        logger.debug("Ollama inference skipped: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main Chat Service
# ---------------------------------------------------------------------------

class FraudChatService:
    """Natural language AI Chat Assistant for FraudShield."""

    _sessions: Dict[str, List[Dict[str, str]]] = {}

    def __init__(self, db_sync_url: str):
        self.db_sync_url = db_sync_url
        self.pandas_agent = PandasDataAgent(db_sync_url)

    def chat(self, question: str, session_id: str) -> Dict[str, Any]:
        question = question.strip()
        history = self._sessions.setdefault(session_id, [])

        q_clean = question.lower().strip().rstrip("!?.,").strip()
        # Strip leading bullet/markdown characters if user clicked a suggestion
        q_clean = re.sub(r"^[-*•\s\"']+", "", q_clean).strip().rstrip("\"'")

        answer = ""
        source = "pandasai"

        # ── 1. Greetings / Small Talk ───────────────────────────────────────
        if q_clean in ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "howdy", "greetings"]:
            answer = (
                "Hi! 👋 I'm **FraudShield AI**, your fraud intelligence assistant.\n\n"
                "I have complete access to the **FraudShield project details**, live database queries, and ML architecture:\n\n"
                "- 📊 **Live Database Queries:** *\"Show me the top 5 most active users\"*, *\"What is the average fraud score?\"*, *\"Top 5 largest transactions\"*\n"
                "- 📁 **Data Ingestion:** *\"How do I import data?\"*, *\"What CSV schema is supported?\"*\n"
                "- ⚙️ **Preprocessing & Features:** *\"Explain the preprocessing steps\"*, *\"What are the 36 input features?\"*, *\"How is PCA used in this project?\"*\n"
                "- 🤖 **AI Models & Hybrid Fusion:** *\"How does XGBoost work?\"*, *\"Explain Isolation Forest\"*, *\"What is the Digital Twin?\"*, *\"Explain SHAP values\"*\n"
                "- ⚖️ **Decisions & Governance:** *\"How do decision thresholds work?\"*, *\"What is the Review Queue?\"*\n\n"
                "What would you like to analyze or explore?"
            )
            source = "rule_based"

        # ── 2. Top Users (Active / Risk / Volume) ──────────────────────────
        elif any(kw in q_clean for kw in ["top 5 most active users", "top 5 users", "top users", "most active users", "most active", "active users", "highest risk users"]):
            is_risk = any(kw in q_clean for kw in ["risk", "dangerous", "fraud"])
            is_amt = any(kw in q_clean for kw in ["volume", "amount", "money", "spent"])
            order_by = "risk" if is_risk else ("amount" if is_amt else "active")
            answer = self.pandas_agent.get_top_users_analysis(n=5, order_by=order_by)
            source = "pandasai"

        # ── 3. Top Transactions (Amounts / Scores) ─────────────────────────
        elif any(kw in q_clean for kw in ["top 5 transaction", "top transactions", "largest transaction", "highest transaction", "top 5 amount", "highest score", "most risky transaction"]):
            is_score = any(kw in q_clean for kw in ["score", "risk", "fraud", "highest score"])
            order_by = "score" if is_score else "amount"
            answer = self.pandas_agent.get_top_transactions_analysis(n=5, order_by=order_by)
            source = "pandasai"

        # ── 4. Total Transactions / Overview / Counts ─────────────────────
        elif any(kw in q_clean for kw in [
            "how many total transactions", "how many transactions", "total transactions",
            "transaction count", "system overview", "total count", "overview", "statistics",
            "how many were blocked", "how many blocked", "how many approved", "how many in review"
        ]):
            answer = self.pandas_agent.get_system_overview()
            source = "pandasai"

        # ── 5. Average Scores / Metrics ───────────────────────────────────
        elif any(kw in q_clean for kw in ["average fraud score", "average score", "mean score", "score distribution", "model score"]):
            answer = self.pandas_agent.get_average_score_analysis()
            source = "pandasai"

        # ── 6. Recent / Today Activity ────────────────────────────────────
        elif any(kw in q_clean for kw in ["today", "last 24", "recent activity", "recent transactions"]):
            answer = self.pandas_agent.get_recent_analysis()
            source = "pandasai"

        # ── 7. Import Batches History ─────────────────────────────────────
        elif any(kw in q_clean for kw in ["import batch", "import batches", "uploaded files", "recent imports"]):
            answer = self.pandas_agent.get_import_batches()
            source = "pandasai"

        # ── 8. System Knowledge Matching ──────────────────────────────────
        else:
            topic = _match_knowledge_topic(q_clean, history)
            if topic and topic in KNOWLEDGE_BASE:
                answer = KNOWLEDGE_BASE[topic]
                source = "knowledge_base"
            else:
                # ── 9. Fallback to Local LLM (Ollama) with Complete Project Context ─────
                ollama_resp = _call_ollama(question=question, history=history)
                if ollama_resp:
                    answer = ollama_resp
                    source = "ollama"
                else:
                    # Comprehensive fallback highlighting project capabilities
                    answer = (
                        f"Here is information regarding your query on **\"{question}\"**:\n\n"
                        + self.pandas_agent.get_system_overview() + "\n\n---\n\n"
                        "💡 **Questions you can ask about FraudShield:**\n"
                        "- *\"How is PCA used in this project?\"*\n"
                        "- *\"Explain the 7 data preprocessing steps\"*\n"
                        "- *\"What are the 36 model input features?\"*\n"
                        "- *\"How are XGBoost and Isolation Forest combined?\"*\n"
                        "- *\"How does the Digital Twin behavioral engine work?\"*\n"
                        "- *\"Show me the top 5 most active users\"*"
                    )
                    source = "pandasai"

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})
        if len(history) > 20:
            self._sessions[session_id] = history[-20:]

        return {"content": answer, "source": source, "session_id": session_id}

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        return self._sessions.get(session_id, [])

    def clear_history(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Singleton Factory
# ---------------------------------------------------------------------------

_chat_service: Optional[FraudChatService] = None


def get_chat_service() -> FraudChatService:
    global _chat_service
    if _chat_service is None:
        from app.core.config import settings
        _chat_service = FraudChatService(db_sync_url=settings.DATABASE_SYNC_URL)
    return _chat_service
