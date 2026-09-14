"""The pure-Python jiter shim (deploy/termux/jiter_shim.py) is the fallback that
lets the Anthropic SDK install on hosts where its Rust dependency can't be
built. These tests pin its behaviour against the real jiter's contract.
"""

import importlib.util
from pathlib import Path

import pytest

SHIM_PATH = Path(__file__).resolve().parents[1] / "deploy" / "termux" / "jiter_shim.py"


def _load_shim():
    spec = importlib.util.spec_from_file_location("_jiter_shim_under_test", SHIM_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def shim():
    return _load_shim()


def test_parses_complete_documents(shim):
    assert shim.from_json(b'{"a": 1, "b": "two"}') == {"a": 1, "b": "two"}
    assert shim.from_json(b"[1, 2, 3]") == [1, 2, 3]
    assert shim.from_json(b"null") is None


def test_parses_unicode_including_hebrew(shim):
    """TASE holdings come back with Hebrew company names."""
    payload = '{"identifier": "טבע", "quantity": 200}'.encode()
    assert shim.from_json(payload) == {"identifier": "טבע", "quantity": 200}


def test_accepts_str_and_bytes(shim):
    assert shim.from_json('{"a": 1}') == {"a": 1}
    assert shim.from_json(b'{"a": 1}') == {"a": 1}


def test_partial_mode_recovers_truncated_object(shim):
    assert shim.from_json(b'{"a": 1, "b"', partial_mode=True) == {"a": 1}
    assert shim.from_json(b'{"x": [1, 2,', partial_mode=True) == {"x": [1, 2]}


def test_partial_mode_trailing_strings_keeps_partial_value(shim):
    result = shim.from_json(b'{"a": 1, "b": "tw', partial_mode="trailing-strings")
    assert result == {"a": 1, "b": "tw"}


def test_partial_mode_off_raises_on_truncation(shim):
    with pytest.raises(ValueError):
        shim.from_json(b'{"a": 1, "b"', partial_mode=False)


def test_invalid_json_raises_value_error(shim):
    """The SDK catches ValueError specifically, so the type matters."""
    with pytest.raises(ValueError):
        shim.from_json(b"not json at all")


def test_catch_duplicate_keys(shim):
    with pytest.raises(ValueError, match="duplicate"):
        shim.from_json(b'{"a": 1, "a": 2}', catch_duplicate_keys=True)
    assert shim.from_json(b'{"a": 1, "a": 2}') == {"a": 2}


def test_allow_inf_nan_false_rejects_constants(shim):
    with pytest.raises(ValueError):
        shim.from_json(b"[NaN]", allow_inf_nan=False)
    assert shim.from_json(b"[NaN]")[0] != shim.from_json(b"[NaN]")[0]  # NaN != NaN


def test_lossless_float_roundtrips_raw_text(shim):
    value = shim.from_json(b"[1.2345678901234567890]", float_mode="lossless-float")[0]
    assert repr(value) == "1.2345678901234567890"
    assert float(value) == pytest.approx(1.2345678901234567890)


def test_module_is_marked_as_a_shim(shim):
    """install-llm.sh and diagnostics rely on this flag to tell the shim apart
    from the real Rust package."""
    assert shim.__is_shim__ is True


def test_cache_helpers_exist(shim):
    """Present in jiter's public API; callers may touch them."""
    shim.cache_clear()
    assert isinstance(shim.cache_usage(), int)
