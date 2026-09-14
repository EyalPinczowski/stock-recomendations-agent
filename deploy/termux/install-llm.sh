#!/data/data/com.termux/files/usr/bin/bash
# Installs just the Anthropic SDK (the `.[llm]` extra) on Termux, with full
# output so a failure is diagnosable.
#
# Split out from install.sh because this is the one step most likely to fail:
# the SDK depends on `jiter`, which is Rust, has no Termux wheel, and cannot be
# built via rustup (rustup has no aarch64-unknown-linux-android target). Termux's
# own `pkg install rust` provides a cargo that can.
#
# Usage:  bash deploy/termux/install-llm.sh

set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$1"; }

if [ ! -f .venv/bin/activate ]; then
    warn "No virtualenv found. Run: bash deploy/termux/install.sh"
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

say "Environment"
printf '  python:  %s\n' "$(python --version 2>&1)"
printf '  arch:    %s\n' "$(uname -m)"
printf '  kernel:  %s\n' "$(uname -r)"

if python -c "import anthropic" >/dev/null 2>&1; then
    say "anthropic is already installed — nothing to do."
    python -c "import anthropic; print('  version:', anthropic.__version__)"
    exit 0
fi

say "Checking for Rust"
if command -v cargo >/dev/null 2>&1; then
    printf '  cargo:   %s\n' "$(cargo --version)"
    printf '  rustc:   %s\n' "$(rustc --version 2>/dev/null || echo '(not found)')"
else
    printf '  cargo:   not installed\n'
    say "Installing Rust via pkg (rustup does not support Android targets)"
    if ! pkg install -y rust; then
        warn "Could not install Rust from the Termux repos."
        warn "Try:  pkg update && pkg install rust"
        exit 1
    fi
fi

if ! command -v cargo >/dev/null 2>&1; then
    warn "Rust installed but cargo still isn't on PATH. Try a fresh Termux session."
    exit 1
fi

say "Building the Anthropic SDK (jiter compiles from Rust — several minutes)"
warn "Keep the screen on and close other apps; this step can be OOM-killed."
if pip install -e ".[llm]"; then
    say "Success"
    python -c "import anthropic; print('  anthropic', anthropic.__version__, 'installed')"
    echo
    echo "Screenshot parsing, news sentiment and the review pass are now available."
    echo "Restart the bot to pick it up:  bash deploy/termux/run-bot.sh"
else
    echo
    warn "Build failed — the full error is above."
    warn "Common causes:"
    warn "  - out of memory (most likely): close all other apps and retry"
    warn "  - older Android kernel: some devices can't build Rust extensions"
    warn
    warn "You don't need this to use the bot. Without it you lose screenshot"
    warn "parsing, so supply holdings as a CSV instead:"
    warn "    cp examples/portfolio.csv my-portfolio.csv   # then edit it"
    warn "    python -m portfolio_agent.cli analyze --portfolio-provider file"
    exit 1
fi
