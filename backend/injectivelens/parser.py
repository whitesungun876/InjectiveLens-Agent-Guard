from __future__ import annotations

import re
from typing import Any


DEFAULT_MARKET = "INJ-PERP"


def parse_trade_intent(prompt: str, parser_mode: str = "deterministic") -> dict[str, Any]:
    """Parse a narrow P0 natural-language trading request.

    This is intentionally deterministic for P0. The LLM can explain the result
    later, but it does not decide executable trade fields.
    """

    cleaned = " ".join(prompt.strip().split())
    lowered = cleaned.lower()
    warnings: list[str] = []

    market = _extract_market(cleaned)
    side = _extract_side(lowered, warnings)
    leverage = _extract_leverage(lowered, warnings)
    margin_usage_pct = _extract_margin_usage(lowered, warnings)
    order_type = "limit" if "limit" in lowered else "market"
    notional_usd = _extract_notional(cleaned, margin_usage_pct)
    slippage_bps = 35 if leverage >= 5 else 15

    if "partial" in lowered or "coverage" in lowered:
        warnings.append("Prompt references partial coverage; missing source data must remain unknown.")

    confidence = 0.94
    if warnings:
        confidence = 0.82
    if side == "long" and "long" not in lowered and "buy" not in lowered:
        confidence = min(confidence, 0.72)

    return {
        "rawPrompt": cleaned,
        "tradeIntent": {
            "market": market,
            "side": side,
            "orderType": order_type,
            "notionalUsd": notional_usd,
            "leverage": leverage,
            "marginUsagePct": margin_usage_pct,
            "slippageBps": slippage_bps,
            "timeInForce": "unspecified",
        },
        "confidence": confidence,
        "parserMode": parser_mode if parser_mode in {"deterministic", "llm_assisted"} else "fallback",
        "warnings": warnings,
    }


def _extract_market(prompt: str) -> str:
    match = re.search(r"\b([A-Z]{2,8})\s*[-/]?\s*(PERP|USDT|USD)\b", prompt)
    if not match:
        return DEFAULT_MARKET
    base, quote = match.groups()
    if quote == "PERP":
        return f"{base}-PERP"
    return f"{base}-{quote}"


def _extract_side(lowered: str, warnings: list[str]) -> str:
    if re.search(r"\b(short|sell)\b", lowered):
        return "short" if "short" in lowered else "sell"
    if re.search(r"\b(long|buy|open)\b", lowered):
        return "long" if "sell" not in lowered else "sell"
    warnings.append("Side was not explicit; defaulted to long for review.")
    return "long"


def _extract_leverage(lowered: str, warnings: list[str]) -> int:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*x\b", lowered)
    if not match:
        warnings.append("Leverage was not explicit; defaulted to 1x.")
        return 1
    return max(1, int(float(match.group(1))))


def _extract_margin_usage(lowered: str, warnings: list[str]) -> int:
    margin_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:of\s*)?(?:available\s*)?(?:margin|balance|collateral)", lowered)
    if margin_match:
        return min(100, max(0, int(float(margin_match.group(1)))))
    any_percent = re.search(r"(\d+(?:\.\d+)?)\s*%", lowered)
    if any_percent:
        return min(100, max(0, int(float(any_percent.group(1)))))
    warnings.append("Margin usage was not explicit; defaulted to 10%.")
    return 10


def _extract_notional(prompt: str, margin_usage_pct: int) -> int:
    match = re.search(r"\$?\b(\d{2,7})(?:\.\d+)?\s*(?:usd|usdt|dollars)?\b", prompt, re.IGNORECASE)
    if match:
        value = int(float(match.group(1)))
        if value not in {1, 2, 3, 5, 10, 20, 50, 60, 100}:
            return value
    return 12500 if margin_usage_pct >= 60 else 2500
