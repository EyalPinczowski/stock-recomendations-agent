# Running on Termux (Android)

Termux works, but two things differ from a normal Linux host:

1. **Dependencies.** Termux uses Bionic libc, so PyPI's manylinux wheels don't
   install. Anything with C or Rust extensions needs a Termux-native package or
   an on-device build. `install.sh` handles this.
2. **Process lifetime.** There's no systemd, and Android kills background
   processes. `run-bot.sh` mitigates this; it can't fully solve it.

The LLM features run on Gemini precisely because of (1): it's plain REST over
`requests`, so there's nothing extra to compile on-device.

A third, smaller one: Android ships no IANA time-zone database that Python can
read, which yfinance needs for every quote. `install.sh` installs the `tzdata`
package to supply it.

## Before you paste anything

Termux often mangles multi-line pastes: the terminal's bracketed-paste markers
get glued onto your command, so you see things like

```
~ $ ^[[200~pkg install git
pkg: command not found
```

The command never ran — `^[[200~` is the paste marker, not part of what you
typed. **Run the install commands one line at a time**, or turn bracketed paste
off once and restart Termux:

```bash
echo 'set enable-bracketed-paste off' >> ~/.inputrc
```

## Install

Run these individually, not as one pasted block:

```bash
pkg install git
git clone https://github.com/EyalPinczowski/stock-recomendations-agent
cd stock-recomendations-agent
git checkout claude/portfolio-revenue-agent-jqdwpx
bash deploy/termux/install.sh
```

If `pkg` itself reports "command not found" even when typed by hand, use the
`apt` it wraps: `apt update && apt install git`.

The installer pulls what it can from Termux's own repos (`numpy`, `pillow`,
`lxml` — never pip, which would try to compile them), creates a venv with
`--system-site-packages` so those stay visible, and installs `pydantic` from a
[prebuilt Android wheel index](https://github.com/Goplr/android-pydantic-core)
so its Rust core doesn't have to build on-device.

**pandas has to be compiled**, because Termux doesn't package it. The installer
handles this, but budget 10–30 minutes for that step and keep the screen on so
Android doesn't suspend the build. It needs `LDFLAGS="-lpython<version>"` and
`--no-build-isolation` — if you ever do it by hand, see
[termux-packages #25247](https://github.com/termux/termux-packages/discussions/25247).

**One dependency is optional**, because it's slow to build here and the app
degrades cleanly without it:

| Optional | Needs | Without it |
|---|---|---|
| `matplotlib` | a long C build | Deck renders allocation **tables** instead of charts. Nothing else changes. |

### Getting screenshot parsing working

Nothing to build. Screenshot parsing, news sentiment and the review pass run
on **Gemini**, which is plain REST over `requests` — already installed. All it
needs is a free key from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey):

```bash
source .venv/bin/activate
python -m portfolio_agent.cli setup --keys-only
```

That verifies the key against Google, picks a model your key actually has, and
writes both to `.env` without touching your Telegram settings.

This is deliberately *not* the Anthropic SDK: that needs `jiter`, which is Rust
with no Termux wheel, and it was the single most common way installing this on
Android failed.

Without any key, screenshot ingestion is unavailable — fall back to a CSV:

```bash
cp examples/portfolio.csv my-portfolio.csv   # then edit it with your holdings
python -m portfolio_agent.cli analyze --portfolio-provider file
```

### If you'd rather use Claude than Gemini

```bash
bash deploy/termux/install-llm.sh   # then set LLM_PROVIDER=anthropic in .env
```

This tries two routes, in order:

1. **Install Rust and build the real `jiter`.** The proper fix. Needs
   Termux's `pkg install rust` — rustup can't do it, as it has no
   `aarch64-unknown-linux-android` target.
2. **Fall back to a pure-Python jiter shim** (`jiter_shim.py`) if that
   build fails. It installs the *real* Anthropic SDK and replaces only its
   `jiter` dependency.

The shim works because the SDK uses jiter in exactly four places, all in
`lib/streaming/`, for parsing partial JSON as it arrives. This app makes
plain non-streaming calls, so that code never runs — only the import at
module load actually fails. The shim is tested for output parity against
the real jiter (`tests/test_jiter_shim.py`), including both partial modes,
so streaming would still behave if something used it. It's slower, but
nothing here is on a hot path.

To switch to the real jiter later:

```bash
rm "$(python -c 'import sysconfig;print(sysconfig.get_paths()["purelib"])')/jiter.py"
pkg install rust && pip install jiter
```

## Connect Telegram

```bash
source .venv/bin/activate
python -m portfolio_agent.cli setup
```

## Run

```bash
bash deploy/termux/run-bot.sh
```

This takes a wake lock, starts the bot, and restarts it with backoff if it
dies. Logs go to `logs/bot.log`.

It also refuses to start if a bot is already running — Telegram allows only one
process per token, so a second one would just collect 409 Conflict errors. If it
says another instance is running but you're sure it isn't (e.g. Android killed
it mid-run), the pid file is stale and it clears it for you automatically; you
only need `pkill -f 'portfolio_agent.cli bot'` when a real second process is up.

## Keeping it alive

Android will kill this eventually unless you do all of the following:

1. **Battery: unrestricted.** Android Settings → Apps → Termux → Battery →
   *Unrestricted*. Do the same for Termux:Boot if you install it. This is the
   single most important step.
2. **Wake lock.** `pkg install termux-api` so `run-bot.sh` can take one.
   There's also a "Acquire wakelock" option in the Termux notification.
3. **Pin the app.** Open recents, pin Termux so a swipe-clear doesn't kill it.
4. **Start on boot** (optional): install
   [Termux:Boot](https://wiki.termux.com/wiki/Termux:Boot) from F-Droid, open it
   once, then:

   ```bash
   mkdir -p ~/.termux/boot
   cat > ~/.termux/boot/start-portfolio-agent <<'EOF'
   #!/data/data/com.termux/files/usr/bin/sh
   termux-wake-lock
   bash ~/stock-recomendations-agent/deploy/termux/run-bot.sh
   EOF
   chmod +x ~/.termux/boot/start-portfolio-agent
   ```

### The honest caveat

Even with all of that, Android 15 can still kill long-running Termux processes
— this is a [known, unresolved issue](https://github.com/termux/termux-app/issues/5150).
Expect occasional silence rather than true 24/7 uptime.

That matters less here than it would for most bots: this agent is **on-demand**,
not scheduled. Nothing is missed while it's down — `/analyze` just won't get a
reply until it's running again, and Telegram queues your messages, so the bot
picks them up when it restarts. If you find it dying often, either relaunch
Termux when you want a report, or move the bot to a cheap always-on host (a free
ARM VPS tier, or a Raspberry Pi) and keep using it from the same Telegram chat.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `^[[200~` in front of a command, or a stray `~` at the end | Paste artifact — the command didn't run. Run one line at a time, or disable bracketed paste (see top of this file). |
| `pkg: command not found` | If it persists when typed by hand, use `apt` instead: `apt update && apt install git`. |
| `No module named portfolio_agent` | You're not in the repo directory, or the venv isn't active. `cd stock-recomendations-agent && source .venv/bin/activate`. |
| `package not available, skipping: python-pandas` | Expected — Termux doesn't package pandas. The installer compiles it instead. |
| pandas build fails or gets killed | Out of memory. Close other apps and re-run; the build resumes from scratch but the pkg steps are instant the second time. |
| `No module named numpy` / `pandas` after install | Re-run `bash deploy/termux/install.sh`; it detects what's missing and only rebuilds that. |
| pydantic build hangs or gets killed | No prebuilt wheel matched your Python version, so it fell back to compiling Rust. Check the wheel index covers your Python (`python -V`). |
| `Failed to build 'jiter'` / `Target triple not supported by rustup` | Only affects the optional Anthropic backend. Either ignore it (Gemini is the default and needs nothing built), or run `bash deploy/termux/install-llm.sh`. |
| `GEMINI_API_KEY is not set` | Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then `python -m portfolio_agent.cli setup --keys-only`. |
| `Gemini has no model called ...` | The model name in `.env` was retired. Re-run `setup --keys-only` — it asks Google what your key can call and writes that. |
| `Gemini rate-limited this request` | Free-tier requests-per-minute cap. Wait a minute and ask again; a report only makes a couple of calls. |
| `This model is currently experiencing high demand` (503) | Google-side load on that model. The agent retries, then automatically tries other models your key has, so this only surfaces when they're all busy — wait a minute and resend. Pin specific alternates with `GEMINI_FALLBACK_MODELS` if you prefer. |
| `No module named pptx` | `pip install python-pptx` — needs `libxml2`/`libxslt` from `pkg` first. |
| `No time zone found with key America/New_York` | Android's time-zone database is in a format Python can't read, so every market-data call fails. `pip install tzdata` (the installer now does this for you). |
| Israeli holdings show no price | They don't use Yahoo — `.TA` tickers with a security number go to TASE's own API. Run `python -m portfolio_agent.cli check-tickers`; it prints `via tase` or `via yahoo` per ticker so you can see which side failed. |
| `getUpdates failed (409 Client Error: Conflict)` | Two bot instances are running — Telegram allows only one per token. Stop the other: `pkill -f 'portfolio_agent.cli bot'`, then start one. |
| `Another supervisor is already running` | The guard did its job — a bot is already up, so this one refused rather than fighting it for the token. Use the running one, or stop it with the `kill` command the message prints. |
| Bot replies stop when screen turns off | No wake lock. `pkg install termux-api`, and set battery to Unrestricted. |
| Deck has tables where charts should be | Expected without matplotlib. `pip install matplotlib` if you want charts. |
