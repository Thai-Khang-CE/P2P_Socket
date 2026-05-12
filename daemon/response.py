#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynApRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.response
~~~~~~~~~~~~~~~~~

Build HTTP/1.1 responses for static files and route handler payloads.
"""

import datetime
import json
import logging
import mimetypes
import os

from .dictionary import CaseInsensitiveDict

LOGGER = logging.getLogger(__name__)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


class Response:
    """HTTP response builder used by the backend adapter."""

    STATUS_REASONS = {
        200: "OK",
        201: "Created",
        204: "No Content",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        500: "Internal Server Error",
    }

    STATIC_ROOTS = {
        "html": "www",
        "static": "static",
    }

    def __init__(self, request=None):
        self._content = b""
        self._header = b""
        self.status_code = 200
        self.headers = {}
        self.url = None
        self.encoding = "utf-8"
        self.history = []
        self.reason = self.STATUS_REASONS[200]
        self.cookies = CaseInsensitiveDict()
        self.elapsed = datetime.timedelta(0)
        self.request = request

    def get_mime_type(self, path):
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type or "application/octet-stream"

    def _http_date(self):
        return datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    def _normalise_static_path(self, request_path):
        path = "/index.html" if request_path == "/" else request_path
        path = path.split("?", 1)[0]
        if path.startswith("/css/") or path.startswith("/images/"):
            root = self.STATIC_ROOTS["static"]
        elif path == "/favicon.ico":
            root = os.path.join(self.STATIC_ROOTS["static"], "images")
        else:
            root = self.STATIC_ROOTS["html"]

        root_dir = os.path.abspath(os.path.join(BASE_DIR, root))
        file_path = os.path.abspath(
            os.path.normpath(os.path.join(root_dir, path.lstrip("/")))
        )
        if not file_path.startswith(root_dir):
            raise ValueError("path traversal blocked")
        return file_path

    def _format(self, status_code, content, headers=None):
        reason = self.STATUS_REASONS.get(status_code, "Unknown")
        content = content or b""
        if isinstance(content, str):
            content = content.encode("utf-8")

        response_headers = {
            "Date": self._http_date(),
            "Server": "AsynapRous/1.0",
            "Content-Length": str(len(content)),
            "Connection": "close",
        }
        response_headers.update(headers or {})

        status_line = "HTTP/1.1 {} {}\r\n".format(status_code, reason)
        header_lines = [
            "{}: {}\r\n".format(key, value)
            for key, value in response_headers.items()
        ]
        self.status_code = status_code
        self.reason = reason
        self.headers = response_headers
        self._content = content
        self._header = (status_line + "".join(header_lines) + "\r\n").encode(
            "iso-8859-1"
        )
        return self._header + self._content

    def build_json_response(self, data, status_code=200):
        if isinstance(data, bytes):
            content = data
        elif isinstance(data, str):
            content = data.encode("utf-8")
        else:
            content = json.dumps(data).encode("utf-8")
        return self._format(
            status_code,
            content,
            {"Content-Type": "application/json; charset=utf-8"},
        )

    def build_text_response(self, text, status_code=200):
        return self._format(
            status_code,
            text,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    def build_error(self, status_code, message=None):
        reason = self.STATUS_REASONS.get(status_code, "Error")
        body = message or reason
        return self._format(
            status_code,
            body,
            {"Content-Type": "text/plain; charset=utf-8"},
        )

    def build_notfound(self):
        return self.build_error(404, "404 Not Found")

    def build_content(self, path, base_dir=None):
        if os.path.isabs(path):
            filepath = path
        elif base_dir:
            filepath = os.path.abspath(os.path.join(base_dir, path.lstrip("/")))
        else:
            filepath = self._normalise_static_path(path)

        LOGGER.info("Serving static file %s", filepath)
        try:
            with open(filepath, "rb") as file_obj:
                content = file_obj.read()
        except FileNotFoundError:
            LOGGER.warning("Static file not found: %s", filepath)
            return -1, b""
        except OSError as exc:
            LOGGER.error("Could not read static file %s: %s", filepath, exc)
            return -1, b""
        return len(content), content

    def build_response_header(self, request):
        return self._header

    def build_response(self, request, envelop_content=None, status_code=200):
        if envelop_content is not None:
            return self.build_json_response(envelop_content, status_code)

        try:
            filepath = self._normalise_static_path(request.path)
        except ValueError:
            return self.build_error(403, "403 Forbidden")

        length, content = self.build_content(filepath, base_dir="")
        if length < 0:
            return self.build_notfound()

        mime_type = self.get_mime_type(filepath)
        if mime_type.startswith("text/"):
            mime_type = "{}; charset=utf-8".format(mime_type)

        LOGGER.info(
            "Built static response status=200 path=%s bytes=%s",
            request.path,
            length,
        )
        return self._format(200, content, {"Content-Type": mime_type})
