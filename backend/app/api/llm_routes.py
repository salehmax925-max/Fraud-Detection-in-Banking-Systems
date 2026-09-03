"""
backend/app/api/llm_routes.py
==============================
LLM-powered transaction explanation endpoint.

POST /api/explain
  Generates a detailed, professional 5-8 sentence fraud analyst explanation
  for why a transaction was APPROVED, REVIEWED, or BLOCKED.
  Uses Ollama qwen3:8b if available; falls back to rule-based text otherwise.

Ollama config:
  - Endpoint:    http://localhost:11434/api/generate
  - Model:       qwen3:8b
  - num_predict: 700  (supports 5-8 sentence analyst report)
  - temperature: 0.3  (stable, professional, reproducible output)
  - Timeout:     60 seconds (qwen3:8b cold start needs ~30-60s)
  - /no_think:   appended to prompt to suppress qwen3 <think> chain-of-thought
  - Fallback:    detailed rule-based explanation (always available)
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Ollama base URL — configurable via OLLAMA_BASE_URL env var
_OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def _parse_ollama_host_port(url: str) -> tuple[str, int]:
    """Parse OLLAMA_BASE_URL into (host, port)."""
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11434
    return host, port

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ShapFeatureIn(BaseModel):
    feature_name: str
    shap_value: float
    feature_value: float
    direction: str
    rank: int


class ExplainRequest(BaseModel):
    decision_tier: str
    final_score: float
    xgb_score: Optional[float] = None
    if_score: Optional[float] = None
    amount: float
    shap_features: List[ShapFeatureIn] = []
    behavioral: Dict[str, Any] = {}


class ExplainResponse(BaseModel):
    explanation: str
    source: str
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Feature label mapping
# ---------------------------------------------------------------------------

_FEATURE_LABELS: Dict[str, str] = {
    "amount_deviation_z": "unusual transaction amount (z-score deviation from customer historical mean)",
    "time_of_day_risk":   "off-hours timing (midnight to 5 AM high-risk window)",
    "location_entropy":   "new or unrecognized device/region marker",
    "velocity_change":    "sudden spike in transaction velocity",
    "tx_freq_1h":         "elevated transaction frequency in the last hour",
    "tx_freq_24h":        "elevated daily transaction count",
}


def _friendly_feature(name: str) -> str:
    if name in _FEATURE_LABELS:
        return _FEATURE_LABELS[name]
    if name.upper().startswith("V") and name[1:].isdigit():
        return f"PCA component {name} (anonymized behavioral pattern)"
    return name


# ---------------------------------------------------------------------------
# Rule-based fallback — detailed 5-8 sentence analyst narrative
# ---------------------------------------------------------------------------

def _rule_based_explanation(req: ExplainRequest) -> str:
    tier      = req.decision_tier.upper()
    score_pct = round(req.final_score * 100, 1)
    xgb_pct   = round((req.xgb_score or 0.0) * 100, 1)
    if_pct    = round((req.if_score  or 0.0) * 100, 1)
    amount    = req.amount

    risk_feats = sorted(
        [f for f in req.shap_features if f.shap_value > 0],
        key=lambda f: f.shap_value, reverse=True,
    )
    legit_feats = sorted(
        [f for f in req.shap_features if f.shap_value < 0],
        key=lambda f: f.shap_value,
    )

    if tier == "APPROVE":
        s1 = (f"This transaction of ${amount:.2f} was automatically APPROVED with a combined fraud "
              f"risk score of {score_pct}%, falling below the 50% manual review threshold.")
    elif tier == "REVIEW":
        s1 = (f"This transaction of ${amount:.2f} has been flagged for MANUAL ANALYST REVIEW, "
              f"receiving a combined fraud risk score of {score_pct}%, which places it in the "
              f"uncertain zone between the 50% review and 85% block thresholds.")
    else:
        s1 = (f"This transaction of ${amount:.2f} has been AUTOMATICALLY BLOCKED based on a "
              f"combined fraud risk score of {score_pct}%, which exceeds the 85% block threshold.")

    s2 = (f"The XGBoost supervised classifier assigned a fraud probability of {xgb_pct}%, "
          f"while the Isolation Forest anomaly detector contributed a normalized anomaly score "
          f"of {if_pct}%, combined using a 70%/30% hybrid weighting.")

    if risk_feats:
        top3 = [_friendly_feature(f.feature_name) for f in risk_feats[:3]]
        s3 = f"The primary factors driving the elevated fraud score were: {', '.join(top3)}."
    else:
        s3 = "The model did not identify strongly fraud-indicating feature signals for this transaction."

    if legit_feats:
        top2 = [_friendly_feature(f.feature_name) for f in legit_feats[:2]]
        s4 = f"Conversely, the following features reduced the estimated fraud risk: {', '.join(top2)}."
    else:
        s4 = "No significant legitimacy signals were detected to offset the risk indicators."

    b = req.behavioral
    behav_parts: List[str] = []
    if b.get("tx_freq_1h") is not None:
        freq = float(b["tx_freq_1h"])
        if freq > 2:
            behav_parts.append(f"{int(freq)} transactions in the last hour (unusually high frequency)")
        elif freq > 0:
            behav_parts.append(f"{int(freq)} prior transaction(s) in the last hour")
    if b.get("amount_deviation_z") is not None:
        z = float(b["amount_deviation_z"])
        if abs(z) >= 1.0:
            direction = "above" if z > 0 else "below"
            behav_parts.append(
                f"the transaction amount is {abs(z):.2f} standard deviations {direction} "
                f"this customer historical mean"
            )
    if b.get("time_of_day_risk") == 1:
        behav_parts.append("the transaction occurred during the midnight-to-5 AM high-risk window")
    if b.get("velocity_change") is not None:
        vc = float(b["velocity_change"])
        if abs(vc) > 0.3:
            behav_parts.append(f"a significant velocity change of {vc:.3f} was observed in recent transactions")
    if b.get("location_entropy") == 1:
        behav_parts.append("a new or previously unseen device/region marker was detected")

    if behav_parts:
        s5 = f"The Digital Twin behavioral profile further indicates that: {'; '.join(behav_parts)}."
    else:
        s5 = "No significant behavioral anomalies were recorded in the Digital Twin profile for this transaction."

    if tier == "APPROVE":
        s6 = ("Given that all risk indicators fall within acceptable thresholds and the behavioral "
              "profile shows no unusual deviations, the system approved this transaction automatically "
              "without requiring further analyst intervention.")
    elif tier == "REVIEW":
        s6 = ("Because the combined evidence is inconclusive — the model detects suspicious signals "
              "but cannot achieve the confidence level required for automatic blocking — a qualified "
              "fraud analyst should manually examine the transaction context, customer history, and "
              "feature breakdown before taking a final approve or reject decision.")
    else:
        s6 = ("The convergence of high XGBoost fraud probability, Isolation Forest anomaly detection, "
              "and multiple behavioral risk signals provides sufficient confidence to block this "
              "transaction automatically, protecting the account from potential financial loss "
              "without requiring human review.")

    return " ".join([s1, s2, s3, s4, s5, s6])


# ---------------------------------------------------------------------------
# Ollama prompt builder
# ---------------------------------------------------------------------------

def _build_ollama_prompt(req: ExplainRequest) -> str:
    """
    Build a structured, detailed prompt for qwen3:8b.
    Provides all transaction values explicitly.
    Appends /no_think to suppress qwen3 chain-of-thought output.
    """
    tier      = req.decision_tier.upper()
    score_pct = round(req.final_score * 100, 1)
    xgb_pct   = round((req.xgb_score or 0.0) * 100, 1) if req.xgb_score is not None else "N/A"
    if_pct    = round((req.if_score  or 0.0) * 100, 1) if req.if_score  is not None else "N/A"

    tier_label = {
        "APPROVE": f"AUTOMATICALLY APPROVED - score {score_pct}% (below 50% review threshold)",
        "REVIEW":  f"FLAGGED FOR MANUAL REVIEW - score {score_pct}% (between 50% and 85% thresholds)",
        "BLOCK":   f"AUTOMATICALLY BLOCKED - score {score_pct}% (above 85% block threshold)",
    }.get(tier, tier)

    risk_feats  = sorted([f for f in req.shap_features if f.shap_value > 0],
                         key=lambda f: f.shap_value, reverse=True)[:5]
    legit_feats = sorted([f for f in req.shap_features if f.shap_value < 0],
                         key=lambda f: f.shap_value)[:3]

    risk_lines = "\n".join(
        f"  {i+1}. {_friendly_feature(f.feature_name)} - SHAP +{f.shap_value:.4f} (value: {f.feature_value:.4f})"
        for i, f in enumerate(risk_feats)
    ) or "  (none significant)"

    legit_lines = "\n".join(
        f"  {i+1}. {_friendly_feature(f.feature_name)} - SHAP {f.shap_value:.4f} (value: {f.feature_value:.4f})"
        for i, f in enumerate(legit_feats)
    ) or "  (none significant)"

    b = req.behavioral
    behav_lines: List[str] = []
    if b.get("tx_freq_1h")         is not None:
        behav_lines.append(f"  - Transactions in last 1 hour: {b['tx_freq_1h']}")
    if b.get("tx_freq_24h")        is not None:
        behav_lines.append(f"  - Transactions in last 24 hours: {b['tx_freq_24h']}")
    if b.get("amount_deviation_z") is not None:
        behav_lines.append(f"  - Amount z-score vs customer history: {float(b['amount_deviation_z']):.3f}")
    if b.get("time_of_day_risk")   is not None:
        label = "YES - midnight to 5 AM window" if b["time_of_day_risk"] == 1 else "NO - normal hours"
        behav_lines.append(f"  - Off-hours high-risk flag: {label}")
    if b.get("velocity_change")    is not None:
        behav_lines.append(f"  - Transaction velocity change: {float(b['velocity_change']):.4f}")
    if b.get("location_entropy")   is not None:
        label = "YES - new/unrecognized device or region" if b["location_entropy"] == 1 else "NO - known device/region"
        behav_lines.append(f"  - New device/location marker: {label}")
    behavioral_section = "\n".join(behav_lines) if behav_lines else "  (no behavioral data available)"

    if tier == "REVIEW":
        analyst_note = ("The score is in the uncertain zone between REVIEW (50%) and BLOCK (85%) thresholds. "
                        "Explain why a human analyst should verify before taking action.")
    elif tier == "BLOCK":
        analyst_note = ("The score exceeds the BLOCK threshold (85%). "
                        "Explain why the combined evidence justifies automatic blocking.")
    else:
        analyst_note = ("The score is below the REVIEW threshold (50%). "
                        "Explain why the model considers this transaction legitimate.")

    return f"""You are a senior banking fraud analyst writing an internal fraud analysis report. Analyze the transaction data below and write a professional explanation.

TRANSACTION DATA:
Decision: {tier_label}
Amount: ${req.amount:.2f}
Combined risk score: {score_pct}%
XGBoost fraud probability: {xgb_pct}%
Isolation Forest anomaly score: {if_pct}%

FACTORS INCREASING FRAUD RISK (SHAP):
{risk_lines}

FACTORS REDUCING FRAUD RISK (SHAP):
{legit_lines}

DIGITAL TWIN BEHAVIORAL PROFILE:
{behavioral_section}

ANALYST NOTE: {analyst_note}

INSTRUCTIONS:
Write exactly 5 to 8 complete, professional sentences as a continuous analyst narrative. You MUST:
1. Start by stating the decision ({tier}) and the exact risk score ({score_pct}%).
2. Explain what the XGBoost ({xgb_pct}%) and Isolation Forest ({if_pct}%) each found.
3. Name the top SHAP features that INCREASED fraud risk and explain their impact.
4. Mention any SHAP features that reduced the risk.
5. Incorporate the Digital Twin behavioral data with specific numbers from above.
6. Conclude with a clear justification for the {tier} decision.

Use ONLY the actual values above. Do NOT invent numbers. Write in flowing professional prose. No bullet points. No headers. Start directly with the analysis.

/no_think"""


# ---------------------------------------------------------------------------
# Ollama HTTP caller (runs in thread executor to avoid blocking async loop)
# ---------------------------------------------------------------------------

async def _call_ollama(
    prompt: str,
    model: str = "qwen3:8b",
    timeout: float = 60.0,
) -> Optional[str]:
    import json
    import http.client
    import socket

    try:
        payload = json.dumps({
            "model":  model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature":    0.3,
                "num_predict":    700,
                "top_p":          0.9,
                "repeat_penalty": 1.1,
            },
        }).encode("utf-8")

        loop = asyncio.get_event_loop()

        def _blocking_call() -> Optional[str]:
            try:
                _ol_host, _ol_port = _parse_ollama_host_port(_OLLAMA_BASE_URL)
                conn = http.client.HTTPConnection(_ol_host, _ol_port, timeout=timeout)
                conn.connect()
                conn.request(
                    "POST", "/api/generate",
                    body=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp = conn.getresponse()
                if resp.status != 200:
                    logger.warning("Ollama returned HTTP %d", resp.status)
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                raw  = data.get("response", "").strip()
                # Safety net: strip any residual <think>...</think> blocks
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                return raw if raw else None
            except (ConnectionRefusedError, socket.timeout, OSError) as exc:
                logger.info("Ollama unavailable (%s) - using rule-based fallback", exc)
                return None
            except Exception as exc:
                logger.warning("Ollama call failed: %s", exc)
                return None

        return await loop.run_in_executor(None, _blocking_call)

    except Exception as exc:
        logger.warning("Ollama async wrapper failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# FastAPI endpoint
# ---------------------------------------------------------------------------

from app.core.config import settings as _settings
OLLAMA_MODEL = _settings.OLLAMA_MODEL


@router.post("/explain", response_model=ExplainResponse, tags=["Explanations"])
async def explain_transaction(req: ExplainRequest) -> ExplainResponse:
    """
    Generate a professional 5-8 sentence fraud analyst explanation.
    Tries Ollama qwen3:8b first; falls back to detailed rule-based text.
    The application NEVER fails because Ollama is unavailable.
    """
    ollama_text = await _call_ollama(
        prompt=_build_ollama_prompt(req),
        model=OLLAMA_MODEL,
        timeout=60.0,
    )

    if ollama_text and len(ollama_text.strip()) > 50:
        logger.info("Ollama explanation: %d chars", len(ollama_text))
        return ExplainResponse(explanation=ollama_text, source="ollama", model=OLLAMA_MODEL)

    logger.debug("Using detailed rule-based fallback")
    return ExplainResponse(explanation=_rule_based_explanation(req), source="rule_based", model=None)
