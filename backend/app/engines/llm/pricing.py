"""Built-in LLM price table.

Prices are USD per 1,000,000 tokens, split input (prompt) vs output
(completion). This is a static MVP table — not live pricing — intended to
give reasonable cost estimates when a caller doesn't supply ``cost_usd``
directly. Unknown models fall back to ``DEFAULT_PRICE``.
"""
from __future__ import annotations

# model name (lowercased, as sent by the caller) -> {"input": $/1M, "output": $/1M}
PRICE_TABLE: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "claude-opus-5": {"input": 15.00, "output": 75.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-5": {"input": 0.80, "output": 4.00},
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-4": {"input": 0.80, "output": 4.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.02},
    "text-embedding-3-large": {"input": 0.13, "output": 0.13},
    "llama-3-70b": {"input": 0.59, "output": 0.79},
    "llama-3-8b": {"input": 0.05, "output": 0.10},
    "mistral-large": {"input": 2.00, "output": 6.00},
}

# Fallback used for any model not present in PRICE_TABLE.
DEFAULT_PRICE: dict[str, float] = {"input": 1.00, "output": 3.00}


def get_price(model: str) -> dict[str, float]:
    """Return the {input, output} USD-per-1M-tokens price for ``model``."""
    return PRICE_TABLE.get((model or "").strip().lower(), DEFAULT_PRICE)


def estimate_cost_usd(
    model: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float:
    """Estimate USD cost from token counts using the built-in price table."""
    price = get_price(model)
    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    cost = (prompt_tokens / 1_000_000.0) * price["input"]
    cost += (completion_tokens / 1_000_000.0) * price["output"]
    return round(cost, 8)
