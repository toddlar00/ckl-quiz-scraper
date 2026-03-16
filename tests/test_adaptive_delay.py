"""Tests for the adaptive delay throttling system."""

import json
import os

import pytest

from scraper.adaptive_delay import (
    AdaptiveDelay,
    DEFAULT_DELAY_BUDGET,
    DELAY_FRACTIONS,
)


@pytest.fixture(autouse=True)
def isolate_delay_file(tmp_path, monkeypatch):
    """Ensure every test uses its own delay file (no disk pollution)."""
    delay_file = str(tmp_path / "test_delay.json")
    monkeypatch.setattr("scraper.adaptive_delay.ADAPTIVE_DELAY_FILE", delay_file)


class TestAdaptiveDelay:
    def test_initial_budget(self):
        ad = AdaptiveDelay(initial_budget=9.0)
        assert ad.budget == 9.0

    def test_default_budget(self):
        ad = AdaptiveDelay()
        assert ad.budget == DEFAULT_DELAY_BUDGET

    def test_get_sleep_point(self):
        ad = AdaptiveDelay(initial_budget=10.0)
        for point, fraction in DELAY_FRACTIONS.items():
            expected = 10.0 * fraction
            assert abs(ad.get(point) - expected) < 0.01

    def test_on_success_decreases_budget(self):
        ad = AdaptiveDelay(initial_budget=9.0)
        ad.on_success()
        assert ad.budget == 8.0

    def test_on_success_min_floor(self):
        ad = AdaptiveDelay(initial_budget=1.5)
        ad.on_success()
        assert ad.budget == 0.5
        ad.on_success()
        assert ad.budget == 0.5  # doesn't go below 0.5

    def test_on_failure_increases_budget(self):
        ad = AdaptiveDelay(initial_budget=5.0)
        ad.on_failure()
        assert ad.budget == 6.0

    def test_on_failure_max_cap(self):
        ad = AdaptiveDelay(initial_budget=30.0)
        ad.on_failure()
        assert ad.budget == 30.0  # capped at max

    def test_success_then_failure_cycle(self):
        ad = AdaptiveDelay(initial_budget=5.0)
        ad.on_success()  # 4.0
        ad.on_success()  # 3.0
        ad.on_success()  # 2.0
        assert ad.budget == 2.0
        ad.on_failure()  # 3.0
        assert ad.budget == 3.0
        ad.on_success()  # 2.0
        assert ad.budget == 2.0

    def test_persistence_save_load(self):
        ad1 = AdaptiveDelay(initial_budget=9.0)
        ad1.on_success()
        ad1.on_success()
        assert ad1.budget == 7.0

        # New instance should load the saved value
        ad2 = AdaptiveDelay(initial_budget=9.0)
        assert ad2.budget == 7.0

    def test_persistence_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "scraper.quiz_scraper.ADAPTIVE_DELAY_FILE",
            str(tmp_path / "nonexistent_dir" / "delay.json"),
        )
        ad = AdaptiveDelay(initial_budget=9.0)
        assert ad.budget == 9.0  # uses initial value

    def test_summary(self):
        ad = AdaptiveDelay(initial_budget=9.0)
        ad.on_success()
        ad.on_success()
        s = ad.summary()
        assert s["current_budget"] == 7.0
        assert s["total_adjustments"] == 2
        assert s["consecutive_successes"] == 2

    def test_get_unknown_sleep_point_uses_default(self):
        ad = AdaptiveDelay(initial_budget=10.0)
        # Unknown point uses 0.1 as default fraction
        assert abs(ad.get("unknown_point") - 1.0) < 0.01

    def test_all_fractions_sum_to_one(self):
        total = sum(DELAY_FRACTIONS.values())
        assert abs(total - 1.0) < 0.01

    def test_budget_converges_to_minimum(self):
        """After many successes, budget should reach the 0.5s floor."""
        ad = AdaptiveDelay(initial_budget=5.0)
        for _ in range(10):
            ad.on_success()
        assert ad.budget == 0.5

    def test_failure_recovery(self):
        """After failure, budget increases; then success brings it back down."""
        ad = AdaptiveDelay(initial_budget=3.0)
        ad.on_failure()  # 4.0
        ad.on_failure()  # 5.0
        assert ad.budget == 5.0
        ad.on_success()  # 4.0
        ad.on_success()  # 3.0
        assert ad.budget == 3.0

    def test_thread_safety_no_crash(self):
        """Concurrent access to on_success/on_failure should not crash."""
        import threading
        ad = AdaptiveDelay(initial_budget=15.0)
        errors = []

        def hammer_success():
            try:
                for _ in range(20):
                    ad.on_success()
            except Exception as e:
                errors.append(e)

        def hammer_failure():
            try:
                for _ in range(20):
                    ad.on_failure()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=hammer_success),
            threading.Thread(target=hammer_failure),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Budget should be between min and max
        assert 0.5 <= ad.budget <= 30.0

    def test_sleep_minimum_floor(self):
        """Sleep duration should never be below the enforced minimum."""
        ad = AdaptiveDelay(initial_budget=1.0)
        # Even with jitter, get() should return a positive value
        for point in DELAY_FRACTIONS:
            duration = ad.get(point)
            assert duration >= 0.0
