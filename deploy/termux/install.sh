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
try_pkg python git build-essential binutils binutils-is-llvm clang \
        cmake ninja patchelf libopenblas libandroid-execinfo \
        libxml2 libxslt libjpeg-turbo libpng freetype

say "Installing native Python packages from Termux repos"
# Prefer pkg over pip for these — pip would try to compile them from source.
# python-pandas isn't in the Termux repos, so it gets built below instead.
try_pkg python-numpy python-pandas python-pillow python-lxml

say "Creating virtualenv (with access to the Termux-installed packages)"
python -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip

PYVER="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
say "Python $PYVER detected"

importable() { python -c "import $1" >/dev/null 2>&1; }

say "Checking numpy/pandas"
for module in numpy pandas; do
    if importable "$module"; then
        printf '  ok: %s\n' "$module"
    else
        printf '  missing: %s (will build from source)\n' "$module"
    fi
done

if ! importable numpy || ! importable pandas; then
    say "Installing build backends needed to compile them"
    pip install --no-cache-dir setuptools wheel packaging pyproject_metadata \
        cython meson-python versioneer setuptools-scm

    # Termux needs to link explicitly against libpython, and numpy needs MATHLIB.
    # --no-build-isolation makes the build use the tools installed above (and the
    # pkg-provided numpy headers) rather than fetching its own copies.
    export LDFLAGS="-lpython${PYVER}"
    export MATHLIB=m

    if ! importable numpy; then
        say "Building numpy (several minutes)"
        pip install --no-build-isolation --no-cache-dir numpy
    fi

    if ! importable pandas; then
        say "Building pandas — this is the slow one, 10-30 min. Keep the screen on."
        if ! pip install --no-build-isolation --no-cache-dir pandas; then
            warn "pandas failed to build. Most common causes:"
            warn "  - out of memory: close other apps and re-run"
            warn "  - missing build tool: see"
            warn "    https://github.com/termux/termux-packages/discussions/25247"
            exit 1
        fi
    fi

    unset LDFLAGS MATHLIB
fi

say "Installing pydantic (prebuilt Android wheels for its Rust core)"
# pydantic-core is Rust; building it on-device takes ~15 min and often gets
# OOM-killed. These third-party indexes publish prebuilt Termux wheels.
# Goplr covers Python 3.9-3.14; Eutalix (3.9-3.13) is the fallback.
if ! pip install --extra-index-url https://Goplr.github.io/android-pydantic-core/ "pydantic>=2.6" \
   && ! pip install --extra-index-url https://eutalix.github.io/android-pydantic-core/ "pydantic>=2.6"; then
    warn "No prebuilt pydantic-core wheel for Python $PYVER on this architecture."
    warn "Build it from source instead (slow, memory-hungry):"
    warn "    pkg install rust && pip install 'pydantic>=2.6'"
    warn "Close other apps first so it doesn't get OOM-killed."
    exit 1
fi

say "Installing the core (pure-Python) dependencies"
pip install -e .

# The anthropic SDK needs `jiter`, which is Rust and has no Termux wheel. It
# powers screenshot parsing, news sentiment, and the review pass — valuable, but
# the rest of the app runs without it, so a failure here is a warning, not fatal.
say "Installing the Anthropic SDK (needs Rust to build its jiter dependency)"
if ! importable jiter; then
    if ! command -v cargo >/dev/null 2>&1; then
        say "Installing Rust (large download; rustup can't target Android, Termux's package can)"
        try_pkg rust
    fi
fi

LLM_OK="yes"
if ! pip install -e ".[llm]"; then
    LLM_OK=""
    warn "Couldn't build the Anthropic SDK (jiter needs Rust)."
    warn "Everything except screenshot parsing, news sentiment and the review"
    warn "pass still works. To retry later:"
    warn "    pkg install rust && pip install -e '.[llm]'"
fi

say "Checking the install"
python - <<'PY'
import importlib

for module in ["pandas", "numpy", "pydantic", "yfinance", "pptx", "requests", "yaml", "dotenv"]:
    importlib.import_module(module)
    print(f"  ok: {module}")

for module, missing_note in [
    ("matplotlib", "deck will use allocation tables instead of charts"),
    ("anthropic", "screenshot parsing, sentiment and the review pass are unavailable"),
]:
    try:
        importlib.import_module(module)
        print(f"  ok: {module}")
    except ImportError:
        print(f"  {module} not installed — {missing_note}.")
PY

echo
echo "Install complete. Next:"
echo
echo "  source .venv/bin/activate"
echo "  python -m portfolio_agent.cli setup          # connect your Telegram bot"
echo "  bash deploy/termux/run-bot.sh                # start the bot (keeps it alive)"
echo
echo "To verify without any API keys or network:"
echo "  python -m portfolio_agent.cli analyze --portfolio-provider file --mock"
if [ -z "$LLM_OK" ]; then
    echo
    warn "Reminder: without the Anthropic SDK you can't send portfolio screenshots."
    warn "Use a CSV instead:  cp examples/portfolio.csv my-portfolio.csv  (then edit it)"
    warn "and run with:  --portfolio-provider file"
fi

EOF
