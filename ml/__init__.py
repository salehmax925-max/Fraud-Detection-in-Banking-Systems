"""
Banking Fraud Detection ML Package
===================================
Al-Balqa' Applied University — Faculty of Artificial Intelligence
Graduation Project 2024/2025

This package (ml/) is the single source of truth for all ML logic:
- preprocessing.py  : data cleaning, scaling, splitting, SMOTE-ENN pipeline builder
- features.py       : BehavioralFeatureEngine (identical at training time and inference time)
- train.py          : XGBoost + Isolation Forest hybrid, Optuna search, SHAP
- evaluate.py       : metrics, plots, evaluation report

Imported by:
  - notebooks/train_colab.ipynb  (on Google Colab)
  - backend/app/services/scoring.py  (local inference server)
  - scripts/verify_model.py  (local verification)
  - scripts/run_preprocessing.py  (local data preparation)
"""

__version__ = "1.0.0"
__author__ = "Graduation Project — Al-Balqa' Applied University, Faculty of AI"
