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
daemon.proxy
~~~~~~~~~~~~~~~~~

Synchronous reverse proxy with host-based routing and round-robin balancing.
"""

import logging
import re
import socket
import threading
from urllib.parse import urlparse

LOGGER = logging.getLogger(__name__)
BUFFER_SIZE = 4096
BACKEND_TIMEOUT = 10

_ROUND_ROBIN_INDEX = {}
_ROUND_ROBIN_LOCK = threading.Lock()


def _http_response(status_code, reason, body):
    body_bytes = body.encode("utf-8")
    header = (
        "HTTP/1.1 {} {}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(status_code, reason, len(body_bytes))
    return header.encode("iso-8859-1") + body_bytes


def bad_request(message="400 Bad Request"):
    return _http_response(400, "Bad Request", message)


def not_found(message="404 Not Found"):
    return _http_response(404, "Not Found", message)


def bad_gateway(message="502 Bad Gateway"):
    return _http_response(502, "Bad Gateway", message)


def parse_proxy_config(config_file):
    """
    Parse config/proxy.conf style host blocks.

    Supported directives:
    - host "name" { ... }
    - proxy_pass http://host:port;
    - dist_policy round-robin
    """
    with open(config_file, "r", encoding="utf-8") as file_obj:
        config_text = file_obj.read()

    routes = {}
    host_blocks = re.findall(
        r'host\s+"([^"]+)"\s*\{(.*?)\}',
        config_text,
        re.DOTALL,
    )

    for hostname, block in host_blocks:
        backends = []
        for raw_backend in re.findall(r"proxy_pass\s+([^;\s]+)\s*;", block):
            parsed = urlparse(raw_backend)
            if parsed.scheme and parsed.scheme != "http":
                LOGGER.warning(
                    "Skipping unsupported proxy_pass scheme for %s: %s",
                    hostname,
                    raw_backend,
                )
                continue

            if parsed.scheme:
                backend_host = parsed.hostname
                backend_port = parsed.port
            else:
                backend_host, backend_port = _split_host_port(raw_backend)

            if not backend_host or not backend_port:
                LOGGER.warning(
                    "Skipping invalid proxy_pass for %s: %s",
                    hostname,
                    raw_backend,
                )
                continue
            backends.append((backend_host, int(backend_port)))

        policy_match = re.search(r"dist_policy\s+([\w-]+)", block)
        policy = policy_match.group(1) if policy_match else "round-robin"
        routes[hostname.lower()] = {
            "backends": backends,
            "policy": policy,
        }

    return routes


def _split_host_port(value):
    if ":" not in value:
        return value, None
    host, port = value.rsplit(":", 1)
    try:
        return host, int(port)
    except ValueError:
        return host, None


def _read_http_message(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk

    if not data:
        raise ValueError("empty request")

    header_bytes, separator, body = data.partition(b"\r\n\r\n")
    if not separator:
        raise ValueError("missing HTTP header terminator")

    content_length = _content_length_from_headers(header_bytes)
    while len(body) < content_length:
        chunk = conn.recv(BUFFER_SIZE)
        if not chunk:
            break
        body += chunk

    return header_bytes + b"\r\n\r\n" + body


def _content_length_from_headers(header_bytes):
    header_text = header_bytes.decode("iso-8859-1", errors="replace")
    for line in header_text.split("\r\n")[1:]:
        if line.lower().startswith("content-length:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                raise ValueError("invalid Content-Length")
    return 0


def _extract_host(request_bytes):
    header_text = request_bytes.split(b"\r\n\r\n", 1)[0].decode(
        "iso-8859-1",
        errors="replace",
    )
    request_line = header_text.split("\r\n", 1)[0]
    if len(request_line.split()) != 3:
        raise ValueError("malformed request line")

    for line in header_text.split("\r\n")[1:]:
        if line.lower().startswith("host:"):
            return line.split(":", 1)[1].strip().lower()
    raise ValueError("missing Host header")


def _extract_response_status(response_bytes):
    try:
        status_line = response_bytes.split(b"\r\n", 1)[0].decode("iso-8859-1")
    except UnicodeDecodeError:
        return "unknown"
    parts = status_line.split()
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


def resolve_routing_policy(hostname, routes):
    """
    Resolve a Host header to a backend using the configured policy.

    Returns ``(backend_host, backend_port)`` or ``(None, None)``.
    """
    route = routes.get(hostname)
    if not route and ":" in hostname:
        route = routes.get(hostname.rsplit(":", 1)[0])

    if not route:
        return None, None

    backends = route.get("backends", [])
    policy = route.get("policy", "round-robin")
    if not backends:
        return None, None

    if len(backends) == 1:
        return backends[0]

    if policy != "round-robin":
        LOGGER.warning(
            "Unsupported policy %s for %s; falling back to round-robin",
            policy,
            hostname,
        )

    with _ROUND_ROBIN_LOCK:
        index = _ROUND_ROBIN_INDEX.get(hostname, 0)
        backend = backends[index % len(backends)]
        _ROUND_ROBIN_INDEX[hostname] = index + 1
    return backend


def forward_request(host, port, request):
    """
    Forward raw HTTP request bytes to a backend and return raw response bytes.
    """
    if isinstance(request, str):
        request = request.encode("iso-8859-1")

    try:
        with socket.create_connection(
            (host, port),
            timeout=BACKEND_TIMEOUT,
        ) as backend:
            backend.sendall(request)
            response = b""
            while True:
                chunk = backend.recv(BUFFER_SIZE)
                if not chunk:
                    break
                response += chunk
            if not response:
                return bad_gateway("502 Bad Gateway: empty backend response")
            return response
    except socket.timeout:
        LOGGER.exception("Backend timeout %s:%s", host, port)
        return bad_gateway("502 Bad Gateway: backend timeout")
    except OSError:
        LOGGER.exception("Backend unavailable %s:%s", host, port)
        return bad_gateway("502 Bad Gateway: backend unavailable")


def handle_client(ip, port, conn, addr, routes):
    """
    Handle one proxy client connection.
    """
    try:
        request = _read_http_message(conn)
        hostname = _extract_host(request)
        LOGGER.info("Incoming request from %s host=%s", addr, hostname)

        resolved_host, resolved_port = resolve_routing_policy(hostname, routes)
        if not resolved_host:
            LOGGER.warning("No proxy route for host=%s", hostname)
            response = not_found("404 Not Found: invalid proxy route")
        else:
            LOGGER.info(
                "Selected backend for host=%s -> %s:%s",
                hostname,
                resolved_host,
                resolved_port,
            )
            response = forward_request(resolved_host, resolved_port, request)

        status = _extract_response_status(response)
        LOGGER.info("Forwarded response status=%s host=%s", status, hostname)
        conn.sendall(response)
    except ValueError as exc:
        LOGGER.warning("Malformed proxy request from %s: %s", addr, exc)
        conn.sendall(bad_request("400 Bad Request: {}".format(exc)))
    except OSError:
        LOGGER.exception("Proxy socket error while serving %s", addr)
    finally:
        conn.close()


def run_proxy(ip, port, routes):
    """
    Start the synchronous reverse proxy server.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(levelname)s] %(name)s: %(message)s",
        )

    proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        proxy.bind((ip, port))
        proxy.listen(50)
        LOGGER.info("Proxy listening on %s:%s", ip, port)
        LOGGER.info("Proxy routes=%s", routes)

        while True:
            conn, addr = proxy.accept()
            client_thread = threading.Thread(
                target=handle_client,
                args=(ip, port, conn, addr, routes),
            )
            client_thread.daemon = True
            client_thread.start()
    except OSError:
        LOGGER.exception("Proxy socket error")
    finally:
        proxy.close()


def create_proxy(ip, port, routes):
    """
    Entry point for launching the proxy server.
    """
    run_proxy(ip, port, routes or {})
