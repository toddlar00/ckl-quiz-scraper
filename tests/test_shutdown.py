"""Tests for graceful shutdown handling."""

import signal

from scraper.shutdown import (
    _signal_handler,
    install_signal_handlers,
    request_shutdown,
    reset,
    shutdown_requested,
)


class TestShutdownFlag:
    def setup_method(self):
        reset()

    def test_not_requested_by_default(self):
        assert shutdown_requested() is False

    def test_request_shutdown_sets_flag(self):
        request_shutdown()
        assert shutdown_requested() is True

    def test_reset_clears_flag(self):
        request_shutdown()
        assert shutdown_requested() is True
        reset()
        assert shutdown_requested() is False


class TestSignalHandler:
    def setup_method(self):
        reset()

    def test_first_signal_sets_shutdown(self):
        _signal_handler(signal.SIGINT, None)
        assert shutdown_requested() is True

    def test_second_signal_raises_keyboard_interrupt(self):
        _signal_handler(signal.SIGINT, None)
        try:
            _signal_handler(signal.SIGINT, None)
            assert False, "Should have raised KeyboardInterrupt"
        except KeyboardInterrupt:
            pass

    def test_first_signal_with_sigterm(self):
        _signal_handler(signal.SIGTERM, None)
        assert shutdown_requested() is True


class TestInstallHandlers:
    def setup_method(self):
        reset()

    def test_install_does_not_raise(self):
        # Just verify it runs without error; actual signal handling
        # is tested via _signal_handler directly
        install_signal_handlers()

    def test_reset_after_install(self):
        install_signal_handlers()
        request_shutdown()
        reset()
        assert shutdown_requested() is False
