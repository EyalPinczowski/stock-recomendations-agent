# Running on Termux (Android)

Termux works, but two things differ from a normal Linux host:

1. **Dependencies.** Termux uses Bionic libc, so PyPI's manylinux wheels don't
   install. Anything with C or Rust extensions needs a Termux-native package or
   an on-device build. `install.sh` handles this.
2. **Process lifetime.** There's no systemd, and Android kills background
   processes. `run-bot.sh` mitigates this; it can't fully solve it.

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

**Two dependencies are optional**, because both are hard to build here and the
app degrades cleanly without either:

| Optional | Needs | Without it |
|---|---|---|
| `matplotlib` | a long C build | Deck renders allocation **tables** instead of charts. Nothing else changes. |
| `anthropic` (`.[llm]`) | **Rust**, for its `jiter` dependency | No screenshot parsing, news sentiment, or review pass. Technicals, screening, rebalancing and decks all still work. |

The installer tries to install Rust and build the Anthropic SDK, but treats a
failure as a warning rather than aborting — you end up with a working bot
either way. To retry later: `pkg install rust && pip install -e '.[llm]'`.

**If the Anthropic SDK won't build, you lose screenshot ingestion** — which is
the normal way to get your holdings in. Fall back to a CSV:

```bash
cp examples/portfolio.csv my-portfolio.csv   # then edit it with your holdings
python -m portfolio_agent.cli analyze --portfolio-provider file
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
| `Failed to build 'jiter'` / `Target triple not supported by rustup` | Rust isn't installed. rustup can't target Android — use Termux's: `pkg install rust`, then `pip install -e '.[llm]'`. |
| `The 'anthropic' package isn't installed` at runtime | Expected if the Rust build failed. Use `--portfolio-provider file` with a CSV, or retry `pkg install rust && pip install -e '.[llm]'`. |
| `No module named pptx` | `pip install python-pptx` — needs `libxml2`/`libxslt` from `pkg` first. |
| Bot replies stop when screen turns off | No wake lock. `pkg install termux-api`, and set battery to Unrestricted. |
| Deck has tables where charts should be | Expected without matplotlib. `pip install matplotlib` if you want charts. |
