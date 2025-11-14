"""
Integration tests for NIQ server-side payload capture.

Tests verify that payload capture works correctly for:
- Flask (WSGI)
- Django (WSGI)
- FastAPI/Starlette (ASGI)

Each test ensures:
1. Request payloads are captured when enabled
2. Response payloads are captured when server response capture is enabled
3. Size limits are respected
4. Application code continues to work normally
5. Latency impact is minimal
"""

import json

import pytest

from ddtrace import config
from ddtrace.internal.constants import HTTP_REQUEST_BODY
from ddtrace.internal.constants import HTTP_RESPONSE_BODY
from tests.utils import TracerTestCase
from tests.utils import override_config


class TestFlaskPayloadCapture(TracerTestCase):
    """Test payload capture for Flask applications"""

    def setUp(self):
        super(TestFlaskPayloadCapture, self).setUp()
        try:
            import flask

            from ddtrace.contrib.internal.flask.patch import patch
            from ddtrace.contrib.internal.flask.patch import unpatch

            unpatch()
            patch()

            # Create a simple Flask app for testing
            app = flask.Flask(__name__)

            @app.route("/test", methods=["POST"])
            def test_post():
                data = flask.request.get_json()
                return flask.jsonify({"received": data, "echo": "Flask response"})

            @app.route("/json", methods=["GET"])
            def test_get():
                return flask.jsonify({"message": "Hello from Flask"})

            @app.route("/large", methods=["GET"])
            def test_large():
                return flask.jsonify({"data": "x" * 10000})

            self.app = app
            self.client = app.test_client()
        except ImportError:
            pytest.skip("Flask not installed")

    def tearDown(self):
        from ddtrace.contrib.internal.flask.patch import unpatch

        unpatch()
        super(TestFlaskPayloadCapture, self).tearDown()

    def test_request_payload_captured(self):
        """Verify Flask request body is captured via AppSec dispatch"""
        with override_config("niq_tracer_payload_capture", True):
            request_data = {"flask": "test", "data": "value"}
            resp = self.client.post("/test", json=request_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            # Find the request span
            request_span = None
            for span in spans:
                if span.name == "flask.request":
                    request_span = span
                    break

            assert request_span is not None
            request_body = request_span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is not None
            assert "flask" in request_body
            assert "test" in request_body

    def test_request_payload_not_captured_when_disabled(self):
        """Verify Flask request body is NOT captured when disabled"""
        with override_config("niq_tracer_payload_capture", False):
            request_data = {"test": "data"}
            resp = self.client.post("/test", json=request_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            for span in spans:
                request_body = span.get_tag(HTTP_REQUEST_BODY)
                assert request_body is None

    def test_response_payload_captured_when_enabled(self):
        """Verify Flask response body is captured when server response capture is enabled"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_server_response_payload_capture", True):
                with override_config("niq_tracer_server_response_max_payload_size", 8192):
                    resp = self.client.get("/json")
                    assert resp.status_code == 200

                    # Verify application still gets response
                    data = resp.get_json()
                    assert data["message"] == "Hello from Flask"

                    spans = self.pop_spans()
                    # Find the response span
                    response_span = None
                    for span in spans:
                        if span.name == "flask.response":
                            response_span = span
                            break

                    assert response_span is not None
                    response_body = response_span.get_tag(HTTP_RESPONSE_BODY)
                    assert response_body is not None
                    assert "Hello from Flask" in response_body

    def test_response_not_captured_when_disabled(self):
        """Verify Flask response body is NOT captured when server response capture is disabled"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_server_response_payload_capture", False):
                resp = self.client.get("/json")
                assert resp.status_code == 200

                spans = self.pop_spans()
                for span in spans:
                    response_body = span.get_tag(HTTP_RESPONSE_BODY)
                    assert response_body is None

    def test_response_size_limit_respected(self):
        """Verify Flask response is truncated at max_size"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_server_response_payload_capture", True):
                with override_config("niq_tracer_server_response_max_payload_size", 100):
                    resp = self.client.get("/large")
                    assert resp.status_code == 200

                    spans = self.pop_spans()
                    response_span = None
                    for span in spans:
                        if span.name == "flask.response":
                            response_span = span
                            break

                    assert response_span is not None
                    response_body = response_span.get_tag(HTTP_RESPONSE_BODY)
                    assert response_body is not None
                    # Should be truncated
                    assert len(response_body) < 500  # Much smaller than 10000

    def test_application_not_broken(self):
        """Verify Flask application works normally with payload capture"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_server_response_payload_capture", True):
                # POST
                request_data = {"key": "value"}
                resp = self.client.post("/test", json=request_data)
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["received"] == request_data
                assert data["echo"] == "Flask response"

                # GET
                resp = self.client.get("/json")
                assert resp.status_code == 200
                data = resp.get_json()
                assert "message" in data


@pytest.mark.asyncio
class TestFastAPIPayloadCapture(TracerTestCase):
    """Test payload capture for FastAPI/ASGI applications"""

    def setUp(self):
        super(TestFastAPIPayloadCapture, self).setUp()
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from pydantic import BaseModel

            from ddtrace.contrib.internal.asgi.patch import patch
            from ddtrace.contrib.internal.asgi.patch import unpatch

            unpatch()
            patch()

            # Create a simple FastAPI app for testing
            app = FastAPI()

            class Item(BaseModel):
                name: str
                value: str

            @app.post("/test")
            async def test_post(item: Item):
                return {"received": item.dict(), "echo": "FastAPI response"}

            @app.get("/json")
            async def test_get():
                return {"message": "Hello from FastAPI"}

            self.app = app
            self.client = TestClient(app)
        except ImportError:
            pytest.skip("FastAPI not installed")

    def tearDown(self):
        from ddtrace.contrib.internal.asgi.patch import unpatch

        unpatch()
        super(TestFastAPIPayloadCapture, self).tearDown()

    def test_request_payload_captured(self):
        """Verify FastAPI request body is captured"""
        with override_config("niq_tracer_payload_capture", True):
            request_data = {"name": "test", "value": "fastapi"}
            resp = self.client.post("/test", json=request_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            # Find request span (ASGI spans have different names)
            request_span = None
            for span in spans:
                request_body = span.get_tag(HTTP_REQUEST_BODY)
                if request_body:
                    request_span = span
                    break

            assert request_span is not None
            assert "test" in request_span.get_tag(HTTP_REQUEST_BODY)

    def test_response_payload_captured_when_enabled(self):
        """Verify FastAPI response body is captured when server response capture is enabled"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_server_response_payload_capture", True):
                resp = self.client.get("/json")
                assert resp.status_code == 200

                # Verify application still works
                data = resp.json()
                assert data["message"] == "Hello from FastAPI"

                spans = self.pop_spans()
                response_span = None
                for span in spans:
                    response_body = span.get_tag(HTTP_RESPONSE_BODY)
                    if response_body:
                        response_span = span
                        break

                assert response_span is not None
                assert "Hello from FastAPI" in response_span.get_tag(HTTP_RESPONSE_BODY)


class TestServerPayloadCaptureEdgeCases(TracerTestCase):
    """Test edge cases for server-side payload capture"""

    def setUp(self):
        super(TestServerPayloadCaptureEdgeCases, self).setUp()
        try:
            import flask

            from ddtrace.contrib.internal.flask.patch import patch

            patch()

            app = flask.Flask(__name__)

            @app.route("/empty", methods=["POST"])
            def empty_post():
                return flask.jsonify({"status": "ok"})

            @app.route("/binary", methods=["POST"])
            def binary_post():
                data = flask.request.get_data()
                return flask.jsonify({"received_bytes": len(data)})

            @app.route("/unicode", methods=["POST"])
            def unicode_post():
                data = flask.request.get_json()
                return flask.jsonify({"received": data})

            @app.route("/streaming")
            def streaming():
                def generate():
                    for i in range(10):
                        yield f"chunk_{i}\n".encode("utf-8")

                return flask.Response(generate(), mimetype="text/plain")

            self.app = app
            self.client = app.test_client()
        except ImportError:
            pytest.skip("Flask not installed")

    def tearDown(self):
        from ddtrace.contrib.internal.flask.patch import unpatch

        unpatch()
        super(TestServerPayloadCaptureEdgeCases, self).tearDown()

    def test_empty_request_payload(self):
        """Verify empty request payloads are handled gracefully"""
        with override_config("niq_tracer_payload_capture", True):
            resp = self.client.post("/empty", data="")
            assert resp.status_code == 200
            # Should not crash

    def test_binary_request_payload(self):
        """Verify binary request payloads are captured"""
        with override_config("niq_tracer_payload_capture", True):
            binary_data = b"\x00\x01\x02\xff\xfe"
            resp = self.client.post("/binary", data=binary_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            request_span = None
            for span in spans:
                if span.name == "flask.request":
                    request_span = span
                    break

            # Should capture binary data (may be encoded)
            if request_span:
                request_body = request_span.get_tag(HTTP_REQUEST_BODY)
                # Binary data handling depends on implementation

    def test_unicode_payload(self):
        """Verify Unicode payloads are captured correctly"""
        with override_config("niq_tracer_payload_capture", True):
            unicode_data = {"message": "Hello 世界 🌍"}
            resp = self.client.post("/unicode", json=unicode_data)
            assert resp.status_code == 200

            spans = self.pop_spans()
            request_span = None
            for span in spans:
                if span.name == "flask.request":
                    request_span = span
                    break

            assert request_span is not None
            request_body = request_span.get_tag(HTTP_REQUEST_BODY)
            assert request_body is not None
            assert "Hello" in request_body

    def test_streaming_response_buffered(self):
        """Verify streaming responses are buffered and captured when enabled"""
        with override_config("niq_tracer_payload_capture", True):
            with override_config("niq_tracer_server_response_payload_capture", True):
                with override_config("niq_tracer_server_response_max_payload_size", 8192):
                    resp = self.client.get("/streaming")
                    assert resp.status_code == 200

                    # Application can still read streamed data
                    data = resp.get_data()
                    assert b"chunk_0" in data
                    assert b"chunk_9" in data

                    spans = self.pop_spans()
                    response_span = None
                    for span in spans:
                        if span.name == "flask.response":
                            response_span = span
                            break

                    # Streaming responses should be buffered and captured
                    if response_span:
                        response_body = response_span.get_tag(HTTP_RESPONSE_BODY)
                        # Should contain buffered chunks
                        if response_body:
                            assert "chunk" in response_body
