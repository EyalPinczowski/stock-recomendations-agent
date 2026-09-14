"""Second-opinion critique pass: one batched Anthropic call per report run
questions every draft recommendation/candidate/suggestion against its own
evidence, checks for better alternatives, and (on analyze runs) writes the
portfolio-level overall_assessment narrative — all in the same response, no
extra call. Can only make the system more conservative: confirmed, revised,
or downgraded (never upgraded past what the deterministic scorer allowed).
"""

from __future__ import annotations

import json
import re

from portfolio_agent.models import Action, ReviewVerdict

REVIEW_SYSTEM_PROMPT_BASE = """You are a skeptical second opinion reviewing draft stock recommendations
produced by a deterministic scoring system. For each item you are given a ticker, its draft
action/conviction, the deterministic rationale, and the underlying signals. For each item:
1. Sanity-check the recommendation against its own stated evidence.
2. Flag anything the deterministic scorer can't see (e.g. an imminent earnings date, thin
   analyst coverage, a headline that changes the picture) if evident from what's given.
3. Note if a clearly better alternative exists among the other items given.
4. Decide a verdict: "confirmed" (ships as-is), "revised" (you'd adjust conviction/notes but not
   reverse the action), or "downgraded" (you are not convinced the action is justified).
NEVER suggest a MORE aggressive action than the draft — you may only confirm, add caveats, or
pull back.

Respond with ONLY a JSON object, no prose, no markdown fences:
{"items": [{"ticker": "...", "outcome": "confirmed"|"revised"|"downgraded", "notes": "<=2 sentences",
"alternative_ticker": "<ticker or null>"}, ...]"""

REVIEW_SYSTEM_PROMPT_WITH_ASSESSMENT = (
    REVIEW_SYSTEM_PROMPT_BASE
    + ', "overall_assessment": "<4-6 sentence synthesis of the portfolio as a whole>"}'
)
REVIEW_SYSTEM_PROMPT_ITEMS_ONLY = REVIEW_SYSTEM_PROMPT_BASE + "}"

DOWNGRADE_MAP = {
    Action.BUY: Action.HOLD,
    Action.ADD: Action.HOLD,
    Action.TRIM: Action.HOLD,
    Action.SELL: Action.TRIM,
}


def _build_item_payload(ticker: str, label: str, rationale: str, extra: dict) -> dict:
    return {"ticker": ticker, "draft": label, "rationale": rationale, **extra}


def _call_review_api(items_payload: list[dict], include_overall_assessment: bool, settings) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system = (
        REVIEW_SYSTEM_PROMPT_WITH_ASSESSMENT if include_overall_assessment else REVIEW_SYSTEM_PROMPT_ITEMS_ONLY
    )
    user_prompt = json.dumps(items_payload, default=str)
    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def _parse_review_response(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?|\n?```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def review_recommendations(recommendations, health, warnings, settings):
    if not recommendations:
        return recommendations, None

    payload = [
        _build_item_payload(
            r.ticker, r.action.value, r.rationale,
            {"conviction": r.conviction, "reward_risk_ratio": r.reward_risk_ratio},
        )
        for r in recommendations
    ]
    try:
        raw = _call_review_api(payload, include_overall_assessment=True, settings=settings)
    except Exception:  # noqa: BLE001
        return recommendations, None

    parsed = _parse_review_response(raw)
    verdicts = {item["ticker"]: item for item in parsed.get("items", [])}

    updated = []
    for r in recommendations:
        entry = verdicts.get(r.ticker)
        if not entry:
            updated.append(r)
            continue
        verdict = ReviewVerdict(
            outcome=entry.get("outcome", "confirmed"),
            notes=entry.get("notes", ""),
            alternative_ticker=entry.get("alternative_ticker"),
        )
        action = r.action
        if verdict.outcome == "downgraded":
            action = DOWNGRADE_MAP.get(r.action, r.action)
        updated.append(r.model_copy(update={"review": verdict, "action": action}))

    return updated, parsed.get("overall_assessment")


def review_candidates(candidates, warnings, settings):
    if not candidates:
        return candidates
    payload = [
        _build_item_payload(c.ticker, f"setup_score={c.setup_score:.2f}", c.rationale, {})
        for c in candidates
    ]
    try:
        raw = _call_review_api(payload, include_overall_assessment=False, settings=settings)
    except Exception:  # noqa: BLE001
        return candidates

    parsed = _parse_review_response(raw)
    verdicts = {item["ticker"]: item for item in parsed.get("items", [])}
    updated = []
    for c in candidates:
        entry = verdicts.get(c.ticker)
        if not entry:
            updated.append(c)
            continue
        verdict = ReviewVerdict(
            outcome=entry.get("outcome", "confirmed"),
            notes=entry.get("notes", ""),
            alternative_ticker=entry.get("alternative_ticker"),
        )
        updated.append(c.model_copy(update={"review": verdict}))
    return updated


def review_new_stock_suggestions(suggestions, warnings, settings):
    if not suggestions:
        return suggestions
    payload = [
        _build_item_payload(s.ticker, s.bucket.value, s.rationale, {"fit_reason": s.fit_reason})
        for s in suggestions
    ]
    try:
        raw = _call_review_api(payload, include_overall_assessment=False, settings=settings)
    except Exception:  # noqa: BLE001
        return suggestions

    parsed = _parse_review_response(raw)
    verdicts = {item["ticker"]: item for item in parsed.get("items", [])}
    updated = []
    for s in suggestions:
        entry = verdicts.get(s.ticker)
        if not entry:
            updated.append(s)
            continue
        verdict = ReviewVerdict(
            outcome=entry.get("outcome", "confirmed"),
            notes=entry.get("notes", ""),
            alternative_ticker=entry.get("alternative_ticker"),
        )
        updated.append(s.model_copy(update={"review": verdict}))
    return updated
