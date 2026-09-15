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
pip install -e ".[charts,dev]"
```

The LLM features (screenshot parsing, news sentiment, the review pass) run on
**Gemini** by default and need no extra package — the calls go over plain REST
using `requests`, which is already a core dependency. All you add is a key.

`charts` (matplotlib, for the deck's allocation charts) is optional and falls
back to tables; skip it on hosts where it's hard to build. The `llm` extra is
only needed if you switch the backend to Anthropic (see below). On Android, use
[`deploy/termux/install.sh`](deploy/termux/README.md) instead.

### 1. Create a Telegram bot, then run setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`,
   and follow the prompts. You'll get a bot token.
2. Run the setup command and paste the token when prompted:

   ```bash
   python -m portfolio_agent.cli setup
   ```

   It validates the token, waits for you to send your bot a message (to
   discover your chat ID automatically), optionally collects your API keys,
   writes `.env` with `0600` permissions, and sends a confirmation message to
   prove the connection works end to end.

To do it by hand instead: copy `.env.example` to `.env`, and find your chat ID
by messaging the bot then visiting
`https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` (look for
`message.chat.id`).

### 2. (Optional) Enable screenshot parsing, sentiment and the review pass

These three features need a model. Get a **free Gemini API key** at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) and add it:

```
GEMINI_API_KEY=...
```

Or let setup do it for you, without redoing the Telegram steps:

```bash
python -m portfolio_agent.cli setup --keys-only
```

That verifies the key against Google and writes the model name it picked, so a
retired model name surfaces immediately instead of as a 404 mid-report.

Without a key, `/analyze` still runs fully on the deterministic pipeline — it
just skips news sentiment and the second-opinion review pass (the narrative
assessment falls back to a short deterministic summary), and **screenshot
ingestion is unavailable**, so holdings have to come from a CSV
(`--portfolio-provider file`).

Optional knobs:

| Variable | Default | What it does |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.8-flash` | Which model to call. Setup fills this in with one your key actually has. |
| `GEMINI_THINKING_LEVEL` | unset | `MINIMAL`/`LOW`/`MEDIUM`/`HIGH` on models that support it — lower spends fewer tokens. Unset uses the model's own default. |
| `GEMINI_FALLBACK_MODELS` | unset | Models to try when the main one returns 503 "high demand". Unset means the agent asks your key what else it can call, only at the moment it needs one. |
| `LLM_PROVIDER` | `gemini` | Set to `anthropic` to use Claude instead (needs `pip install -e ".[llm]"` plus `ANTHROPIC_API_KEY`, and `ANTHROPIC_MODEL` to pick the model). |

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

**On Android/Termux**, see [`deploy/termux/README.md`](deploy/termux/README.md) —
dependencies install differently there (no manylinux wheels), and there's a
`run-bot.sh` supervisor that replaces systemd.

### First use

Scroll through your holdings and send the bot a screenshot of each screenful —
as many as it takes to cover the portfolio. They're read **together** as one
portfolio a few seconds after the last one arrives, so overlapping rows are
fine (duplicates are merged). Sending `/analyze` immediately also closes the
batch, so you don't have to wait.

Then `/status` to check it read everything — it lists the tickers it found.
If the count looks short, send the missing screenful again.

#### What it reads, and what it works out

Meitav Trade shows no share count and no cost basis, so both are derived from
what *is* on screen:

| Shown | Used for |
|---|---|
| Position value ÷ price | the share count (comes out whole for real positions) |
| Price ÷ (1 + total return %) | what you paid per share |
| TASE price ÷ 100 | agorot → shekels, since the app values positions in shekels |

Currency balances (`דולר ארה"ב`, `יתרות`) are recorded as cash rather than
holdings, and non-tradable rows like `מגן מס` are skipped with a note.

## Local testing / manual CLI use

All the bot commands are also plain CLI subcommands — `bot/dispatch.py`
calls these same functions under the hood:

```bash
python -m portfolio_agent.cli analyze --portfolio-provider file --mock --output-format console
python -m portfolio_agent.cli screen --mock --output-format pptx --output-file screen.pptx
python -m portfolio_agent.cli newstocks --portfolio-provider file --mock
python -m portfolio_agent.cli scorecard --since 30
python -m portfolio_agent.cli ingest-portfolio
python -m portfolio_agent.cli check-tickers
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

TASE holdings have to be translated into Yahoo Finance symbols. Most need no
work: Israeli funds show a security number in the app (`מספר ני"ע 1159714`),
and Yahoo lists them under exactly that number plus `.TA`, which happens
automatically. This file is for the rest — Hebrew company names with a letter
symbol on Yahoo:

```csv
identifier,yahoo_ticker,notes
טבע,TEVA.TA,Teva Pharmaceutical
```

An unmapped identifier isn't silently dropped — it shows up as a warning in
your next report so you notice and can add it. To confirm a symbol prices
before trusting it:

```bash
python -m portfolio_agent.cli check-tickers            # everything in the current snapshot
python -m portfolio_agent.cli check-tickers 1159714.TA TEVA.TA
```

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
