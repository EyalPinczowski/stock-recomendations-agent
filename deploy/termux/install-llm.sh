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
    say "Success — built with the real jiter"
    python -c "import anthropic; print('  anthropic', anthropic.__version__, 'installed')"
    echo
    echo "Screenshot parsing, news sentiment and the review pass are now available."
    echo "Restart the bot to pick it up:  bash deploy/termux/run-bot.sh"
    exit 0
fi

echo
warn "The Rust build failed — the full error is above."
warn "Usual causes: out of memory, or an Android kernel that can't build Rust."
echo
say "Falling back to the pure-Python jiter shim"
cat <<'EXPLAIN'
  The SDK only uses jiter for streaming responses, which this app never does —
  it makes plain non-streaming calls. So a pure-Python stand-in satisfies the
  import and everything works. It's slower than the Rust original, but nothing
  here is on a hot path.

  This installs the real Anthropic SDK; only its jiter dependency is replaced.
EXPLAIN

SITE_PACKAGES="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
if [ ! -d "$SITE_PACKAGES" ]; then
    warn "Couldn't locate site-packages; aborting."
    exit 1
fi

say "Installing the Anthropic SDK without its Rust dependency"
if ! pip install --no-deps "anthropic>=0.34"; then
    warn "Couldn't install the Anthropic SDK itself. Aborting."
    exit 1
fi
# --no-deps skipped anthropic's other (pure-Python) requirements too; add them
# back explicitly, minus jiter.
pip install "httpx>=0.23" "anyio>=3.5" "distro>=1.7" "sniffio" "typing-extensions>=4.10" "pydantic>=2.6" || true

cp "$(dirname "${BASH_SOURCE[0]}")/jiter_shim.py" "$SITE_PACKAGES/jiter.py"
printf '  installed shim: %s\n' "$SITE_PACKAGES/jiter.py"

say "Verifying"
if python - <<'PY'
import sys
import jiter
if not getattr(jiter, "__is_shim__", False):
    print("  note: the real jiter is installed, not the shim")
else:
    print("  jiter: pure-Python shim active")
import anthropic
print("  anthropic", anthropic.__version__, "imports OK")
# Round-trip the shim on a payload shaped like a holdings extraction
data = jiter.from_json(b'[{"identifier": "TEVA.TA", "quantity": 200, "currency": "ILS"}]')
assert data[0]["quantity"] == 200, data
print("  JSON parsing verified")
PY
then
    echo
    echo "Screenshot parsing, news sentiment and the review pass are now available."
    echo "Restart the bot to pick it up:  bash deploy/termux/run-bot.sh"
    echo
    warn "You're on the pure-Python jiter shim. To switch to the real one later:"
    warn "    rm '$SITE_PACKAGES/jiter.py' && pkg install rust && pip install jiter"
else
    warn "Verification failed. Removing the shim to leave a clean state."
    rm -f "$SITE_PACKAGES/jiter.py"
    warn "Use the CSV path instead:"
    warn "    cp examples/portfolio.csv my-portfolio.csv   # then edit it"
    warn "    python -m portfolio_agent.cli analyze --portfolio-provider file"
    exit 1
fi
