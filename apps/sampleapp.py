#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
app.sampleapp
~~~~~~~~~~~~~~~~~

Sample REST app with Phase 3 cookie-based session authentication.
Phase 5 adds a lightweight in-memory tracker for peer discovery.
"""

import asyncio
import json
import secrets
import time
from urllib.parse import parse_qs

from daemon import AsynapRous

app = AsynapRous()

SESSION_COOKIE = "session_id"
SESSION_TTL_SECONDS = 3600

USERS = {
    "alice": {
        "password": "wonderland",
        "role": "user",
    },
    "admin": {
        "password": "admin123",
        "role": "admin",
    },
}

SESSIONS = {}
PEER_TTL_SECONDS = 300
ACTIVE_PEER_STATUSES = {"online", "away", "busy"}
PEERS = {}


def json_response(body, status=200, headers=None):
    return {
        "status": status,
        "headers": headers or {},
        "body": body,
        "content_type": "application/json; charset=utf-8",
    }


def parse_body(body, headers):
    content_type = headers.get("Content-Type", "")
    if not body:
        return {}
    if "application/json" in content_type:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def parse_channels(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def peer_key(username, peer_ip, peer_port):
    return "{}@{}:{}".format(username, peer_ip, peer_port)


def cleanup_inactive_peers(now=None):
    now = now or time.time()
    inactive = [
        key
        for key, peer in PEERS.items()
        if now - peer["last_seen"] > PEER_TTL_SECONDS
        or peer.get("status") == "offline"
    ]
    for key in inactive:
        PEERS.pop(key, None)
    return len(inactive)


def peer_to_public(peer):
    return {
        "username": peer["username"],
        "peer_ip": peer["peer_ip"],
        "peer_port": peer["peer_port"],
        "status": peer["status"],
        "channels": peer["channels"],
        "last_seen": int(peer["last_seen"]),
    }


def peer_list(channel=None, include_inactive=False):
    cleanup_inactive_peers()
    peers = []
    for peer in PEERS.values():
        if not include_inactive and peer["status"] not in ACTIVE_PEER_STATUSES:
            continue
        if channel and channel not in peer["channels"]:
            continue
        peers.append(peer_to_public(peer))
    return sorted(
        peers,
        key=lambda item: (item["username"], item["peer_ip"], item["peer_port"]),
    )


def register_peer(data, request):
    username = data.get("username", "").strip()
    peer_addr = getattr(request, "connaddr", ("", 0))
    peer_ip = data.get("peer_ip") or data.get("ip") or peer_addr[0]
    peer_ip = str(peer_ip).strip()
    peer_port = data.get("peer_port") or data.get("port")
    status = data.get("status", "online").strip() or "online"
    channels = parse_channels(data.get("channels") or data.get("channel"))

    if not username or not peer_ip or not peer_port:
        return None, json_response(
            {
                "error": "Bad Request",
                "message": "username, peer_ip and peer_port are required",
            },
            status=400,
        )

    try:
        peer_port = int(peer_port)
    except (TypeError, ValueError):
        return None, json_response(
            {"error": "Bad Request", "message": "peer_port must be integer"},
            status=400,
        )

    if status not in ("online", "away", "busy", "offline"):
        return None, json_response(
            {"error": "Bad Request", "message": "invalid peer status"},
            status=400,
        )

    key = peer_key(username, peer_ip, peer_port)
    now = time.time()
    existing = key in PEERS
    PEERS[key] = {
        "username": username,
        "peer_ip": peer_ip,
        "peer_port": peer_port,
        "status": status,
        "channels": channels,
        "last_seen": now,
    }
    return existing, None


def create_session(username):
    session_id = secrets.token_urlsafe(32)
    SESSIONS[session_id] = {
        "username": username,
        "role": USERS[username]["role"],
        "created_at": time.time(),
    }
    return session_id


def get_session(request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None

    session = SESSIONS.get(session_id)
    if not session:
        return None

    if time.time() - session["created_at"] > SESSION_TTL_SECONDS:
        SESSIONS.pop(session_id, None)
        return None

    return session


def require_user(request):
    session = get_session(request)
    if not session:
        return None, json_response(
            {"error": "Unauthorized", "message": "Login required"},
            status=401,
        )
    return session, None


def require_role(request, role):
    session, error = require_user(request)
    if error:
        return None, error
    if session["role"] != role:
        return None, json_response(
            {"error": "Forbidden", "message": "Insufficient permission"},
            status=403,
        )
    return session, None


def session_cookie(session_id):
    return (
        "{}={}; Path=/; Max-Age={}; HttpOnly; SameSite=Lax".format(
            SESSION_COOKIE,
            session_id,
            SESSION_TTL_SECONDS,
        )
    )


def expired_session_cookie():
    return (
        "{}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax".format(
            SESSION_COOKIE
        )
    )


@app.route("/login", methods=["POST", "PUT"])
def login(headers, body, request):
    data = parse_body(body, headers)
    username = data.get("username", "")
    password = data.get("password", "")
    user = USERS.get(username)

    if not user or user["password"] != password:
        return json_response(
            {"error": "Unauthorized", "message": "Invalid credentials"},
            status=401,
        )

    session_id = create_session(username)
    return json_response(
        {
            "message": "Login successful",
            "username": username,
            "role": user["role"],
        },
        headers={"Set-Cookie": session_cookie(session_id)},
    )


@app.route("/logout", methods=["POST", "PUT"])
def logout(headers, body, request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        SESSIONS.pop(session_id, None)

    return json_response(
        {"message": "Logout successful"},
        headers={"Set-Cookie": expired_session_cookie()},
    )


@app.route("/private", methods=["GET"])
def private(headers, body, request):
    session, error = require_user(request)
    if error:
        return error
    return json_response(
        {
            "message": "Private route access granted",
            "username": session["username"],
            "role": session["role"],
        }
    )


@app.route("/admin", methods=["GET"])
def admin(headers, body, request):
    session, error = require_role(request, "admin")
    if error:
        return error
    return json_response(
        {
            "message": "Admin route access granted",
            "username": session["username"],
        }
    )


@app.route("/submit-info", methods=["POST", "PUT"])
def submit_info(headers, body, request):
    data = parse_body(body, headers)
    existing, error = register_peer(data, request)
    if error:
        return error

    removed = cleanup_inactive_peers()
    return json_response(
        {
            "message": "Peer updated" if existing else "Peer registered",
            "duplicate": existing,
            "removed_inactive": removed,
            "peers": peer_list(),
        }
    )


@app.route("/get-list", methods=["GET", "POST"])
def get_list(headers, body, request):
    data = parse_body(body, headers)
    query_channel = request.query_params.get("channel", [""])[0]
    channel = data.get("channel") or query_channel or None
    include_inactive = (
        data.get("include_inactive") == "true"
        or request.query_params.get("include_inactive", ["false"])[0] == "true"
    )
    removed = cleanup_inactive_peers()
    peers = peer_list(channel=channel, include_inactive=include_inactive)
    return json_response(
        {
            "count": len(peers),
            "removed_inactive": removed,
            "channel": channel,
            "peers": peers,
        }
    )


@app.route("/add-list", methods=["POST", "PUT", "DELETE"])
def add_list(headers, body, request):
    data = parse_body(body, headers)
    if request.method == "DELETE" or data.get("status") == "offline":
        username = data.get("username", "").strip()
        peer_ip = str(data.get("peer_ip") or data.get("ip") or "").strip()
        peer_port = data.get("peer_port") or data.get("port")
        try:
            peer_port = int(peer_port)
        except (TypeError, ValueError):
            return json_response(
                {
                    "error": "Bad Request",
                    "message": "valid peer_port is required",
                },
                status=400,
            )
        key = peer_key(username, peer_ip, peer_port)
        removed = PEERS.pop(key, None) is not None
        return json_response(
            {
                "message": "Peer removed" if removed else "Peer not found",
                "removed": removed,
                "peers": peer_list(),
            }
        )

    existing, error = register_peer(data, request)
    if error:
        return error

    return json_response(
        {
            "message": "Peer updated" if existing else "Peer added",
            "duplicate": existing,
            "peers": peer_list(),
        }
    )


@app.route("/echo", methods=["POST"])
def echo(headers="guest", body="anonymous"):
    try:
        message = json.loads(body)
        return json_response({"received": message})
    except json.JSONDecodeError:
        return json_response({"error": "Invalid JSON"}, status=400)


@app.route("/hello", methods=["POST"])
def hello(headers, body):
    data = {"id": 1, "name": "Alice", "email": "alice@example.com"}
    return json_response(data)


@app.route("/async-hello", methods=["GET"])
async def async_hello(headers, body, request):
    await asyncio.sleep(0.01)
    return json_response({"message": "Hello from async route"})


def create_sampleapp(ip, port):
    app.prepare_address(ip, port)
    app.run()
