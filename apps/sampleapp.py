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

"""Provide the HTTP authentication server and peer discovery tracker.

The tracker deliberately does not forward chat messages.  It authenticates
users, stores short-lived peer presence records, and lets real peer processes
discover each other before opening direct TCP sockets.
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
PEER_TTL_SECONDS = 300
ACTIVE_PEER_STATUSES = {"online", "away", "busy"}

USERS = {
    "alice": {"password": "wonderland", "role": "user"},
    "bob": {"password": "wonderland", "role": "user"},
    "charlie": {"password": "wonderland", "role": "user"},
    "admin": {"password": "admin123", "role": "admin"},
}

SESSIONS = {}
PEERS = {}
CHAT_CHANNELS = {"general": {"name": "general", "members": set()}}


def json_response(body, status=200, headers=None):
    """Return a route result encoded as JSON by the framework."""
    return {
        "status": status,
        "headers": headers or {},
        "body": body,
        "content_type": "application/json; charset=utf-8",
    }


def error_response(message, status=400, error="Bad Request"):
    """Return a JSON error response."""
    return json_response(
        {"error": error, "message": message},
        status=status,
    )


def parse_body(body, headers):
    """Parse JSON or form-encoded route bodies into a dictionary."""
    if not body:
        return {}

    content_type = headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def parse_channels(value):
    """Return a normalized list of channel names."""
    if value is None:
        return ["general"]
    if isinstance(value, list):
        channels = [str(item).strip() for item in value if str(item).strip()]
    else:
        channels = [item.strip() for item in str(value).split(",") if item.strip()]
    return channels or ["general"]


def create_session(username):
    """Create and store a signed-looking random session token."""
    session_id = secrets.token_urlsafe(32)
    SESSIONS[session_id] = {
        "username": username,
        "role": USERS[username]["role"],
        "created_at": time.time(),
    }
    return session_id


def get_session(request):
    """Return the active session for a request cookie."""
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
    """Return the logged-in user session or an unauthorized response."""
    session = get_session(request)
    if not session:
        return None, error_response(
            "Login required",
            status=401,
            error="Unauthorized",
        )
    return session, None


def require_role(request, role):
    """Return the logged-in session if it has the required role."""
    session, error = require_user(request)
    if error:
        return None, error
    if session["role"] != role:
        return None, error_response(
            "Insufficient permission",
            status=403,
            error="Forbidden",
        )
    return session, None


def session_cookie(session_id):
    """Return the Set-Cookie header value for a login session."""
    return "{}={}; Path=/; Max-Age={}; HttpOnly; SameSite=Lax".format(
        SESSION_COOKIE,
        session_id,
        SESSION_TTL_SECONDS,
    )


def expired_session_cookie():
    """Return the Set-Cookie header value that clears the session."""
    return "{}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax".format(
        SESSION_COOKIE
    )


def peer_key(username, peer_ip, peer_port):
    """Return the in-memory key for one peer endpoint."""
    return "{}@{}:{}".format(username, peer_ip, int(peer_port))


def cleanup_inactive_peers(now=None):
    """Remove inactive or offline peer records from memory."""
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
    """Return the public tracker representation of a peer."""
    return {
        "username": peer["username"],
        "peer_ip": peer["peer_ip"],
        "peer_port": peer["peer_port"],
        "status": peer["status"],
        "channels": list(peer["channels"]),
        "last_seen": int(peer["last_seen"]),
    }


def peer_list(channel=None, include_inactive=False):
    """Return the active peer list."""
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


def channel_list():
    """Return known tracker channel names."""
    return sorted(CHAT_CHANNELS)


def tracker_state_payload(session):
    """Return tracker-only dashboard state for the browser UI."""
    return {
        "user": {
            "username": session["username"],
            "role": session["role"],
        },
        "peers": peer_list(),
        "channels": channel_list(),
        "note": (
            "Tracker only handles discovery. Direct chat runs in peer.py."
        ),
    }


def register_peer(data, request, session):
    """Register or refresh the peer owned by the logged-in user."""
    peer_addr = getattr(request, "connaddr", ("", 0))
    peer_ip = str(data.get("peer_ip") or data.get("ip") or peer_addr[0]).strip()
    peer_port = data.get("peer_port") or data.get("port")
    status = str(data.get("status", "online")).strip() or "online"
    channels = parse_channels(data.get("channels") or data.get("channel"))
    username = session["username"]

    if not peer_ip or not peer_port:
        return None, error_response("peer_ip and peer_port are required")

    try:
        peer_port = int(peer_port)
    except (TypeError, ValueError):
        return None, error_response("peer_port must be integer")

    if status not in ("online", "away", "busy", "offline"):
        return None, error_response("invalid peer status")

    key = peer_key(username, peer_ip, peer_port)
    existing = key in PEERS
    PEERS[key] = {
        "username": username,
        "peer_ip": peer_ip,
        "peer_port": peer_port,
        "status": status,
        "channels": channels,
        "last_seen": time.time(),
    }
    for channel in channels:
        CHAT_CHANNELS.setdefault(channel, {"name": channel, "members": set()})
        CHAT_CHANNELS[channel]["members"].add(username)
    return existing, None


@app.route("/login", methods=["POST"])
def login(headers, body, request):
    """Authenticate a user and set the session cookie."""
    data = parse_body(body, headers)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user = USERS.get(username)

    if not user or user["password"] != password:
        return error_response(
            "Invalid credentials",
            status=401,
            error="Unauthorized",
        )

    session_id = create_session(username)
    return json_response(
        {"username": username, "role": user["role"]},
        headers={"Set-Cookie": session_cookie(session_id)},
    )


@app.route("/logout", methods=["POST"])
def logout(headers, body, request):
    """Remove the current session and clear the cookie."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        SESSIONS.pop(session_id, None)
    return json_response(
        {"message": "Logout successful"},
        headers={"Set-Cookie": expired_session_cookie()},
    )


@app.route("/me", methods=["GET"])
def me(headers, body, request):
    """Return the logged-in user represented by the session cookie."""
    session, error = require_user(request)
    if error:
        return error
    return json_response(
        {"username": session["username"], "role": session["role"]}
    )


@app.route("/private", methods=["GET"])
def private(headers, body, request):
    """Return a protected user-only response."""
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
    """Return a protected admin-only response."""
    session, error = require_role(request, "admin")
    if error:
        return error
    return json_response(
        {
            "message": "Admin route access granted",
            "username": session["username"],
        }
    )


@app.route("/submit-info", methods=["POST"])
def submit_info(headers, body, request):
    """Register or update the current user's peer endpoint."""
    session, error = require_user(request)
    if error:
        return error

    data = parse_body(body, headers)
    existing, error = register_peer(data, request, session)
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


@app.route("/get-list", methods=["GET"])
def get_list(headers, body, request):
    """Return peers visible to the logged-in user."""
    session, error = require_user(request)
    if error:
        return error

    channel = request.query_params.get("channel", [""])[0] or None
    include_inactive = (
        request.query_params.get("include_inactive", ["false"])[0].lower()
        == "true"
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


@app.route("/heartbeat", methods=["POST"])
def heartbeat(headers, body, request):
    """Refresh last_seen for the logged-in peer."""
    session, error = require_user(request)
    if error:
        return error

    data = parse_body(body, headers)
    peer_ip = data.get("peer_ip") or data.get("ip")
    peer_port = data.get("peer_port") or data.get("port")
    if peer_port:
        try:
            peer_port = int(peer_port)
        except (TypeError, ValueError):
            return error_response("peer_port must be integer")

    refreshed = 0
    for peer in PEERS.values():
        if peer["username"] != session["username"]:
            continue
        if peer_ip and peer["peer_ip"] != str(peer_ip):
            continue
        if peer_port and peer["peer_port"] != peer_port:
            continue
        peer["last_seen"] = time.time()
        peer["status"] = data.get("status", peer["status"])
        refreshed += 1

    if refreshed == 0:
        return error_response("peer is not registered", status=404, error="Not Found")
    return json_response({"refreshed": refreshed, "peers": peer_list()})


@app.route("/leave", methods=["POST", "DELETE"])
def leave(headers, body, request):
    """Mark the logged-in user's peer endpoint offline."""
    session, error = require_user(request)
    if error:
        return error

    data = parse_body(body, headers)
    peer_ip = data.get("peer_ip") or data.get("ip")
    peer_port = data.get("peer_port") or data.get("port")
    if peer_port:
        try:
            peer_port = int(peer_port)
        except (TypeError, ValueError):
            return error_response("peer_port must be integer")

    changed = 0

    for peer in PEERS.values():
        if peer["username"] != session["username"]:
            continue
        if peer_ip and peer["peer_ip"] != str(peer_ip):
            continue
        if peer_port and peer["peer_port"] != peer_port:
            continue
        peer["status"] = "offline"
        peer["last_seen"] = time.time()
        changed += 1

    cleanup_inactive_peers()
    return json_response({"left": changed, "peers": peer_list()})


@app.route("/add-list", methods=["POST", "DELETE"])
def add_list(headers, body, request):
    """Compatibility alias for peer registration and leave operations."""
    if request.method == "DELETE":
        return leave(headers, body, request)
    return submit_info(headers, body, request)


def legacy_peer_response():
    """Return a deprecation notice for server-global peer endpoints."""
    return json_response(
        {
            "error": "Deprecated",
            "message": (
                "Direct chat is implemented by peer.py. The tracker does not "
                "forward peer messages."
            ),
        },
        status=410,
    )


@app.route("/connect-peer", methods=["POST"])
def connect_peer(headers, body, request):
    """Reject legacy server-global P2P connection attempts."""
    return legacy_peer_response()


@app.route("/send-peer", methods=["POST"])
def send_peer(headers, body, request):
    """Reject legacy server-forwarded peer sends."""
    return legacy_peer_response()


@app.route("/broadcast-peer", methods=["POST"])
def broadcast_peer(headers, body, request):
    """Reject legacy server-forwarded peer broadcasts."""
    return legacy_peer_response()


@app.route("/peer-inbox", methods=["GET"])
def peer_inbox(headers, body, request):
    """Explain that peer inboxes live in peer.py processes."""
    return legacy_peer_response()


@app.route("/tracker-state", methods=["GET"])
def tracker_state(headers, body, request):
    """Return authenticated tracker state for the browser dashboard."""
    session, error = require_user(request)
    if error:
        return error
    return json_response(tracker_state_payload(session))


@app.route("/chat-state", methods=["GET"])
def chat_state(headers, body, request):
    """Return optional UI channel state without storing chat messages."""
    session, error = require_user(request)
    if error:
        return error
    return json_response(tracker_state_payload(session))


@app.route("/echo", methods=["POST"])
def echo(headers="guest", body="anonymous"):
    """Echo JSON payloads for simple framework testing."""
    try:
        message = json.loads(body)
    except json.JSONDecodeError:
        return error_response("Invalid JSON")
    return json_response({"received": message})


@app.route("/hello", methods=["POST"])
def hello(headers, body):
    """Return a small JSON hello payload."""
    data = {"id": 1, "name": "Alice", "email": "alice@example.com"}
    return json_response(data)


@app.route("/async-hello", methods=["GET"])
async def async_hello(headers, body, request):
    """Return a small async JSON hello payload."""
    await asyncio.sleep(0.01)
    return json_response({"message": "Hello from async route"})


def create_sampleapp(ip, port):
    """Run the sample tracker application."""
    app.prepare_address(ip, port)
    app.run()
