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

HTTP adapter for parsing requests, dispatching routes and writing responses.
Phase 4 adds asyncio StreamReader/StreamWriter support while keeping the
synchronous handler available for compatibility.
"""

import asyncio
import inspect
import logging

from .request import Request
from .response import Response

LOGGER = logging.getLogger(__name__)


class HttpAdapter:
    """Manage one client connection and route it to the correct handler."""

    SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE"}
    BUFFER_SIZE = 4096
    READ_TIMEOUT = 15
    MAX_BODY_BYTES = 1024 * 1024

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
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    LOGGER.warning("Invalid Content-Length header: %s", line)
                    return 0
                if content_length > self.MAX_BODY_BYTES:
                    raise ValueError("request body too large")
                return content_length
        return 0

    def _request_error_response(self, resp, exc):
        if str(exc) == "request body too large":
            return resp.build_error(413, "413 Payload Too Large")
        return resp.build_error(400, "400 Bad Request")

    def _dispatch_route(self, req, resp):
        if req.method not in self.SUPPORTED_METHODS:
            LOGGER.warning("Unsupported method %s for %s", req.method, req.path)
            return resp.build_error(405, "405 Method Not Allowed")

        if not req.hook:
            if req.method == "GET":
                return resp.build_response(req)
            LOGGER.info("No route for method=%s path=%s", req.method, req.path)
            return resp.build_notfound()

        LOGGER.info("Dispatching route method=%s path=%s", req.method, req.path)
        result = self._call_route(req)
        if inspect.isawaitable(result):
            raise RuntimeError("Async route requires async backend mode")
        return resp.build_response(req, envelop_content=result)

    async def _dispatch_route_async(self, req, resp):
        if req.method not in self.SUPPORTED_METHODS:
            LOGGER.warning("Unsupported method %s for %s", req.method, req.path)
            return resp.build_error(405, "405 Method Not Allowed")

        if not req.hook:
            if req.method == "GET":
                return await asyncio.to_thread(resp.build_response, req)
            LOGGER.info("No route for method=%s path=%s", req.method, req.path)
            return resp.build_notfound()

        LOGGER.info(
            "Async dispatch route method=%s path=%s",
            req.method,
            req.path,
        )
        result = await self._call_route_async(req)
        return resp.build_response(req, envelop_content=result)

    def _call_route(self, req):
        """Call route handlers while preserving the Phase 1 two-arg API."""
        return req.hook(*self._route_arguments(req))

    async def _call_route_async(self, req):
        """Call sync or async route handlers from the asyncio backend."""
        args = self._route_arguments(req)
        if inspect.iscoroutinefunction(req.hook):
            return await req.hook(*args)

        result = await asyncio.to_thread(req.hook, *args)
        if inspect.isawaitable(result):
            return await result
        return result

    def _route_arguments(self, req):
        signature = inspect.signature(req.hook)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if len(positional) >= 3:
            return req.headers, req.body, req
        return req.headers, req.body

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
            req.connaddr = addr
            response = self._dispatch_route(req, resp)
        except ValueError as exc:
            LOGGER.warning("Bad request from %s: %s", addr, exc)
            response = self._request_error_response(resp, exc)
        except Exception:
            LOGGER.exception("Unhandled error while serving %s", addr)
            response = resp.build_error(500, "500 Internal Server Error")

        try:
            conn.sendall(response)
        except OSError:
            LOGGER.warning("Client disconnected before response was sent: %s", addr)
        try:
            conn.shutdown(2)
        except OSError:
            pass
        conn.close()
        LOGGER.info("Closed connection from %s", addr)

    async def handle_client_coroutine(self, reader, writer):
        """Read, route and respond to one asyncio client connection."""
        addr = writer.get_extra_info("peername")
        req = Request()
        resp = Response()
        LOGGER.info("Async accepted connection from %s", addr)

        try:
            msg = await asyncio.wait_for(
                self._read_http_message_async(reader),
                timeout=self.READ_TIMEOUT,
            )
            req.prepare(msg, self.routes)
            req.connaddr = addr
            response = await self._dispatch_route_async(req, resp)
        except asyncio.TimeoutError:
            LOGGER.warning("Async request timeout from %s", addr)
            response = resp.build_error(408, "408 Request Timeout")
        except ValueError as exc:
            LOGGER.warning("Bad async request from %s: %s", addr, exc)
            response = self._request_error_response(resp, exc)
        except Exception:
            LOGGER.exception("Unhandled async error while serving %s", addr)
            response = resp.build_error(500, "500 Internal Server Error")

        try:
            writer.write(response)
            await writer.drain()
        except (ConnectionError, OSError):
            LOGGER.warning("Async client disconnected before response: %s", addr)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            LOGGER.debug("Socket already closed for %s", addr)
        LOGGER.info("Async closed connection from %s", addr)

    async def _read_http_message_async(self, reader):
        """Read a full HTTP message without blocking the event loop."""
        try:
            header_bytes = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                return exc.partial.decode("iso-8859-1", errors="replace")
            raise ValueError("empty request")
        except asyncio.LimitOverrunError as exc:
            raise ValueError("headers too large") from exc

        header_text = header_bytes.decode("iso-8859-1", errors="replace")
        content_length = self._content_length_from_headers(header_text)
        body = b""
        if content_length:
            try:
                body = await reader.readexactly(content_length)
            except asyncio.IncompleteReadError as exc:
                raise ValueError("incomplete request body") from exc

        return (
            header_bytes.rstrip(b"\r\n")
            + b"\r\n\r\n"
            + body
        ).decode("utf-8", errors="replace")

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
