# NIQ Payload Capture Integration Tests

This directory contains comprehensive integration tests for the NIQ payload capture feature across all supported frameworks.

## Test Coverage

### Client Frameworks (`test_client_payload_capture.py`)
- **requests**: Request + response payload capture
- **httpx**: Sync and async request + response capture
- **aiohttp**: Async request + response capture via wrapper
- **urllib3**: Request + response payload capture
- **httplib (http.client)**: Standard library request + response capture

### Server Frameworks (`test_server_payload_capture.py`)
- **Flask (WSGI)**: Request + response payload capture
- **FastAPI (ASGI)**: Request + response payload capture
- **Django (WSGI)**: Request + response payload capture (planned)

### gRPC (`test_grpc_payload_capture.py`)
- **Unary-Unary**: Request + response capture via SerializeToString()
- **Unary-Stream**: Request capture + streaming response marker
- **Stream-Unary**: Streaming request marker + response capture
- **Stream-Stream**: Both streaming markers

## Test Categories

### 1. Configuration Tests
- Payload capture enabled/disabled
- Size limits respected
- Server response capture separate flag
- Environment variable configuration

### 2. Capture Tests
- Request payloads captured correctly
- Response payloads captured correctly
- Both captured when enabled
- Neither captured when disabled

### 3. Edge Cases
- Empty payloads
- Large payloads (truncation)
- Binary data
- Unicode/UTF-8 data
- JSON payloads
- Streaming responses

### 4. Application Integrity Tests
- Application code works normally
- Responses can be read correctly
- Multiple reads work (aiohttp wrapper)
- No crashes or errors introduced
- Silent failures don't break apps

## Running Tests

### Run All NIQ Payload Capture Tests
```bash
pytest tests/contrib/niq_payload_capture/ -v
```

### Run Specific Test Module
```bash
# Client framework tests
pytest tests/contrib/niq_payload_capture/test_client_payload_capture.py -v

# Server framework tests
pytest tests/contrib/niq_payload_capture/test_server_payload_capture.py -v

# gRPC tests
pytest tests/contrib/niq_payload_capture/test_grpc_payload_capture.py -v
```

### Run Specific Test Class
```bash
pytest tests/contrib/niq_payload_capture/test_client_payload_capture.py::TestRequestsPayloadCapture -v
```

### Run Specific Test
```bash
pytest tests/contrib/niq_payload_capture/test_client_payload_capture.py::TestRequestsPayloadCapture::test_request_payload_captured_when_enabled -v
```

### Run with Coverage
```bash
pytest tests/contrib/niq_payload_capture/ --cov=ddtrace/contrib/internal --cov-report=html -v
```

## Test Infrastructure Requirements

### Prerequisites
1. **Test HTTP Server**: Tests expect httpbin-like server on `localhost:8001`
   - Provides `/post`, `/json`, `/status/200` endpoints
   - Can use `scripts/run-tests` which handles server setup

2. **Framework Dependencies**: Install test dependencies
   ```bash
   pip install requests httpx aiohttp urllib3 grpcio protobuf flask fastapi
   ```

3. **Test Utilities**: Uses dd-trace-py test utilities
   - `TracerTestCase`: Base class with tracer setup/teardown
   - `override_config`: Context manager for config overrides
   - `pop_spans()`: Collect spans from test tracer

### Environment Variables (Optional)
```bash
# Enable payload capture for all tests
export NIQ_TRACER_PAYLOAD_CAPTURE=true
export NIQ_TRACER_MAX_PAYLOAD_SIZE=8192

# Enable server response capture
export NIQ_TRACER_SERVER_RESPONSE_PAYLOAD_CAPTURE=true
export NIQ_TRACER_SERVER_RESPONSE_MAX_PAYLOAD_SIZE=8192
```

## Test Structure

Each test module follows the pattern:

```python
class Test<Framework>PayloadCapture(TracerTestCase):
    def setUp(self):
        # Patch framework
        # Create test client/app

    def tearDown(self):
        # Unpatch framework

    def test_request_payload_captured(self):
        # Enable config
        # Make request
        # Assert request body in span tags

    def test_response_payload_captured(self):
        # Enable config
        # Make request
        # Assert response body in span tags

    def test_payload_not_captured_when_disabled(self):
        # Disable config
        # Make request
        # Assert no payload tags

    def test_application_not_broken(self):
        # Enable config
        # Make requests
        # Assert application functionality works
```

## Key Test Assertions

### Request Capture
```python
request_body = span.get_tag(HTTP_REQUEST_BODY)
assert request_body is not None
assert "expected_data" in request_body
```

### Response Capture
```python
response_body = span.get_tag(HTTP_RESPONSE_BODY)
assert response_body is not None
assert "expected_response" in response_body
```

### Size Limits
```python
assert len(request_body) < max_size * 2  # Accounting for truncation message
assert "truncated" in request_body.lower()
```

### Application Integrity
```python
# Application can still read response
data = resp.json()
assert data == expected_data

# Multiple reads work (aiohttp)
data1 = await resp.read()
data2 = await resp.read()
assert data1 == data2
```

## Debugging Tests

### View Captured Spans
```python
spans = self.pop_spans()
for span in spans:
    print(f"Span: {span.name}")
    print(f"  Request Body: {span.get_tag(HTTP_REQUEST_BODY)}")
    print(f"  Response Body: {span.get_tag(HTTP_RESPONSE_BODY)}")
```

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Run Single Test with Verbose Output
```bash
pytest tests/contrib/niq_payload_capture/test_client_payload_capture.py::TestRequestsPayloadCapture::test_request_payload_captured_when_enabled -vv -s
```

## Known Limitations

1. **gRPC Tests**: Require full gRPC server setup for complete integration testing. Current tests verify Protobuf serialization logic.

2. **Django Tests**: Planned but not yet implemented. Django has more complex setup requirements.

3. **Test Server**: Tests assume httpbin-like server is running. Future improvement: auto-start test server.

4. **Streaming Responses**: Full streaming response tests require careful setup to avoid consuming streams twice.

## Contributing

When adding new framework support:

1. Create test class in appropriate module
2. Follow existing test patterns
3. Test all scenarios:
   - Capture enabled/disabled
   - Request + response
   - Size limits
   - Application integrity
4. Add edge case tests
5. Update this README

## CI/CD Integration

These tests are designed to run in the standard dd-trace-py CI pipeline:

```bash
# Via riot (recommended)
riot run -p 3.11 -- pytest tests/contrib/niq_payload_capture/

# Via hatch
hatch run tests:test tests/contrib/niq_payload_capture/

# Via scripts/run-tests
scripts/run-tests --suite=niq_payload_capture
```

## Performance Benchmarks

Tests include assertions about overhead:
- Client-side capture: < 0.5ms per request
- Server-side request capture: < 0.1ms (no stream reading)
- Server-side response capture: < 1ms (buffering overhead)

Benchmark tests can be run with:
```bash
pytest tests/contrib/niq_payload_capture/ --benchmark
```

## Security Considerations

Tests verify:
- No PII leakage in test data
- Size limits prevent DoS
- Silent failures don't expose internals
- Application code never breaks
- Configuration defaults are safe (disabled)
