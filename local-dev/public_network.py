"""Preflight preview destinations; fetches still use pinned, redirect-aware IO."""

import socket
from urllib.parse import urlsplit

from backend.services.safe_outbound_http_service import (
    SafeOutboundHttpError, _address_is_public, _validated_url,
)


def validate_destination(value):
    url = _validated_url(value)
    parsed = urlsplit(url)
    try:
        records = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                     family=socket.AF_UNSPEC, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise SafeOutboundHttpError(502, "The outbound hostname could not be resolved") from None
    if not records or any(not _address_is_public(record[4][0]) for record in records):
        raise SafeOutboundHttpError(403, "The outbound destination is not public")
    return url
