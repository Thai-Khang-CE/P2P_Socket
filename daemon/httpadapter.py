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
daemon.httpadapter
~~~~~~~~~~~~~~~~~

Synchronous HTTP adapter for parsing requests, dispatching routes and writing
HTTP responses.
"""

import inspect
import logging

from .request import Request
from .response import Response

LOGGER = logging.getLogger(__name__)


class HttpAdapter:
    """Manage one client connection and route it to the correct handler."""

    SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE"}
    BUFFER_SIZE = 4096

    def __init__(self, ip, port, conn, connaddr, routes):
        self.ip = ip
        self.port = port
        self.conn = conn
        self.connaddr = connaddr
        self.routes = routes or {}
        self.request = Request()
        self.response = Response()

    def _read_http_message(self, conn):
        """Read headers and body from a blocking socket."""
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(self.BUFFER_SIZE)
            if not chunk:
                break
            data += chunk

        header_bytes, separator, body = data.partition(b"\r\n\r\n")
        if not separator:
            return data.decode("iso-8859-1", errors="replace")

        header_text = header_bytes.decode("iso-8859-1", errors="replace")
        content_length = self._content_length_from_headers(header_text)
        while len(body) < content_length:
            chunk = conn.recv(self.BUFFER_SIZE)
            if not chunk:
                break
            body += chunk

        return (
            header_text
            + "\r\n\r\n"
            + body.decode("utf-8", errors="replace")
        )

    def _content_length_from_headers(self, header_text):
        for line in header_text.split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    LOGGER.warning("Invalid Content-Length header: %s", line)
                    return 0
        return 0

    def _dispatch_route(self, req, resp):
        if req.method not in self.SUPPORTED_METHODS:
            LOGGER.warning("Unsupported method %s for %s", req.method, req.path)
            return resp.build_error(405, "405 Method Not Allowed")

        if not req.hook:
            if req.method == "GET":
                return resp.build_response(req)
            LOGGER.info("No route for method=%s path=%s", req.method, req.path)
            return resp.build_notfound()

        if inspect.iscoroutinefunction(req.hook):
            LOGGER.warning("Async route registered in Phase 1: %s", req.path)
            return resp.build_error(
                500,
                "Async route handlers are not enabled in Phase 1",
            )

        LOGGER.info("Dispatching route method=%s path=%s", req.method, req.path)
        result = req.hook(req.headers, req.body)
        return resp.build_response(req, envelop_content=result)

    def handle_client(self, conn, addr, routes):
        """Read, route and respond to one synchronous HTTP client."""
        self.conn = conn
        self.connaddr = addr
        self.routes = routes or {}
        req = self.request
        resp = self.response

        LOGGER.info("Accepted connection from %s", addr)
        try:
            msg = self._read_http_message(conn)
            req.prepare(msg, self.routes)
            response = self._dispatch_route(req, resp)
        except ValueError as exc:
            LOGGER.warning("Bad request from %s: %s", addr, exc)
            response = resp.build_error(400, "400 Bad Request")
        except Exception:
            LOGGER.exception("Unhandled error while serving %s", addr)
            response = resp.build_error(500, "500 Internal Server Error")

        conn.sendall(response)
        conn.close()
        LOGGER.info("Closed connection from %s", addr)

    async def handle_client_coroutine(self, reader, writer):
        """Async mode is reserved for later assignment phases."""
        raise NotImplementedError("Async mode is not implemented in Phase 1")

    @property
    def extract_cookies(self):
        return self.request.cookies

    def add_headers(self, request):
        return

    def build_proxy_headers(self, proxy):
        headers = {}
        username, password = ("user1", "password")
        if username:
            headers["Proxy-Authorization"] = (username, password)
        return headers
