"""Adaptive delay system for throttling scraping speed.

Automatically adjusts timing between requests based on success/failure
feedback. Decreases delay on success, increases on failure, with
persistence across runs.

Thread Safety:
    The global AdaptiveDelay singleton is NOT thread-safe. If multiple
    threads call on_success/on_failure concurrently, budget updates may
    race. Use threading.Lock externally if concurrent access is needed,
    or create per-thread instances.
"""

import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

ADAPTIVE_DELAY_FILE = ".ckl_adaptive_delay.json"

# Default total sleep budget per question (sum of all original hardcoded sleeps).
# Original: 1s (pre-submit) + 2s (post-submit) + 2s (feedback wait) + 3s (next click) + 1s (rate limit) = 9s
DEFAULT_DELAY_BUDGET = 9.0

# Proportional distribution of the delay budget across sleep points.
# These fractions sum to 1.0 and represent where time is spent per question.
DELAY_FRACTIONS = {
    "pre_submit": 0.11,    # After selecting radio, before clicking Submit (orig 1s)
    "post_submit": 0.22,   # After clicking Submit, waiting for feedback (orig 2s)
    "feedback_wait": 0.22, # After submit_answer returns, before reading feedback (orig 2s)
    "next_click": 0.34,    # After clicking Next Question, waiting for page (orig 3s)
    "rate_limit": 0.11,    # Between questions rate limit (orig 1s)
}


class AdaptiveDelay:
    """Finds the minimum viable delay by decreasing on success and increasing on failure.

    Strategy:
      - Start with a total delay budget (seconds per question).
      - Each successful question: reduce budget by 1 second.
      - Each failure (timeout, parse error): increase budget by 1 second.
      - Individual sleep points get proportional fractions of the total budget.
      - The learned delay is saved to disk and reloaded on next run.
    """

    def __init__(self, initial_budget=None):
        self._budget = initial_budget or DEFAULT_DELAY_BUDGET
        self._min_budget = 0.5
        self._max_budget = 30.0
        self._consecutive_successes = 0
        self._consecutive_failures = 0
        self._total_adjustments = 0
        self._lock = threading.Lock()
        self._load()
        logger.info(
            "Adaptive delay: starting budget = %.1fs per question "
            "(sleeps: pre_submit=%.1fs, post_submit=%.1fs, feedback=%.1fs, "
            "next=%.1fs, rate_limit=%.1fs)",
            self._budget,
            self.get("pre_submit"), self.get("post_submit"),
            self.get("feedback_wait"), self.get("next_click"),
            self.get("rate_limit"),
        )

    @property
    def budget(self):
        return self._budget

    def get(self, sleep_point):
        """Get the delay in seconds for a named sleep point."""
        fraction = DELAY_FRACTIONS.get(sleep_point, 0.1)
        return max(0.0, self._budget * fraction)

    def sleep(self, sleep_point):
        """Sleep for the adaptive duration with human-like jitter.

        Adds gaussian jitter (+-30%) around the computed duration so timing
        patterns don't look robotic to anti-bot systems. Enforces a minimum
        floor to prevent zero-length sleeps.
        """
        import random
        duration = self.get(sleep_point)
        if duration > 0:
            # Add jitter: +-30% gaussian noise
            jitter = random.gauss(0, duration * 0.15)
            # Enforce minimum floor of 50ms or 25% of duration, whichever is larger
            floor = max(0.05, duration * 0.25)
            actual = max(floor, duration + jitter)
            time.sleep(actual)

    def on_success(self):
        """Called after a question is successfully scraped."""
        with self._lock:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            old = self._budget
            if self._budget > self._min_budget:
                self._budget = max(self._min_budget, self._budget - 1.0)
                self._total_adjustments += 1
            if old != self._budget:
                logger.info(
                    "  Adaptive delay: success -> reduced %.1fs -> %.1fs",
                    old, self._budget,
                )
            self._save()

    def on_failure(self):
        """Called after a question fails to scrape (timeout, parse error)."""
        with self._lock:
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            old = self._budget
            if self._budget < self._max_budget:
                self._budget = min(self._max_budget, self._budget + 1.0)
                self._total_adjustments += 1
            logger.info(
                "  Adaptive delay: failure -> increased %.1fs -> %.1fs",
                old, self._budget,
            )
            self._save()

    def summary(self):
        """Return a summary dict for logging."""
        return {
            "current_budget": self._budget,
            "total_adjustments": self._total_adjustments,
            "consecutive_successes": self._consecutive_successes,
        }

    def _load(self):
        """Load saved delay from disk."""
        if not os.path.exists(ADAPTIVE_DELAY_FILE):
            return
        try:
            with open(ADAPTIVE_DELAY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved = data.get("budget")
            if saved is not None and isinstance(saved, (int, float)):
                self._budget = max(self._min_budget, min(self._max_budget, float(saved)))
                logger.info("Loaded saved adaptive delay: %.1fs", self._budget)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Could not load adaptive delay: %s", e)

    def _save(self):
        """Save current delay to disk."""
        try:
            data = {
                "budget": self._budget,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(ADAPTIVE_DELAY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.debug("Could not save adaptive delay: %s", e)


# The global adaptive delay instance, initialized lazily.
_adaptive_delay = None
_global_lock = threading.Lock()


def get_adaptive_delay():
    """Get or create the global AdaptiveDelay instance (thread-safe)."""
    global _adaptive_delay
    if _adaptive_delay is None:
        with _global_lock:
            if _adaptive_delay is None:
                _adaptive_delay = AdaptiveDelay()
    return _adaptive_delay


def reset_adaptive_delay():
    """Reset the adaptive delay to defaults (for --fresh mode)."""
    global _adaptive_delay
    with _global_lock:
        _adaptive_delay = AdaptiveDelay(initial_budget=DEFAULT_DELAY_BUDGET)
    if os.path.exists(ADAPTIVE_DELAY_FILE):
        os.remove(ADAPTIVE_DELAY_FILE)
