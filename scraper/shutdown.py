"""Graceful shutdown handling for the scraper.

Provides a cooperative shutdown mechanism: when the user presses Ctrl+C
(or sends SIGTERM), the scraper finishes the current question, saves a
checkpoint, exports any data collected so far, and exits cleanly.

Usage:
    from scraper.shutdown import shutdown_requested, request_shutdown

    # In a loop:
    while not shutdown_requested():
        do_work()

    # The signal handlers are installed automatically on import of main.py
"""

import logging
import signal
import threading

logger = logging.getLogger(__name__)

_shutdown_event = threading.Event()
_first_signal = True


def shutdown_requested():
    """Check if a graceful shutdown has been requested.

    Returns True after the first SIGINT/SIGTERM. The scraping loop
    should check this between questions and exit cleanly.
    """
    return _shutdown_event.is_set()


def request_shutdown():
    """Programmatically request a graceful shutdown."""
    _shutdown_event.set()


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown.

    First signal: sets the shutdown flag so the scraper can finish its
    current question and save progress.
    Second signal: raises KeyboardInterrupt for immediate exit.
    """
    global _first_signal
    sig_name = signal.Signals(signum).name

    if _first_signal:
        _first_signal = False
        logger.info(
            "\n%s received — finishing current question and saving progress...\n"
            "  Press Ctrl+C again to force quit immediately.",
            sig_name,
        )
        _shutdown_event.set()
    else:
        logger.info("\nForce quit requested. Exiting immediately.")
        raise KeyboardInterrupt


def install_signal_handlers():
    """Install graceful shutdown handlers for SIGINT and SIGTERM.

    Call this once at startup (in main.py) before the scraping loop begins.
    """
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    logger.debug("Graceful shutdown handlers installed")


def reset():
    """Reset shutdown state (for testing)."""
    global _first_signal
    _shutdown_event.clear()
    _first_signal = True
