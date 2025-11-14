"""
Tests for NIQ custom trace header injection (niqtid and current-span-id).

This module tests:
1. Client-side niqtid header injection (request propagation)
2. Server-side current-span-id header injection (response propagation)
3. Integration with various server frameworks
"""
import mock

from ddtrace.propagation.http import HTTPPropagator


class TestNiqTidClientSideInjection:
    """Tests for niqtid header injection on client-side (outgoing requests)."""

    def test_niqtid_header_injected_with_parent_id(self, tracer):
        """Test that niqtid header is injected with correct W3C format including parent_id."""
        tracer.configure(writer=mock.MagicMock())

        with tracer.trace("test_span") as span:
            # Set up trace IDs in W3C format
            span.context._trace_id = 0x0AF7651916CD43DD8448EB211C80319C
            span._span_id = 0xB7AD6B7169203331
            span.context.parent_id = 0xA1B2C3D4E5F60708

            headers = {}
            HTTPPropagator.inject(span.context, headers)

            # Verify niqtid header exists
            assert "niqtid" in headers

            # Verify format: {trace-id-32hex}-{span-id-16hex}-{parent-id-16hex}~niqtid
            niqtid_value = headers["niqtid"]
            assert niqtid_value.endswith("~niqtid")

            # Parse the value
            value_without_suffix = niqtid_value[:-7]  # Remove ~niqtid
            parts = value_without_suffix.split("-")
            assert len(parts) == 3

            trace_id_hex, span_id_hex, parent_id_hex = parts

            # Verify W3C format: 32 hex for trace, 16 hex for span and parent
            assert len(trace_id_hex) == 32
            assert len(span_id_hex) == 16
            assert len(parent_id_hex) == 16

            # Verify actual values
            assert trace_id_hex == "0af7651916cd43dd8448eb211c80319c"
            assert span_id_hex == "b7ad6b7169203331"
            assert parent_id_hex == "a1b2c3d4e5f60708"

    def test_niqtid_header_without_parent_id(self, tracer):
        """Test that niqtid header uses zero-padded parent_id when parent is None."""
        tracer.configure(writer=mock.MagicMock())

        with tracer.trace("test_span") as span:
            span.context._trace_id = 0x8448EB211C80319C  # 64-bit trace ID
            span._span_id = 0xB7AD6B7169203331
            span.context.parent_id = None

            headers = {}
            HTTPPropagator.inject(span.context, headers)

            niqtid_value = headers["niqtid"]
            parts = niqtid_value[:-7].split("-")

            # parent_id should be all zeros when None
            assert parts[2] == "0000000000000000"

            # trace_id should be zero-padded to 32 hex chars
            assert len(parts[0]) == 32
            assert parts[0] == "00000000000000008448eb211c80319c"

    def test_niqtid_extraction_and_roundtrip(self, tracer):
        """Test that niqtid header can be extracted and roundtripped."""
        tracer.configure(writer=mock.MagicMock())

        # Inject first
        with tracer.trace("span1") as span1:
            span1.context._trace_id = 0x0AF7651916CD43DD8448EB211C80319C
            span1._span_id = 0xB7AD6B7169203331
            span1.context.parent_id = 0xA1B2C3D4E5F60708

            headers = {}
            HTTPPropagator.inject(span1.context, headers)

        # Extract
        context = HTTPPropagator.extract(headers)

        # Verify parent_id was extracted from niqtid
        assert context.parent_id == 0xA1B2C3D4E5F60708
        assert context.trace_id == 0x0AF7651916CD43DD8448EB211C80319C
        assert context.span_id == 0xB7AD6B7169203331


class TestCurrentSpanIdServerSideInjection:
    """Tests for current-span-id header injection on server-side (outgoing responses)."""

    def test_inject_server_response_headers_basic(self, tracer):
        """Test basic current-span-id injection."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())
        with tracer.trace("test_span") as span:
            span.context._trace_id = 0x0AF7651916CD43DD8448EB211C80319C
            span._span_id = 0xB7AD6B7169203331

            response_headers = {}
            inject_server_response_headers(span, response_headers)

            # Verify header exists
            assert "current-span-id" in response_headers

            # Verify format: 00-{trace-id-32hex}-{span-id-16hex}-01~ncsd
            header_value = response_headers["current-span-id"]
            assert header_value.startswith("00-")
            assert header_value.endswith("-01~ncsd")

            # Parse value
            value_without_prefix = header_value[3:]  # Remove 00-
            value_without_suffix = value_without_prefix[:-7]  # Remove -01~ncsd
            parts = value_without_suffix.split("-")

            assert len(parts) == 2
            trace_id_hex, span_id_hex = parts

            # Verify W3C format
            assert len(trace_id_hex) == 32
            assert len(span_id_hex) == 16

            # Verify values
            assert trace_id_hex == "0af7651916cd43dd8448eb211c80319c"
            assert span_id_hex == "b7ad6b7169203331"

    def test_inject_server_response_headers_64bit_trace_id(self, tracer):
        """Test that 64-bit trace IDs are zero-padded to 32 hex chars."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())
        with tracer.trace("test_span") as span:
            span.context._trace_id = 0x8448EB211C80319C  # 64-bit
            span._span_id = 0xB7AD6B7169203331

            response_headers = {}
            inject_server_response_headers(span, response_headers)

            header_value = response_headers["current-span-id"]
            trace_id_hex = header_value[3:35]  # Extract trace ID part

            # Should be zero-padded
            assert len(trace_id_hex) == 32
            assert trace_id_hex == "00000000000000008448eb211c80319c"

    def test_inject_server_response_headers_handles_none_span(self):
        """Test that injection handles None span gracefully."""
        from ddtrace.propagation.http import inject_server_response_headers

        response_headers = {}
        inject_server_response_headers(None, response_headers)

        # Should not inject header
        assert "current-span-id" not in response_headers

    def test_inject_server_response_headers_handles_invalid_span(self, tracer):
        """Test that injection handles invalid span data gracefully."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())
        with tracer.trace("test_span") as span:
            # Remove context to simulate error condition
            span.context = None

            response_headers = {}
            # Should not raise, just log warning
            inject_server_response_headers(span, response_headers)

            # Should not inject header
            assert "current-span-id" not in response_headers

    def test_inject_server_response_headers_error_handling(self, tracer):
        """Test that errors during injection are logged but don't crash."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())
        with tracer.trace("test_span") as span:
            # Use a response_headers object that will fail on assignment
            class FailingDict(dict):
                def __setitem__(self, key, value):
                    raise RuntimeError("Simulated failure")

            response_headers = FailingDict()

            # Should not raise, just log warning
            inject_server_response_headers(span, response_headers)

            # Verify header is not present (due to failure)
            assert "current-span-id" not in response_headers


class TestW3CFormatCompliance:
    """Tests to ensure W3C/OTel format compliance for both headers."""

    def test_niqtid_w3c_format_always_32_hex_trace_id(self, tracer):
        """Test that niqtid always uses 32 hex chars for trace_id."""
        tracer.configure(writer=mock.MagicMock())

        # Test with various trace ID sizes
        test_cases = [
            0x01,  # Very small
            0x1234567890ABCDEF,  # 64-bit
            0x0AF7651916CD43DD8448EB211C80319C,  # 128-bit
        ]

        for trace_id in test_cases:
            with tracer.trace("test") as span:
                span.context._trace_id = trace_id
                span._span_id = 0xB7AD6B7169203331

                headers = {}
                HTTPPropagator.inject(span.context, headers)

                niqtid_value = headers["niqtid"]
                trace_id_hex = niqtid_value.split("-")[0]

                # Must always be 32 hex chars
                assert len(trace_id_hex) == 32
                assert all(c in "0123456789abcdef" for c in trace_id_hex)

    def test_current_span_id_w3c_traceparent_like_format(self, tracer):
        """Test that current-span-id follows W3C traceparent-like format."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())
        with tracer.trace("test") as span:
            response_headers = {}
            inject_server_response_headers(span, response_headers)

            header_value = response_headers["current-span-id"]

            # Format should be: 00-{32hex}-{16hex}-01~ncsd
            # Similar to W3C traceparent: version-trace_id-span_id-flags
            parts = header_value.split("-")
            assert len(parts) == 4

            version, trace_id, span_id, flags_suffix = parts

            # Verify version
            assert version == "00"

            # Verify trace_id is 32 hex chars
            assert len(trace_id) == 32
            assert all(c in "0123456789abcdef" for c in trace_id)

            # Verify span_id is 16 hex chars
            assert len(span_id) == 16
            assert all(c in "0123456789abcdef" for c in span_id)

            # Verify flags with suffix
            assert flags_suffix == "01~ncsd"


class TestEndToEndHeaderPropagation:
    """End-to-end tests for both request and response header propagation."""

    def test_complete_trace_propagation_cycle(self, tracer):
        """Test complete cycle: niqtid in request -> current-span-id in response."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())

        # Simulate incoming request with niqtid header
        incoming_headers = {"niqtid": "0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-a1b2c3d4e5f60708~niqtid"}

        # Extract context from incoming request
        context = HTTPPropagator.extract(incoming_headers)

        # Verify parent_id was extracted
        assert context.parent_id == 0xA1B2C3D4E5F60708

        # Create a new span with the extracted context
        with tracer.trace("server_span", child_of=context) as span:
            # The new span should have the extracted trace_id
            assert span.trace_id == context.trace_id

            # Inject current-span-id into response
            response_headers = {}
            inject_server_response_headers(span, response_headers)

            # Verify response header contains the current span info
            assert "current-span-id" in response_headers

            # Response should contain same trace_id but new span_id
            header_value = response_headers["current-span-id"]
            trace_id_from_response = header_value[3:35]  # Extract trace ID

            # Trace ID should match
            expected_trace_id = "{:032x}".format(span.trace_id)
            assert trace_id_from_response == expected_trace_id

    def test_both_headers_can_coexist(self, tracer):
        """Test that both niqtid and current-span-id can exist in same context."""
        from ddtrace.propagation.http import inject_server_response_headers

        tracer.configure(writer=mock.MagicMock())

        with tracer.trace("test_span") as span:
            span.context._trace_id = 0x0AF7651916CD43DD8448EB211C80319C
            span._span_id = 0xB7AD6B7169203331
            span.context.parent_id = 0xA1B2C3D4E5F60708

            # Inject both request headers (niqtid)
            request_headers = {}
            HTTPPropagator.inject(span.context, request_headers)

            # Inject response headers (current-span-id)
            response_headers = {}
            inject_server_response_headers(span, response_headers)

            # Both headers should exist
            assert "niqtid" in request_headers
            assert "current-span-id" in response_headers

            # Both should contain the same trace_id
            niqtid_trace_id = request_headers["niqtid"].split("-")[0]
            current_span_trace_id = response_headers["current-span-id"][3:35]

            assert niqtid_trace_id == current_span_trace_id
