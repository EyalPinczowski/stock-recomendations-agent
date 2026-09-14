"""Pure-Python stand-in for `jiter`, for hosts where it cannot be built.

`jiter` is a Rust JSON parser that the `anthropic` SDK imports. It has no
Termux/Android wheel and building it needs a Rust toolchain that rustup can't
provide for Android, so on some devices the SDK simply cannot be installed.

The SDK only ever uses jiter in `lib/streaming/` — four call sites, all for
parsing partial JSON as it streams in. Code that makes ordinary
(non-streaming) `messages.create()` calls never executes any of it; the import
at module load is the only thing that actually fails. This module satisfies
that import with `json` from the standard library, and implements partial
parsing well enough that streaming still behaves correctly if it is used.

Slower than the real thing, obviously. It's a fallback, not a replacement —
install the real jiter (`pkg install rust && pip install jiter`) when you can.

Installed by deploy/termux/install-llm.sh only when the Rust build fails.
"""

from __future__ import annotations

import json

__all__ = ["LosslessFloat", "cache_clear", "cache_usage", "from_json"]

# Lets callers (and our own diagnostics) tell this apart from the real package.
__is_shim__ = True


class LosslessFloat(float):
    """jiter returns these under float_mode='lossless-float'; we keep the raw
    text alongside the float so repr() round-trips like the real one."""

    def __new__(cls, raw: str | bytes):
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        obj = super().__new__(cls, float(text))
        obj._raw = text
        return obj

    def as_decimal(self):
        from decimal import Decimal

        return Decimal(self._raw)

    def __bytes__(self) -> bytes:
        return self._raw.encode()

    def __repr__(self) -> str:
        return self._raw

    __str__ = __repr__


def cache_clear() -> None:
    """No-op: this shim has no string cache."""


def cache_usage() -> int:
    """No-op: this shim has no string cache."""
    return 0


def _reject_constant(name: str):
    raise ValueError(f"{name} is not allowed when allow_inf_nan=False")


def _duplicate_key_hook(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"Detected duplicate key: {key}")
        seen.add(key)
    return dict(pairs)


def _repair_truncated(text: str, keep_trailing_string: bool) -> str:
    """Close any structures left open by a truncated document."""
    stack: list[str] = []
    in_string = False
    escaped = False

    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            stack.append("]")
        elif ch == "{":
            stack.append("}")
        elif ch in "]}" and stack:
            stack.pop()

    repaired = text
    if in_string:
        if escaped:
            repaired = repaired[:-1]  # drop a dangling escape
        if keep_trailing_string:
            repaired += '"'
        else:
            # Discard the incomplete string entirely.
            repaired = repaired[: repaired.rindex('"')]
            repaired = repaired.rstrip()
            if repaired.endswith(":"):
                repaired = repaired[:-1].rstrip()
                repaired = repaired[: repaired.rindex('"')] if '"' in repaired else repaired

    repaired = repaired.rstrip()
    while repaired and repaired[-1] in ",:":
        repaired = repaired[:-1].rstrip()

    return repaired + "".join(reversed(stack))


def _parse_partial(text: str, keep_trailing_string: bool, **kwargs):
    """Best-effort parse of an incomplete document, mirroring jiter's
    partial_mode: return whatever has arrived so far rather than raising."""
    repaired = _repair_truncated(text, keep_trailing_string)
    try:
        return json.loads(repaired, **kwargs)
    except json.JSONDecodeError:
        pass

    # Fall back to trimming from the end until something parses.
    for end in range(len(text) - 1, 0, -1):
        candidate = _repair_truncated(text[:end], keep_trailing_string)
        if not candidate:
            continue
        try:
            return json.loads(candidate, **kwargs)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Unable to parse partial JSON: {text[:80]!r}")


def from_json(
    json_data,
    /,
    *,
    allow_inf_nan: bool = True,
    cache_mode=None,
    partial_mode=False,
    catch_duplicate_keys: bool = False,
    float_mode=None,
):
    """Drop-in for jiter.from_json, backed by the standard library."""
    if isinstance(json_data, (bytes, bytearray, memoryview)):
        text = bytes(json_data).decode("utf-8")
    else:
        text = json_data

    kwargs = {}
    if not allow_inf_nan:
        kwargs["parse_constant"] = _reject_constant
    if catch_duplicate_keys:
        kwargs["object_pairs_hook"] = _duplicate_key_hook
    if float_mode == "decimal":
        from decimal import Decimal

        kwargs["parse_float"] = Decimal
    elif float_mode == "lossless-float":
        kwargs["parse_float"] = LosslessFloat

    try:
        return json.loads(text, **kwargs)
    except json.JSONDecodeError as exc:
        # partial_mode: True/"on" tolerate truncation, "trailing-strings" also
        # keeps a half-received string value. False/"off" propagate the error.
        if partial_mode in (False, "off", None):
            raise ValueError(str(exc)) from exc
        return _parse_partial(
            text, keep_trailing_string=(partial_mode == "trailing-strings"), **kwargs
        )
