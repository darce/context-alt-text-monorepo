"""Integration helpers for external adapter calls."""

from recognition.application.integrations.circuit_breaker import (
	AdapterBreakerConfig,
	AdapterBreakerOpenError,
	AdapterBreakerSnapshot,
	AdapterBreakerState,
	AdapterCircuitBreaker,
	create_adapter_circuit_breaker,
)
from recognition.application.integrations.timeouts import AdapterTimeoutError, wait_for_adapter

__all__ = [
	"AdapterBreakerConfig",
	"AdapterBreakerOpenError",
	"AdapterBreakerSnapshot",
	"AdapterBreakerState",
	"AdapterCircuitBreaker",
	"create_adapter_circuit_breaker",
	"AdapterTimeoutError",
	"wait_for_adapter",
]