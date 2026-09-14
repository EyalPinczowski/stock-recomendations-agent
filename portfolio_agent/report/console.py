"""Plain-text console renderer. Used for local dev/testing (--output-format
console) — the .pptx deck (report/presentation.py) is what you'd normally see.
"""

from __future__ import annotations

from portfolio_agent.models import NewStockIdeasReport, PortfolioReport, ScreenReport


def render_portfolio_report(report: PortfolioReport) -> str:
    lines = [
        f"Portfolio Report — {report.generated_at:%Y-%m-%d %H:%M} UTC",
        f"Total value: ${report.total_value:,.2f}",
        "",
        "Overall assessment:",
        f"  {report.overall_assessment}",
        "",
        "Portfolio Health:",
        f"  Sharpe ratio: {report.health.sharpe_ratio}",
        f"  Volatility (annualized): {report.health.volatility_annualized}",
        f"  Max drawdown: {report.health.max_drawdown_pct}",
        f"  Bucket allocation: {report.health.bucket_allocation}",
        f"  Sector allocation: {report.health.sector_allocation}",
    ]
    if report.health.concentration_warnings:
        lines.append("  Concentration warnings:")
        for w in report.health.concentration_warnings:
            lines.append(f"    - {w}")

    if report.rebalance_suggestions:
        lines.append("")
        lines.append("Rebalance Suggestions:")
        for s in report.rebalance_suggestions:
            lines.append(f"  [{s.kind}] {s.label}: {s.current_pct:.1%} vs target {s.target_pct:.1%} — {s.action_summary}")

    lines.append("")
    lines.append("Recommendations:")
    for r in report.holding_recommendations:
        lines.append(
            f"  {r.ticker}: {r.action.value.upper()} (conviction {r.conviction:.2f}, "
            f"R:R {r.reward_risk_ratio})"
        )
        lines.append(f"    Stop: {r.stop_take.stop_loss}  Target: {r.stop_take.take_profit}")
        lines.append(f"    {r.rationale}")
        if r.review:
            lines.append(f"    Review [{r.review.outcome}]: {r.review.notes}")

    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")

    return "\n".join(lines)


def render_screen_report(report: ScreenReport) -> str:
    lines = [f"Short-Term Screen — {report.generated_at:%Y-%m-%d %H:%M} UTC", ""]
    for c in report.candidates:
        lines.append(f"  {c.ticker}: setup score {c.setup_score:.2f} ({c.horizon_days}d horizon)")
        lines.append(f"    Entry: {c.entry_zone_low:.2f}-{c.entry_zone_high:.2f}  Stop: {c.stop_take.stop_loss}  Target: {c.stop_take.take_profit}")
        lines.append(f"    {c.rationale}")
    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def render_newstocks_report(report: NewStockIdeasReport) -> str:
    lines = [f"New Stock Ideas — {report.generated_at:%Y-%m-%d %H:%M} UTC", ""]
    lines.append("Gaps identified: " + "; ".join(report.gaps_identified) if report.gaps_identified else "Gaps identified: none")
    lines.append("")
    for s in report.suggestions:
        lines.append(f"  {s.ticker} ({s.sector}, {s.bucket.value}): score {s.composite_score:.2f}, suggested {s.suggested_allocation_pct:.1%}")
        lines.append(f"    Fit: {s.fit_reason}")
        lines.append(f"    {s.rationale}")
    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)
