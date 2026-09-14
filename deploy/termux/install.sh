#!/data/data/com.termux/files/usr/bin/bash
# Termux (Android) installer.
#
# Termux uses Bionic libc, not glibc, so the manylinux wheels on PyPI don't
# work here. Anything with C/Rust extensions either needs a Termux-native
# package (`pkg install python-<name>`) or a build toolchain. This script
# prefers Termux packages, falls back to prebuilt Android wheels for
# pydantic-core, and skips matplotlib entirely (the deck renders allocation
# tables instead of charts without it).
#
# Usage:  bash deploy/termux/install.sh

set -euo pipefail

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$1"; }

# pkg install that doesn't abort the script when a package isn't in the repos.
try_pkg() {
    for package in "$@"; do
        if pkg install -y "$package" >/dev/null 2>&1; then
            printf '  installed: %s\n' "$package"
        else
            warn "package not available, skipping: $package"
        fi
    done
}

say "Updating Termux packages (this can take a few minutes)"
pkg update -y && pkg upgrade -y

say "Installing build tools and libraries"
try_pkg python git build-essential binutils cmake ninja patchelf \
        libopenblas libandroid-execinfo libxml2 libxslt \
        libjpeg-turbo libpng freetype

say "Installing native Python packages from Termux repos"
# These MUST come from pkg — pip would try to compile them from source.
try_pkg python-numpy python-pandas python-pillow python-lxml

say "Creating virtualenv (with access to the Termux-installed packages)"
python -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip

say "Verifying numpy/pandas are importable inside the venv"
MISSING=""
python - <<'PY' || MISSING="yes"
import sys
for module in ("numpy", "pandas"):
    try:
        __import__(module)
        print(f"  ok: {module}")
    except ImportError:
        print(f"  MISSING: {module}", file=sys.stderr)
        sys.exit(1)
PY

if [ -n "$MISSING" ]; then
    warn "numpy and/or pandas are missing. They could not be installed via pkg."
    warn "See https://github.com/termux/termux-packages/discussions/19126 for"
    warn "current build instructions, then re-run this script."
    exit 1
fi

say "Installing pydantic (prebuilt Android wheels for its Rust core)"
# pydantic-core is Rust; building it on-device takes ~15 min and often runs out
# of memory. This third-party index publishes prebuilt Termux wheels.
if ! pip install --extra-index-url https://eutalix.github.io/android-pydantic-core/ "pydantic>=2.6"; then
    warn "Prebuilt pydantic-core wheel unavailable for your Python/arch."
    warn "Falling back to building from source — install Rust first:"
    warn "    pkg install rust && pip install 'pydantic>=2.6'"
    warn "Expect ~15 minutes, and close other apps so it doesn't get OOM-killed."
    exit 1
fi

say "Installing the remaining (pure-Python) dependencies"
pip install -e .

say "Checking the install"
python - <<'PY'
import importlib

required = ["pandas", "numpy", "pydantic", "yfinance", "pptx", "anthropic", "requests", "yaml", "dotenv"]
for module in required:
    importlib.import_module(module)
    print(f"  ok: {module}")

try:
    import matplotlib  # noqa: F401
    print("  ok: matplotlib (deck will include charts)")
except ImportError:
    print("  matplotlib not installed — deck will use allocation tables instead of charts.")
    print("  That's expected on Termux and everything else works normally.")
PY

cat <<'EOF'

Install complete. Next:

  source .venv/bin/activate
  python -m portfolio_agent.cli setup          # connect your Telegram bot
  bash deploy/termux/run-bot.sh                # start the bot (keeps it alive)

To verify without any API keys or network:
  python -m portfolio_agent.cli analyze --portfolio-provider file --mock

EOF
