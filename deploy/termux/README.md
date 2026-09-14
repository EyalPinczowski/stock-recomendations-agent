# Running on Termux (Android)

Termux works, but two things differ from a normal Linux host:

1. **Dependencies.** Termux uses Bionic libc, so PyPI's manylinux wheels don't
   install. Anything with C or Rust extensions needs a Termux-native package or
   an on-device build. `install.sh` handles this.
2. **Process lifetime.** There's no systemd, and Android kills background
   processes. `run-bot.sh` mitigates this; it can't fully solve it.

## Install

```bash
pkg install git
git clone https://github.com/EyalPinczowski/stock-recomendations-agent
cd stock-recomendations-agent
git checkout claude/portfolio-revenue-agent-jqdwpx
bash deploy/termux/install.sh
```

The installer pulls `numpy`/`pandas`/`pillow`/`lxml` from Termux's own repos
(never pip — pip would try to compile them), creates a venv with
`--system-site-packages` so those stay visible, and installs `pydantic` from a
[prebuilt Android wheel index](https://github.com/Eutalix/android-pydantic-core)
so its Rust core doesn't have to build on-device.

**matplotlib is skipped on purpose.** It's the hardest thing to build here, and
it's only used for the two allocation charts. Without it the deck renders those
as tables instead — everything else is identical. If you want the charts and
have patience: `pip install matplotlib`.

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
| `No module named numpy` / `pandas` | They didn't install from `pkg`. See [termux-packages #19126](https://github.com/termux/termux-packages/discussions/19126). |
| pydantic build hangs or gets killed | Out of memory building Rust. Close other apps, or use the prebuilt wheel index in `install.sh`. |
| `No module named pptx` | `pip install python-pptx` — needs `libxml2`/`libxslt` from `pkg` first. |
| Bot replies stop when screen turns off | No wake lock. `pkg install termux-api`, and set battery to Unrestricted. |
| Deck has tables where charts should be | Expected without matplotlib. `pip install matplotlib` if you want charts. |
