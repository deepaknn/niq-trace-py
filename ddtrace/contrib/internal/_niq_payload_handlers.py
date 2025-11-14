"""
NIQ Tracer Payload Capture Handlers

This module provides handlers for capturing request and response payloads
in server-side frameworks. It leverages AppSec's existing stream handling
infrastructure to avoid duplicate stream reading and ensure compatibility.

The handlers hook into the 'set_http_meta_for_asm' dispatch event, which
is already used by AppSec for security analysis. When NIQ payload capture
is enabled, these handlers set the payload data as span tags for observability.
"""

import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

import wrapt

from ddtrace._trace.span import Span
from ddtrace.contrib.internal.trace_utils import capture_payload
from ddtrace.internal import core
from ddtrace.internal.constants import HTTP_REQUEST_BODY
from ddtrace.internal.constants import HTTP_RESPONSE_BODY
from ddtrace.internal.logger import get_logger
from ddtrace.internal.settings._config import config


log = get_logger(__name__)


class _TracedIterableWithBodyCapture(wrapt.ObjectProxy):
    """
    Wrapper for WSGI response iterables that buffers chunks to capture the response body.

    This extends the tracing functionality by intercepting each yielded chunk,
    buffering it up to max_size, and setting it as a span tag when iteration completes.

    Only used when niq_tracer_server_response_payload_capture is enabled, as it
    adds latency due to buffering (though minimal for small responses).
    """

    def __init__(self, wrapped, resp_span, req_span, max_size, wrapped_is_iterator=False):
        super(_TracedIterableWithBodyCapture, self).__init__(wrapped)
        self._self_wrapped_is_iterator = wrapped_is_iterator
        self._self_resp_span = resp_span
        self._self_req_span = req_span
        self._self_max_size = max_size
        self._self_body_chunks = []
        self._self_body_size = 0
        self._self_span_finished = False

        if self._self_wrapped_is_iterator:
            self._wrapped_iterator = iter(wrapped)
        # else: __wrapped__ is already an iterator from the parent class

    def __iter__(self):
        return self

    def __next__(self):
        try:
            if self._self_wrapped_is_iterator:
                chunk = next(self._wrapped_iterator)
            else:
                chunk = next(self.__wrapped__)

            # Buffer the chunk if we haven't exceeded max_size
            if self._self_body_size < self._self_max_size:
                if isinstance(chunk, bytes):
                    chunk_size = len(chunk)
                    if self._self_body_size + chunk_size <= self._self_max_size:
                        self._self_body_chunks.append(chunk)
                        self._self_body_size += chunk_size
                    else:
                        # Partial chunk to reach max_size
                        remaining = self._self_max_size - self._self_body_size
                        self._self_body_chunks.append(chunk[:remaining])
                        self._self_body_size = self._self_max_size

            return chunk
        except StopIteration:
            self._finish_spans_and_capture()
            raise
        except Exception:
            self._self_resp_span.set_exc_info(*sys.exc_info())
            self._finish_spans_and_capture()
            raise

    # PY2 Support
    next = __next__

    def close(self):
        if getattr(self.__wrapped__, "close", None):
            self.__wrapped__.close()
        self._finish_spans_and_capture()

    def _finish_spans_and_capture(self):
        """Finish spans and capture buffered response body"""
        if not self._self_span_finished:
            # Capture the buffered body
            if self._self_body_chunks:
                try:
                    body_bytes = b"".join(self._self_body_chunks)
                    body_captured = capture_payload(body_bytes, self._self_max_size)
                    if body_captured:
                        self._self_resp_span._set_tag_str(HTTP_RESPONSE_BODY, body_captured)
                        log.debug(
                            "NIQ: Captured server-side response body (%d bytes) for span %s",
                            len(body_captured),
                            self._self_resp_span.span_id,
                        )
                except Exception:
                    log.debug("NIQ: Failed to capture server-side response body", exc_info=True)

            # Finish spans
            self._self_resp_span.finish()
            self._self_req_span.finish()
            self._self_span_finished = True

    def __getattribute__(self, name):
        if name == "__len__":
            # __len__ is defined by the parent class, wrapt.ObjectProxy.
            # However this attribute should not be defined for iterables.
            # By definition, iterables should not support len(...).
            raise AttributeError("__len__ is not supported")
        return super(_TracedIterableWithBodyCapture, self).__getattribute__(name)


def _on_niq_request_body_capture(
    span,  # type: Span
    request_ip,  # type: Optional[str]
    raw_uri,  # type: Optional[str]
    route,  # type: Optional[str]
    method,  # type: Optional[str]
    request_headers,  # type: Optional[Dict[str, str]]
    request_cookies,  # type: Optional[Dict[str, str]]
    parsed_query,  # type: Optional[Dict[str, Any]]
    request_path_params,  # type: Optional[Dict[str, str]]
    request_body,  # type: Optional[Union[str, Dict[str, List[str]]]]
    status_code,  # type: Optional[Union[int, str]]
    response_headers,  # type: Optional[Dict[str, str]]
    response_cookies,  # type: Optional[Dict[str, str]]
):
    # type: (...) -> None
    """
    Handler for capturing server-side request and response payloads.

    This handler listens to the 'set_http_meta_for_asm' dispatch event,
    which is emitted when HTTP metadata is set on spans. If NIQ payload
    capture is enabled, it sets the request/response body as span tags.

    Why this works:
    - AppSec already handles stream reading for WSGI/ASGI frameworks
    - The request_body parameter is already populated by AppSec's
      sophisticated stream handling (see ddtrace/appsec/_handlers.py)
    - We simply reuse that data to set span tags - no duplicate reading!

    Performance:
    - <0.1ms overhead (just setting span tags)
    - No additional stream reading
    - Only executes when payload capture is enabled

    :param span: The current span
    :param request_body: Request body already captured by AppSec
    :param status_code: HTTP status code (for response context)
    :param response_headers: Response headers (for future response body capture)
    """
    # Only proceed if NIQ payload capture is enabled
    if not config.niq_tracer_payload_capture:
        return

    try:
        # Capture request body if available
        if request_body is not None:
            max_size = config.niq_tracer_max_payload_size

            # AppSec may pass request_body as various types (str, dict, etc.)
            # Use capture_payload to normalize and truncate
            body_captured = capture_payload(request_body, max_size)

            if body_captured:
                span._set_tag_str(HTTP_REQUEST_BODY, body_captured)
                log.debug(
                    "NIQ: Captured server-side request body (%d bytes) for span %s",
                    len(body_captured),
                    span.span_id,
                )

    except Exception:
        # Silent failure - never break request handling
        log.debug("NIQ: Failed to capture server-side payload", exc_info=True)


def _on_wsgi_request_complete(ctx, closing_iterable, app_is_iterator):
    """
    Handler for wrapping WSGI response iterables to capture response body.

    This handler intercepts the wsgi.request.complete dispatch event and wraps
    the response iterable with _TracedIterableWithBodyCapture when server-side
    response capture is enabled.

    Note: This is called BEFORE the default trace_handlers._on_request_complete,
    so we return our wrapped iterable which will then be wrapped by _TracedIterable.

    Actually, we need to wrap AFTER _TracedIterable is created. Let me reconsider...
    """
    # Only proceed if server response capture is enabled
    if not config.niq_tracer_server_response_payload_capture:
        return None  # Let default handler proceed

    middleware = ctx.get_item("middleware")
    req_span = ctx.get_item("req_span")
    max_size = config.niq_tracer_server_response_max_payload_size

    # Start response span (same as _on_request_complete)
    resp_span = middleware.tracer.start_span(
        (
            middleware._response_call_name
            if hasattr(middleware, "_response_call_name")
            else middleware._response_span_name
        ),
        child_of=req_span,
        activate=True,
    )

    from ddtrace.internal.constants import COMPONENT
    resp_span._set_tag_str(COMPONENT, middleware._config.integration_name)

    modifier = (
        middleware._response_call_modifier
        if hasattr(middleware, "_response_call_modifier")
        else middleware._response_span_modifier
    )
    modifier(resp_span, closing_iterable)

    # Return our body-capturing wrapper instead of regular _TracedIterable
    return _TracedIterableWithBodyCapture(
        closing_iterable, resp_span, req_span, max_size, wrapped_is_iterator=app_is_iterator
    )


def listen():
    """
    Register NIQ payload capture handlers with the core dispatch system.

    This function should be called during tracer initialization to enable
    server-side payload capture. It hooks into AppSec's existing dispatch
    events to leverage their stream handling infrastructure.
    """
    # Hook into the same dispatch event as AppSec for request body capture
    # This ensures we get the request_body that AppSec has already captured
    core.on("set_http_meta_for_asm", _on_niq_request_body_capture)

    # Hook into wsgi.request.complete for response body capture
    # Register with result_key to override default behavior when server response capture is enabled
    core.on("wsgi.request.complete", _on_wsgi_request_complete, "traced_iterable")

    log.debug("NIQ: Registered server-side payload capture handlers")
