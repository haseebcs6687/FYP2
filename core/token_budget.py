"""
=============================================================================
EduGen - Token Budget & Provider Rate-Limit Manager (Phase 4C)
=============================================================================
Tracks daily token consumption per model and enforces budget caps:
  - Primary model cap: EDUGEN_DAILY_TOKEN_BUDGET (default 160,000)
  - Fallback model cap: EDUGEN_FALLBACK_DAILY_TOKEN_BUDGET (default 160,000)
  - Switching logic: primary -> fallback -> pool-only (live generation disabled)
  - Intercepts 429 TPD or Retry-After > 60s, marking the model exhausted immediately
=============================================================================
"""

import os
import re
from datetime import datetime, timezone
from core.agent_log import add_log
from core.db import get_db

DEFAULT_PRIMARY_BUDGET = 160000
DEFAULT_FALLBACK_BUDGET = 160000

# In-memory registry of models marked exhausted for the current calendar day
_EXHAUSTED_MODELS_TODAY = set()
_UNSUPPORTED_REASONING_MODELS = set()


def get_budget_for_model(model, is_fallback=False):
    """Retrieve daily token limit for a specific model from environment."""
    if is_fallback:
        env_val = os.environ.get("EDUGEN_FALLBACK_DAILY_TOKEN_BUDGET")
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                pass
        return DEFAULT_FALLBACK_BUDGET

    env_val = os.environ.get("EDUGEN_DAILY_TOKEN_BUDGET")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return DEFAULT_PRIMARY_BUDGET


def get_today_token_usage(model, conn=None):
    """
    Sum all tokens used by the given model today from llm_calls table.
    """
    if not model:
        return 0

    should_close = False
    if conn is None:
        try:
            conn = get_db()
            should_close = True
        except Exception:
            return 0

    try:
        # Date match using local/UTC date string
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(llm_calls)").fetchall()}

        if "total_tokens" in cols:
            row = conn.execute(
                """SELECT SUM(COALESCE(total_tokens, prompt_tokens + completion_tokens, 0)) as total
                   FROM llm_calls
                   WHERE model = ? AND date(created_at) = date(?)""",
                (model, today_date),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT SUM(COALESCE(prompt_tokens + completion_tokens, 0)) as total
                   FROM llm_calls
                   WHERE model = ? AND date(created_at) = date(?)""",
                (model, today_date),
            ).fetchone()

        total = row["total"] if row and row["total"] is not None else 0
        return int(total)
    except Exception as exc:
        add_log("TokenBudget", f"get_today_token_usage query failed for '{model}': {exc}", "warning")
        return 0
    finally:
        if should_close and conn:
            try:
                conn.close()
            except Exception:
                pass


def mark_model_exhausted(model, reason="budget_exceeded"):
    """Mark a model exhausted for the rest of today."""
    if model:
        _EXHAUSTED_MODELS_TODAY.add(model)
        add_log(
            "TokenBudget",
            f"Model '{model}' marked EXHAUSTED for today ({reason}).",
            "warning",
        )


def is_model_exhausted(model, primary_model=None, fallback_model=None, conn=None):
    """Check if model is exhausted via memory flag or DB token sum."""
    if not model:
        return True

    if model in _EXHAUSTED_MODELS_TODAY:
        return True

    is_fallback = (model == fallback_model and model != primary_model)
    budget = get_budget_for_model(model, is_fallback=is_fallback)
    used = get_today_token_usage(model, conn=conn)

    if used >= budget:
        mark_model_exhausted(model, f"usage {used} >= budget {budget}")
        return True

    return False


def select_active_model(primary_model, fallback_model, conn=None):
    """
    Select active generation model:
      - primary if within budget
      - fallback if primary exhausted but fallback within budget
      - None if both exhausted
    Returns (model_name_or_None, status_str: 'primary'|'fallback'|'exhausted')
    """
    # 1. Try primary
    if not is_model_exhausted(primary_model, primary_model, fallback_model, conn=conn):
        return primary_model, "primary"

    # 2. Try fallback
    if fallback_model and fallback_model != primary_model:
        if not is_model_exhausted(fallback_model, primary_model, fallback_model, conn=conn):
            add_log(
                "TokenBudget",
                f"Primary model '{primary_model}' exhausted today. Switching to fallback '{fallback_model}'.",
                "warning",
            )
            return fallback_model, "fallback"

    # 3. Both exhausted
    add_log(
        "TokenBudget",
        "Both primary and fallback models exhausted for today. Live generation disabled.",
        "error",
    )
    return None, "exhausted"


def are_all_models_exhausted(primary_model, fallback_model, conn=None):
    """Convenience boolean check whether no generation models remain."""
    active_m, _ = select_active_model(primary_model, fallback_model, conn=conn)
    return active_m is None


def check_429_exhaustion(model, error_text_or_exc, retry_after=None):
    """
    Check if a 429 response indicates tokens-per-day or Retry-After > 60s.
    If so, immediately marks the model exhausted today and returns True.
    """
    err_text = str(error_text_or_exc or "").lower()

    # Look for tokens-per-day
    is_tpd = (
        "tokens-per-day" in err_text
        or "tokens per day" in err_text
        or "tpd" in err_text
    )

    # Parse retry_after if not provided directly
    if retry_after is None:
        m = re.search(r"try again in (\d+(?:\.\d+)?)s", err_text)
        if m:
            try:
                retry_after = float(m.group(1))
            except (ValueError, TypeError):
                pass
        m_min = re.search(r"try again in (\d+)m([\d\.]+)s", err_text)
        if m_min:
            try:
                mins = float(m_min.group(1))
                secs = float(m_min.group(2))
                retry_after = mins * 60.0 + secs
            except (ValueError, TypeError):
                pass

    is_long_retry = (retry_after is not None and float(retry_after) > 60.0)

    if is_tpd or is_long_retry:
        reason = "tokens-per-day cap" if is_tpd else f"Retry-After {retry_after}s > 60s"
        mark_model_exhausted(model, reason)
        return True

    return False


def is_reasoning_supported(model):
    """Check if reasoning_effort is supported for this model."""
    return model not in _UNSUPPORTED_REASONING_MODELS


def mark_reasoning_unsupported(model):
    """Remember that this model rejected reasoning_effort (HTTP 400)."""
    if model:
        _UNSUPPORTED_REASONING_MODELS.add(model)
        add_log(
            "TokenBudget",
            f"Model '{model}' does not support reasoning_effort; disabled for future calls.",
            "info",
        )


def reset_budget_state():
    """Reset in-memory exhaustion and reasoning state (for testing)."""
    _EXHAUSTED_MODELS_TODAY.clear()
    _UNSUPPORTED_REASONING_MODELS.clear()

