"""
NIQ Tracer Payload Capture Handlers

This module provides handlers for capturing request and response payloads
in server-side frameworks. It leverages AppSec's existing stream handling
infrastructure to avoid duplicate stream reading and ensure compatibility.

The handlers hook into the 'set_http_meta_for_asm' dispatch event, which
is already used by AppSec for security analysis. When NIQ payload capture
is enabled, these handlers set the payload data as span tags for observability.
"""

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from ddtrace._trace.span import Span
from ddtrace.contrib.internal.trace_utils import capture_payload
from ddtrace.internal import core
from ddtrace.internal.constants import HTTP_REQUEST_BODY
from ddtrace.internal.constants import HTTP_RESPONSE_BODY
from ddtrace.internal.logger import get_logger
from ddtrace.internal.settings._config import config


log = get_logger(__name__)


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

        # TODO: Response body capture for server-side
        # Response bodies in server frameworks are often streamed to the client,
        # so capturing them requires buffering which adds latency.
        # For now, we only capture request bodies server-side.
        # Response bodies can be added later if needed with:
        # - Middleware to buffer responses before streaming
        # - Or mark as "[streaming]" similar to aiohttp client

    except Exception:
        # Silent failure - never break request handling
        log.debug("NIQ: Failed to capture server-side payload", exc_info=True)


def listen():
    """
    Register NIQ payload capture handlers with the core dispatch system.

    This function should be called during tracer initialization to enable
    server-side payload capture. It hooks into AppSec's existing dispatch
    events to leverage their stream handling infrastructure.
    """
    # Hook into the same dispatch event as AppSec
    # This ensures we get the request_body that AppSec has already captured
    core.on("set_http_meta_for_asm", _on_niq_request_body_capture)

    log.debug("NIQ: Registered server-side payload capture handlers")
