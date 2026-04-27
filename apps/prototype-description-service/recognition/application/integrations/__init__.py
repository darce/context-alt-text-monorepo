"""Integration helpers for external adapter calls."""

from recognition.application.integrations.timeouts import AdapterTimeoutError, wait_for_adapter

__all__ = ["AdapterTimeoutError", "wait_for_adapter"]