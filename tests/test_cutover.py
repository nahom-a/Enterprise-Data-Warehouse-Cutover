"""Pytest test suite for warehouse-schema-cutover verifier.
Total tests: 144 (9 build tests + 135 mart equality tests across 9 windows).
"""
import pytest
from helpers import MARTS, WINDOWS, compare_mart_files, get_expected_mart_path, run_window

# Parameterize 75 window-mart pairs
WINDOW_MART_PAIRS = [f"{w}-{m}" for w in WINDOWS for m in MARTS]


@pytest.fixture(scope="session")
def build_outputs():
    """Runs each window once and caches the output directory or exception."""
    cache = {}
    errors = {}

    def _get_window_output(window: str):
        if window in errors:
            raise errors[window]
        if window not in cache:
            try:
                cache[window] = run_window(window)
            except Exception as e:
                errors[window] = e
                raise
        return cache[window]

    return _get_window_output


@pytest.mark.parametrize("window", WINDOWS)
def test_build(window, build_outputs):
    """Test that the analytics project builds cleanly on the platform data for window."""
    out_dir = build_outputs(window)
    assert out_dir.exists(), f"Output directory missing for window {window}"


@pytest.mark.parametrize("window_mart", WINDOW_MART_PAIRS)
def test_mart(window_mart, build_outputs):
    """Test that the generated mart matches the expected legacy mart multiset exactly."""
    window, mart = window_mart.split("-", 1)
    out_dir = build_outputs(window)

    actual_path = out_dir / f"{mart}.parquet"
    assert actual_path.exists(), f"Expected mart {mart}.parquet was not produced for {window}"

    expected_path = get_expected_mart_path(window, mart)
    assert expected_path.exists(), f"Expected reference mart not found: {expected_path}"

    errors = compare_mart_files(mart, actual_path, expected_path)
    assert not errors, f"Parity mismatch in {mart} for window {window}:\n" + "\n".join(errors)
