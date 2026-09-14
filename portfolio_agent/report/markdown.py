"""Markdown renderer — kept for local dev/testing (--output-file report.md)."""

from __future__ import annotations

from portfolio_agent.report import console as console_mod


def render(report, report_kind: str) -> str:
    # Console rendering is already plain enough to double as a simple markdown-ish
    # text dump; wrap it in a code fence so it's still readable as a .md file.
    renderer = {
        "analyze": console_mod.render_portfolio_report,
        "screen": console_mod.render_screen_report,
        "newstocks": console_mod.render_newstocks_report,
    }[report_kind]
    return "```\n" + renderer(report) + "\n```\n"
