"""
Integration tests for NIQ payload capture across client frameworks.

Tests verify that payload capture works correctly for:
- requests
- httpx (sync and async)
- aiohttp
- urllib3
- httplib (http.client)

Each test ensures:
1. Payloads are captured when enabled
2. Payloads are NOT captured when disabled
3. Size limits are respected
4. Application code continues to work normally
5. Both request and response payloads are captured
"""

import json

import pytest

from ddtrace import config
from ddtrace.internal.constants import HTTP_REQUEST_BODY
from ddtrace.internal.constants import HTTP_RESPONSE_BODY
from tests.utils import TracerTestCase
from tests.utils import override_config


# Test server URLs (httpbin-like endpoints)
HOST_AND_PORT = "localhost:8001"
URL_200 = "http://{}/status/200".format(HOST_AND_PORT)
URL_POST = "http://{}/post".format(HOST_AND_PORT)
URL_JSON = "http://{}/json".format(HOST_AND_PORT)


class TestRequestsPayloadCapture(TracerTestCase):
    """Test payload capture for requests library"""

    def setUp(self):
        super(TestRequestsPayloadCapture, self).setUp()
        # Import and patch requests
        import requests
        from ddtrace.contrib.internal.requests.patch import patch
        from ddtrace.contrib.internal.requests.patch import unpatch

        unpatch()  # Ensure clean state
        patch()
        self.requests = requests
        self.session = requests.Session()
        self.session.datadog_tracer = self.tracer

    def tearDown(self):
        from ddtrace.contrib.internal.requests.patch import unpatch

        unpatch()
        super(TestRequestsPayloadCapture, self).tearDown()

    def test_request_payload_captured_when_enabled(self):
        """Verify request body is captured when payload capture is enabled"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_max_payload_size", 8192):
                request_data = {"test": "data", "foo": "bar"}
                resp = self.session.post(URL_POST, json=request_data)
                assert resp.status_code == 200

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                # Verify request body was captured
                request_body = span.get_tag(HTTP_REQUEST_BODY)
                assert request_body is not None
                assert "test" in request_body
                assert "data" in request_body

    def test_request_payload_not_captured_when_disabled(self):
        """Verify request body is NOT captured when payload capture is disabled"""
        with override_config("niq_tracer_payload_capture", False):
            request_data = {"test": "data"}
            resp = self.session.post(URL_POST, json=request_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            # Verify request body was NOT captured
            request_body = span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is None

    def test_response_payload_captured_when_enabled(self):
        """Verify response body is captured when payload capture is enabled"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_max_payload_size", 8192):
                resp = self.session.get(URL_JSON)
                assert resp.status_code == 200
                # Ensure application can still read response
                data = resp.json()
                assert isinstance(data, dict)

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                # Verify response body was captured
                response_body = span.get_tag(HTTP_RESPONSE_BODY)
                assert response_body is not None

    def test_payload_size_limit_respected(self):
        """Verify payloads are truncated at max_size"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_max_payload_size", 50):
                # Send large payload
                large_data = {"key": "x" * 1000}
                resp = self.session.post(URL_POST, json=large_data)
                assert resp.status_code == 200

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                request_body = span.get_tag(HTTP_REQUEST_BODY)
                assert request_body is not None
                # Should be truncated
                assert "truncated" in request_body.lower()
                assert len(request_body) < 200  # Much smaller than original

    def test_application_code_not_broken(self):
        """Verify application code works normally with payload capture enabled"""
        with override_config("niq_tracer_payload_capture", True):
            # POST request
            request_data = {"test": "value"}
            resp = self.session.post(URL_POST, json=request_data)
            assert resp.status_code == 200
            echo_data = resp.json()
            assert echo_data["json"] == request_data

            # GET request
            resp = self.session.get(URL_JSON)
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)


@pytest.mark.asyncio
class TestHttpxPayloadCapture(TracerTestCase):
    """Test payload capture for httpx library (sync and async)"""

    def setUp(self):
        super(TestHttpxPayloadCapture, self).setUp()
        try:
            import httpx
            from ddtrace.contrib.internal.httpx.patch import patch
            from ddtrace.contrib.internal.httpx.patch import unpatch

            unpatch()
            patch()
            self.httpx = httpx
        except ImportError:
            pytest.skip("httpx not installed")

    def tearDown(self):
        from ddtrace.contrib.internal.httpx.patch import unpatch

        unpatch()
        super(TestHttpxPayloadCapture, self).tearDown()

    def test_sync_request_payload_captured(self):
        """Verify sync httpx request body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            with self.httpx.Client() as client:
                request_data = {"httpx": "test"}
                resp = client.post(URL_POST, json=request_data)
                assert resp.status_code == 200

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                request_body = span.get_tag(HTTP_REQUEST_BODY)
                assert request_body is not None
                assert "httpx" in request_body

    async def test_async_request_payload_captured(self):
        """Verify async httpx request body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            async with self.httpx.AsyncClient() as client:
                request_data = {"async": "httpx"}
                resp = await client.post(URL_POST, json=request_data)
                assert resp.status_code == 200

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                request_body = span.get_tag(HTTP_REQUEST_BODY)
                assert request_body is not None
                assert "async" in request_body

    async def test_async_response_payload_captured(self):
        """Verify async httpx response body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            async with self.httpx.AsyncClient() as client:
                resp = await client.get(URL_JSON)
                assert resp.status_code == 200
                # Application can still read response
                data = resp.json()
                assert isinstance(data, dict)

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                response_body = span.get_tag(HTTP_RESPONSE_BODY)
                assert response_body is not None


@pytest.mark.asyncio
class TestAiohttpPayloadCapture(TracerTestCase):
    """Test payload capture for aiohttp library"""

    def setUp(self):
        super(TestAiohttpPayloadCapture, self).setUp()
        try:
            import aiohttp
            from ddtrace.contrib.internal.aiohttp.patch import patch
            from ddtrace.contrib.internal.aiohttp.patch import unpatch

            unpatch()
            patch()
            self.aiohttp = aiohttp
        except ImportError:
            pytest.skip("aiohttp not installed")

    def tearDown(self):
        from ddtrace.contrib.internal.aiohttp.patch import unpatch

        unpatch()
        super(TestAiohttpPayloadCapture, self).tearDown()

    async def test_request_payload_captured(self):
        """Verify aiohttp request body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            async with self.aiohttp.ClientSession() as session:
                request_data = {"aiohttp": "test"}
                async with session.post(URL_POST, json=request_data) as resp:
                    assert resp.status == 200

                    spans = self.pop_spans()
                    assert len(spans) == 1
                    span = spans[0]

                    request_body = span.get_tag(HTTP_REQUEST_BODY)
                    assert request_body is not None
                    assert "aiohttp" in request_body

    async def test_response_payload_captured_via_wrapper(self):
        """Verify aiohttp response body is captured via _ResponseBodyCapturingWrapper"""
        with override_config("niq_tracer_payload_capture", True):
            async with self.aiohttp.ClientSession() as session:
                async with session.get(URL_JSON) as resp:
                    assert resp.status == 200
                    # Application reads response - wrapper should capture
                    data = await resp.json()
                    assert isinstance(data, dict)

                    spans = self.pop_spans()
                    assert len(spans) == 1
                    span = spans[0]

                    # Response body should be captured by wrapper
                    response_body = span.get_tag(HTTP_RESPONSE_BODY)
                    assert response_body is not None

    async def test_response_can_be_read_multiple_times(self):
        """Verify aiohttp response can be read multiple times with wrapper"""
        with override_config("niq_tracer_payload_capture", True):
            async with self.aiohttp.ClientSession() as session:
                async with session.get(URL_JSON) as resp:
                    # First read
                    data1 = await resp.read()
                    assert len(data1) > 0

                    # Second read should return cached data
                    data2 = await resp.read()
                    assert data1 == data2

    async def test_aiohttp_disabled_no_capture(self):
        """Verify aiohttp does NOT capture when disabled"""
        with override_config("niq_tracer_payload_capture", False):
            async with self.aiohttp.ClientSession() as session:
                async with session.post(URL_POST, json={"test": "data"}) as resp:
                    assert resp.status == 200

                    spans = self.pop_spans()
                    assert len(spans) == 1
                    span = spans[0]

                    request_body = span.get_tag(HTTP_REQUEST_BODY)
                    assert request_body is None
                    response_body = span.get_tag(HTTP_RESPONSE_BODY)
                    assert response_body is None


class TestUrllib3PayloadCapture(TracerTestCase):
    """Test payload capture for urllib3 library"""

    def setUp(self):
        super(TestUrllib3PayloadCapture, self).setUp()
        try:
            import urllib3
            from ddtrace.contrib.internal.urllib3.patch import patch
            from ddtrace.contrib.internal.urllib3.patch import unpatch

            unpatch()
            patch()
            self.urllib3 = urllib3
            self.http = urllib3.PoolManager()
        except ImportError:
            pytest.skip("urllib3 not installed")

    def tearDown(self):
        from ddtrace.contrib.internal.urllib3.patch import unpatch

        unpatch()
        super(TestUrllib3PayloadCapture, self).tearDown()

    def test_request_payload_captured(self):
        """Verify urllib3 request body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            body_data = json.dumps({"urllib3": "test"}).encode("utf-8")
            resp = self.http.request("POST", URL_POST, body=body_data, headers={"Content-Type": "application/json"})
            assert resp.status == 200

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            request_body = span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is not None
            assert "urllib3" in request_body

    def test_response_payload_captured(self):
        """Verify urllib3 response body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            resp = self.http.request("GET", URL_JSON)
            assert resp.status == 200
            # Application can still read response
            data = json.loads(resp.data.decode("utf-8"))
            assert isinstance(data, dict)

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            response_body = span.get_tag(HTTP_RESPONSE_BODY)
            assert response_body is not None


class TestHttplibPayloadCapture(TracerTestCase):
    """Test payload capture for http.client (httplib) standard library"""

    def setUp(self):
        super(TestHttplibPayloadCapture, self).setUp()
        try:
            from http.client import HTTPConnection

            from ddtrace.contrib.internal.httplib.patch import patch
            from ddtrace.contrib.internal.httplib.patch import unpatch

            unpatch()
            patch()
            self.HTTPConnection = HTTPConnection
        except ImportError:
            pytest.skip("http.client not available")

    def tearDown(self):
        from ddtrace.contrib.internal.httplib.patch import unpatch

        unpatch()
        super(TestHttplibPayloadCapture, self).tearDown()

    def test_request_payload_captured(self):
        """Verify http.client request body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            conn = self.HTTPConnection(HOST_AND_PORT)
            body_data = json.dumps({"httplib": "test"})
            conn.request("POST", "/post", body=body_data, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()  # Consume response
            conn.close()

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            request_body = span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is not None
            assert "httplib" in request_body

    def test_response_payload_captured(self):
        """Verify http.client response body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            conn = self.HTTPConnection(HOST_AND_PORT)
            conn.request("GET", "/json")
            resp = conn.getresponse()
            assert resp.status == 200
            # Application reads response
            data = json.loads(resp.read().decode("utf-8"))
            assert isinstance(data, dict)
            conn.close()

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            response_body = span.get_tag(HTTP_RESPONSE_BODY)
            assert response_body is not None


class TestPayloadCaptureEdgeCases(TracerTestCase):
    """Test edge cases for payload capture across all frameworks"""

    def setUp(self):
        super(TestPayloadCaptureEdgeCases, self).setUp()
        import requests
        from ddtrace.contrib.internal.requests.patch import patch

        patch()
        self.requests = requests
        self.session = requests.Session()
        self.session.datadog_tracer = self.tracer

    def tearDown(self):
        from ddtrace.contrib.internal.requests.patch import unpatch

        unpatch()
        super(TestPayloadCaptureEdgeCases, self).tearDown()

    def test_empty_payload(self):
        """Verify empty payloads are handled gracefully"""
        with override_config("niq_tracer_payload_capture", True):
            resp = self.session.post(URL_POST, data="")
            assert resp.status_code == 200

            spans = self.pop_spans()
            assert len(spans) == 1
            # Should not crash, may or may not have body tag

    def test_binary_payload(self):
        """Verify binary payloads are captured correctly"""
        with override_config("niq_tracer_payload_capture", True):
            binary_data = b"\x00\x01\x02\xff\xfe"
            resp = self.session.post(URL_POST, data=binary_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            # Binary data should be captured (may be encoded)
            request_body = span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is not None

    def test_large_json_payload(self):
        """Verify large JSON payloads are truncated"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_max_payload_size", 100):
                large_json = {"data": "x" * 10000}
                resp = self.session.post(URL_POST, json=large_json)
                assert resp.status_code == 200

                spans = self.pop_spans()
                assert len(spans) == 1
                span = spans[0]

                request_body = span.get_tag(HTTP_REQUEST_BODY)
                assert request_body is not None
                # Should be truncated
                assert len(request_body) < 1000

    def test_unicode_payload(self):
        """Verify Unicode payloads are captured correctly"""
        with override_config("niq_tracer_payload_capture", True):
            unicode_data = {"message": "Hello 世界 🌍"}
            resp = self.session.post(URL_POST, json=unicode_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            assert len(spans) == 1
            span = spans[0]

            request_body = span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is not None
            # Unicode should be preserved or safely encoded
            assert "Hello" in request_body
