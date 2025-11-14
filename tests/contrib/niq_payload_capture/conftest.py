"""
Pytest configuration for NIQ payload capture tests.

This module provides shared fixtures and configuration for all payload capture tests.
"""

import pytest


@pytest.fixture(scope="session")
def httpbin_server():
    """
    Fixture that ensures httpbin test server is running.

    The dd-trace-py test suite typically uses a local httpbin-like server
    running on localhost:8001. This fixture can be extended to start/stop
    the server if needed.
    """
    # For now, assume server is running (via test infrastructure)
    # In full integration, you might start the server here
    yield "localhost:8001"


@pytest.fixture(autouse=True)
def reset_config():
    """
    Fixture that resets payload capture config after each test.

    This ensures tests don't interfere with each other by leaving
    config values set.
    """
    from ddtrace import config

    # Store original values
    original_capture = getattr(config, "niq_tracer_payload_capture", False)
    original_size = getattr(config, "niq_tracer_max_payload_size", 8192)
    original_server_capture = getattr(config, "niq_tracer_server_response_payload_capture", False)
    original_server_size = getattr(config, "niq_tracer_server_response_max_payload_size", 8192)

    yield

    # Reset to original values
    config.niq_tracer_payload_capture = original_capture
    config.niq_tracer_max_payload_size = original_size
    config.niq_tracer_server_response_payload_capture = original_server_capture
    config.niq_tracer_server_response_max_payload_size = original_server_size


@pytest.fixture
def mock_grpc_server():
    """
    Fixture that provides a mock gRPC server for testing.

    This is a placeholder for full gRPC integration tests.
    Real implementation would start a gRPC server with test services.
    """
    # TODO: Implement mock gRPC server if needed for integration tests
    yield None
