#!/usr/bin/env python3
"""
scripts/run_preprocessing.py
==============================
Entry point script to run the full preprocessing pipeline on creditcard.csv.
Produces data/processed/ with parquet splits + preprocessing_report.json.

Usage (from project root, after activating venv):
    python scripts/run_preprocessing.py

This must be run before:
  - scripts/verify_model.py (needs test split for smoke-validation)
  - Backend startup (needs processed data for simulation endpoint)
"""

import logging
import sys
from pathlib import Path

# Add project root to path so ml/ is importable without pip install -e .
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from ml.preprocessing import run_preprocessing_pipeline

def main() -> None:
    csv_path = PROJECT_ROOT / "data" / "raw" / "creditcard.csv"
    processed_dir = PROJECT_ROOT / "data" / "processed"
    scaler_path = processed_dir / "scaler.joblib"

    if not csv_path.exists():
        print(f"\nERROR: creditcard.csv not found at {csv_path}")
        print("Please ensure creditcard.csv is placed at data/raw/creditcard.csv")
        print("(Copy from 'graduation project/creditcard.csv')")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("FRAUD DETECTION — DATA PREPROCESSING PIPELINE")
    print(f"{'='*60}")
    print(f"  Dataset: {csv_path}")
    print(f"  Output:  {processed_dir}")
    print(f"{'='*60}\n")

    report = run_preprocessing_pipeline(
        csv_path=csv_path,
        processed_dir=processed_dir,
        scaler_path=scaler_path,
    )

    print(f"\n{'='*60}")
    print("PREPROCESSING COMPLETE")
    print(f"  Rows initial:    {report['rows_initial']}")
    print(f"  Duplicates rm:   {report['duplicates_removed']}")
    print(f"  Sanity removed:  {report['sanity_total_removed']}")
    print(f"  Train:   {report['split']['train_rows']} rows | Fraud: {report['split']['train_fraud_pct']:.4f}%")
    print(f"  Val:     {report['split']['val_rows']} rows | Fraud: {report['split']['val_fraud_pct']:.4f}%")
    print(f"  Test:    {report['split']['test_rows']} rows | Fraud: {report['split']['test_fraud_pct']:.4f}%")
    print(f"  Scaler:  {report['scaler']['path']}")
    print(f"  Report:  {processed_dir / 'preprocessing_report.json'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
