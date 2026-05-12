#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.request
~~~~~~~~~~~~~~~~~

This module provides a Request object for parsing incoming HTTP messages.
"""

import logging
from http import cookies
from urllib.parse import parse_qs, urlsplit

from .dictionary import CaseInsensitiveDict

LOGGER = logging.getLogger(__name__)


class Request:
    """Mutable HTTP request parsed from raw client data."""

    __attrs__ = [
        "method",
        "url",
        "path",
        "version",
        "headers",
        "query_params",
        "body",
        "_raw_headers",
        "_raw_body",
        "cookies",
        "routes",
        "hook",
        "connaddr",
    ]

    def __init__(self):
        self.method = None
        self.url = None
        self.path = None
        self.version = None
        self.headers = CaseInsensitiveDict()
        self.query_params = {}
        self.cookies = {}
        self.body = ""
        self._raw_headers = ""
        self._raw_body = ""
        self.routes = {}
        self.hook = None
        self.connaddr = None

    def extract_request_line(self, header_text):
        """Parse the HTTP request line into method, URL target and version."""
        lines = header_text.splitlines()
        if not lines:
            raise ValueError("empty HTTP request")

        parts = lines[0].split()
        if len(parts) != 3:
            raise ValueError("malformed request line: {}".format(lines[0]))

        method, target, version = parts
        if not version.startswith("HTTP/"):
            raise ValueError("unsupported request version: {}".format(version))

        return method.upper(), target, version

    def prepare_headers(self, header_text):
        """Parse HTTP headers into a case-insensitive mapping."""
        headers = CaseInsensitiveDict()
        for line in header_text.split("\r\n")[1:]:
            if not line:
                continue
            if ":" not in line:
                LOGGER.warning("Skipping malformed header line: %s", line)
                continue
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
        return headers

    def fetch_headers_body(self, request):
        """Split raw HTTP text into headers and body sections."""
        parts = request.split("\r\n\r\n", 1)
        header_text = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        return header_text, body

    def prepare_cookies(self, cookie_header):
        """Parse Cookie header into a plain dictionary."""
        parsed = cookies.SimpleCookie()
        parsed.load(cookie_header or "")
        return {key: morsel.value for key, morsel in parsed.items()}

    def prepare_query_params(self, target):
        """Parse URL path and query string from the request target."""
        parsed = urlsplit(target)
        self.url = target
        self.path = parsed.path or "/"
        self.query_params = parse_qs(parsed.query, keep_blank_values=True)

    def prepare(self, request, routes=None):
        """Parse a complete HTTP request string."""
        routes = routes or {}
        self._raw_headers, self._raw_body = self.fetch_headers_body(request)
        self.body = self._raw_body
        self.method, target, self.version = self.extract_request_line(
            self._raw_headers
        )
        self.prepare_query_params(target)
        self.headers = self.prepare_headers(self._raw_headers)
        self.cookies = self.prepare_cookies(self.headers.get("Cookie", ""))
        self.routes = routes
        self.hook = routes.get((self.method, self.path))

        LOGGER.info(
            "Parsed request method=%s path=%s query=%s body_bytes=%s",
            self.method,
            self.path,
            self.query_params,
            len(self.body.encode("utf-8")),
        )
        return self

    def prepare_body(self, data, files=None, json=None):
        """Compatibility helper for callers that prepare outbound requests."""
        if json is not None:
            body = json
        elif data is not None:
            body = data
        else:
            body = ""
        self.body = body
        self.prepare_content_length(body)
        return

    def prepare_content_length(self, body):
        body_bytes = str(body).encode("utf-8") if body is not None else b""
        self.headers["Content-Length"] = str(len(body_bytes))
        return

    def prepare_auth(self, auth, url=""):
        return
