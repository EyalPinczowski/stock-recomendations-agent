# Portfolio Agent

An on-demand portfolio analysis agent. You message a Telegram bot; it analyzes
your holdings (technical indicators, analyst recommendations, news sentiment,
portfolio-level risk/rebalancing), reviews its own draft calls with a second
LLM pass, and sends you back a PowerPoint deck with recommendations and
explanations. Recommendations only — it never places trades. Nothing runs on
a schedule; everything happens when you ask.

## What it can do

- **`/analyze`** — full holdings analysis: buy/add/hold/trim/sell per position
  with stop-loss/take-profit levels, portfolio health (Sharpe ratio,
  volatility, max drawdown), bucket (conservative/aggressive) and sector
  rebalancing suggestions, and an overall narrative assessment.
- **`/screen`** — scans a broad universe of stocks for short-term (days-to-
  weeks) technical setups, independent of what you currently hold.
- **`/newstocks`** — identifies gaps in your portfolio (underweight bucket or
  sector) and suggests specific new stocks that would fill them.
- **`/scorecard`** — checks past recommendations against what the price
  actually did since, for an honest accuracy check over time.
- **`/status`**, **`/riskprofile`**, **`/help`** — quick status/config checks.
- **Send a photo** of your portfolio (from your brokerage app) any time to
  update your holdings — no manual data entry required.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### 1. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`,
   follow the prompts. You'll get a bot token.
2. Message your new bot once (anything), then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser to find
   your chat ID (`message.chat.id` in the JSON).
3. Fill in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```

### 2. (Optional) Enable sentiment analysis and the review pass

Without an Anthropic key, `/analyze` still runs fully — it just skips news
sentiment and the second-opinion review pass (including the narrative
assessment, which falls back to a short deterministic summary).

```
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-4-5
```

### 3. (Optional) Better news coverage

Without `NEWS_API_KEY`, sentiment uses the free GDELT source. With a
[NewsAPI.org](https://newsapi.org) key, it's used instead (generally better
relevance):

```
NEWS_API_KEY=...
```

## Running

**Primary way to run this** — the persistent bot process:

```bash
python -m portfolio_agent.cli bot
```

It long-polls Telegram and replies to your messages within seconds. Keep it
running continuously via systemd (recommended) — copy
`deploy/portfolio-agent-bot.service`, edit the paths, then:

```bash
sudo cp deploy/portfolio-agent-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now portfolio-agent-bot
journalctl -u portfolio-agent-bot -f   # tail logs
```

Or just run it in a terminal / `tmux` session if you'd rather not use
systemd. `Restart=on-failure` in the unit file means a crash restarts the
process automatically and it picks up where it left off (no messages lost).

### First use

Send a screenshot of your portfolio to the bot, then send `/analyze`. If you
haven't sent a screenshot yet, `/analyze` will tell you to.

## Local testing / manual CLI use

All the bot commands are also plain CLI subcommands — `bot/dispatch.py`
calls these same functions under the hood:

```bash
python -m portfolio_agent.cli analyze --portfolio-provider file --mock --output-format console
python -m portfolio_agent.cli screen --mock --output-format pptx --output-file screen.pptx
python -m portfolio_agent.cli newstocks --portfolio-provider file --mock
python -m portfolio_agent.cli scorecard --since 30
python -m portfolio_agent.cli ingest-portfolio
```

`--mock` swaps in fixture-backed/synthetic data providers so everything runs
fully offline — no API keys, no network — useful for development and CI.
`--portfolio-provider file` uses `examples/portfolio.csv` instead of the
Telegram-screenshot snapshot.

Run the test suite:

```bash
pytest
```

## Configuration

### `risk_profile.yaml`

The single dial that shapes every recommendation:

```yaml
name: balanced
target_conservative_pct: 0.6   # target split between conservative...
target_aggressive_pct: 0.4     # ...and aggressive holdings
min_reward_risk_ratio: 1.5     # BUY/ADD calls below this reward:risk get downgraded to HOLD
max_position_pct: 0.15         # cap on any single position as % of portfolio
max_sector_pct: 0.25           # flag a sector once it exceeds this % of portfolio
rebalance_drift_threshold_pct: 0.05   # how far off-target before a rebalance is suggested
```

Ask `/riskprofile` any time to see the current values. Send the file itself
via `/help` for a reminder of what each field does, or just edit
`risk_profile.yaml` directly and restart the bot.

### `data/tase_ticker_map.csv`

If your portfolio includes TASE (Israeli exchange) stocks, screenshot
parsing needs to translate what your broker's app shows (a Hebrew company
name or TASE security number) into a Yahoo Finance-compatible ticker (a
`.TA` suffix) — OCR/vision alone can't do this reliably. Add rows as needed:

```csv
identifier,yahoo_ticker,notes
טבע,TEVA.TA,Teva Pharmaceutical
```

An unmapped identifier isn't silently dropped — it shows up as a warning in
your next report so you notice and can add it.

### `data/sp500_constituents.csv`

The bundled universe used by `/screen` and `/newstocks`. It's a curated
subset, not the full index — edit it (or ask me to regenerate it) if you
want broader/different coverage.

## Architecture notes

- **Providers** (`providers/`) are the only code that talks to the outside
  world (yfinance, news APIs, Telegram). `analysis/` and `optimization/` are
  pure functions over data models — fully unit-testable without network
  access.
- **Stop-loss/take-profit levels** are suggestions for you to set as actual
  orders on your broker — this tool never monitors prices or places trades.
- **The review pass** (`review/reviewer.py`) is one batched LLM call per
  request that questions the deterministic scorer's calls and can only make
  them *more* conservative (confirm, revise, or downgrade — never upgrade).
- **Sentiment and review calls are batched** across everything in one
  request, not per-ticker, so cost doesn't scale with portfolio/universe
  size.

## Known limitation

No direct Meitav Trade integration — no public self-serve API was found;
this would require contacting Meitav's trading/algo desk directly. The
`PortfolioProvider` interface (`providers/base.py`) means a real broker
integration can be added later without touching analysis, optimization, or
reporting code.
