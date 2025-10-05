"""
bias_check.py
---------------
Performs a lightweight bias scan on model predictions.
This is a simplified demonstration module for lex.machine.
"""

import json
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# Mock Data & Configuration
# ---------------------------------------------------------------------
def load_mock_predictions():
    """Simulate model predictions and demographic attributes."""
    np.random.seed(42)
    data = pd.DataFrame({
        "prediction": np.random.choice([0, 1], size=100),
        "gender": np.random.choice(["male", "female"], size=100),
    })
    return data

# ---------------------------------------------------------------------
# Bias Check Logic
# ---------------------------------------------------------------------
def compute_bias_metrics(df: pd.DataFrame):
    """
    Compute a simple fairness metric: difference in positive outcome rates
    between groups.
    """
    rates = df.groupby("gender")["prediction"].mean().to_dict()
    bias_score = abs(rates.get("male", 0) - rates.get("female", 0))
    return {
        "positive_rate_male": rates.get("male"),
        "positive_rate_female": rates.get("female"),
        "bias_score": round(bias_score, 3),
    }

# ---------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------
def generate_report(metrics: dict, file_path="bias_report.json"):
    """Save the bias metrics to a JSON report."""
    with open(file_path, "w") as f:
        json.dump(metrics, f, indent=4)
    print(f"✅ Bias report generated → {file_path}")

# ---------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------
if __name__ == "__main__":
    df = load_mock_predictions()
    metrics = compute_bias_metrics(df)
    generate_report(metrics)
