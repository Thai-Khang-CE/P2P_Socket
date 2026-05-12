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
CHAT_CHANNELS = {}
CHAT_NEXT_MESSAGE_ID = 1
DEFAULT_CHANNELS = ("general", "python", "random")


class PeerNode:
    """Async peer socket node controlled by REST endpoints."""

    def __init__(self):
        self.username = "anonymous"
        self.host = "127.0.0.1"
        self.port = None
        self.server = None
        self.connections = {}
        self.messages = []
        self.lock = asyncio.Lock()

    async def start_server(self, username=None, host="127.0.0.1", port=None):
        if username:
            self.username = username
        if not port:
            return {
                "listening": self.server is not None,
                "host": self.host,
                "port": self.port,
            }

        port = int(port)
        if self.server and self.host == host and self.port == port:
            return {
                "listening": True,
                "host": self.host,
                "port": self.port,
                "already_running": True,
            }

        if self.server:
            self.server.close()
            await self.server.wait_closed()

        self.host = host
        self.port = port
        self.server = await asyncio.start_server(
            self._handle_incoming_peer,
            host,
            port,
        )
        return {
            "listening": True,
            "host": self.host,
            "port": self.port,
            "already_running": False,
        }

    async def connect(self, username, host, port):
        port = int(port)
        key = self.connection_key(host, port)
        async with self.lock:
            connection = self.connections.get(key)
            if connection and not connection["writer"].is_closing():
                return {
                    "connected": True,
                    "duplicate": True,
                    "peer": key,
                }
            self.connections.pop(key, None)

        reader, writer = await asyncio.open_connection(host, port)
        connection = {
            "username": username,
            "host": host,
            "port": port,
            "reader": reader,
            "writer": writer,
            "direction": "outbound",
        }
        async with self.lock:
            self.connections[key] = connection
        await self._send_json(
            writer,
            {
                "type": "hello",
                "from": self.username,
                "listen_host": self.host,
                "listen_port": self.port,
                "timestamp": time.time(),
            },
        )
        asyncio.create_task(self._read_peer_messages(key, reader))
        return {
            "connected": True,
            "duplicate": False,
            "peer": key,
        }

    async def send_message(self, username, host, port, message):
        port = int(port)
        key = self.connection_key(host, port)
        connection = await self._ensure_connection(username, host, port)
        payload = {
            "type": "message",
            "from": self.username,
            "to": username,
            "message": message,
            "timestamp": time.time(),
        }

        try:
            await self._send_json(connection["writer"], payload)
        except (ConnectionError, OSError):
            await self._drop_connection(key)
            connection = await self._ensure_connection(username, host, port)
            await self._send_json(connection["writer"], payload)

        return {
            "sent": True,
            "peer": key,
        }

    async def broadcast(self, peers, message):
        async def send_one(peer):
            username = peer.get("username", "")
            host = peer.get("peer_ip") or peer.get("host") or peer.get("ip")
            port = peer.get("peer_port") or peer.get("port")
            if not username or not host or not port:
                return {
                    "sent": False,
                    "error": "invalid peer",
                    "peer": peer,
                }
            try:
                return await self.send_message(username, host, port, message)
            except (ConnectionError, OSError) as exc:
                return {
                    "sent": False,
                    "error": str(exc),
                    "peer": self.connection_key(host, port),
                }

        results = await asyncio.gather(*(send_one(peer) for peer in peers))
        return results

    async def _ensure_connection(self, username, host, port):
        key = self.connection_key(host, port)
        async with self.lock:
            connection = self.connections.get(key)
            if connection and not connection["writer"].is_closing():
                return connection
        await self.connect(username, host, port)
        async with self.lock:
            return self.connections[key]

    async def _handle_incoming_peer(self, reader, writer):
        addr = writer.get_extra_info("peername")
        key = self.connection_key(addr[0], addr[1])
        connection = {
            "username": None,
            "host": addr[0],
            "port": addr[1],
            "reader": reader,
            "writer": writer,
            "direction": "inbound",
        }
        async with self.lock:
            self.connections[key] = connection
        await self._read_peer_messages(key, reader)

    async def _read_peer_messages(self, key, reader):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                await self._handle_protocol_message(key, payload)
        finally:
            await self._drop_connection(key)

    async def _handle_protocol_message(self, key, payload):
        message_type = payload.get("type")
        if message_type == "hello":
            listen_host = payload.get("listen_host")
            listen_port = payload.get("listen_port")
            if listen_host and listen_port:
                new_key = self.connection_key(listen_host, listen_port)
                async with self.lock:
                    connection = self.connections.pop(key, None)
                    if connection:
                        connection["username"] = payload.get("from")
                        connection["host"] = listen_host
                        connection["port"] = int(listen_port)
                        self.connections[new_key] = connection
            return

        if message_type == "message":
            self.messages.append({
                "from": payload.get("from"),
                "to": payload.get("to"),
                "message": payload.get("message"),
                "timestamp": payload.get("timestamp", time.time()),
            })

    async def _send_json(self, writer, payload):
        writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await writer.drain()

    async def _drop_connection(self, key):
        async with self.lock:
            connection = self.connections.pop(key, None)
        if connection:
            writer = connection["writer"]
            if not writer.is_closing():
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    def connection_summary(self):
        return sorted(self.connections.keys())

    def inbox(self):
        return list(self.messages)

    @staticmethod
    def connection_key(host, port):
        return "{}:{}".format(host, int(port))


P2P_NODE = PeerNode()


def ensure_channel(name):
    name = (name or "general").strip().lower()
    if not name:
        name = "general"
    if name not in CHAT_CHANNELS:
        CHAT_CHANNELS[name] = {
            "name": name,
            "members": set(),
            "messages": [],
        }
    return CHAT_CHANNELS[name]


def ensure_default_channels():
    for channel in DEFAULT_CHANNELS:
        ensure_channel(channel)


def channel_summary():
    ensure_default_channels()
    return [
        {
            "name": channel["name"],
            "members": sorted(channel["members"]),
            "member_count": len(channel["members"]),
            "message_count": len(channel["messages"]),
        }
        for channel in sorted(
            CHAT_CHANNELS.values(),
            key=lambda item: item["name"],
        )
    ]


def add_chat_message(channel_name, username, text, system=False):
    global CHAT_NEXT_MESSAGE_ID

    channel = ensure_channel(channel_name)
    message = {
        "id": CHAT_NEXT_MESSAGE_ID,
        "channel": channel["name"],
        "username": username or "guest",
        "text": text,
        "system": system,
        "timestamp": int(time.time()),
    }
    CHAT_NEXT_MESSAGE_ID += 1
    channel["messages"].append(message)
    channel["messages"] = channel["messages"][-200:]
    return message


def chat_messages(channel_name, since_id=0):
    channel = ensure_channel(channel_name)
    return [
        message
        for message in channel["messages"]
        if int(message["id"]) > int(since_id or 0)
    ]


def chat_peers():
    ensure_default_channels()
    names = set()
    for channel in CHAT_CHANNELS.values():
        names.update(channel["members"])
    return sorted(names)


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


@app.route("/connect-peer", methods=["POST", "PUT"])
async def connect_peer(headers, body, request):
    data = parse_body(body, headers)
    local_username = data.get("local_username") or data.get("from")
    local_host = data.get("listen_host", "127.0.0.1")
    local_port = data.get("listen_port")
    peer_username = data.get("peer_username") or data.get("username")
    peer_host = data.get("peer_ip") or data.get("host") or data.get("ip")
    peer_port = data.get("peer_port") or data.get("port")

    try:
        server_info = await P2P_NODE.start_server(
            username=local_username,
            host=local_host,
            port=local_port,
        )
    except OSError as exc:
        return json_response(
            {"error": "Peer server failed", "message": str(exc)},
            status=502,
        )

    if not peer_host or not peer_port:
        return json_response(
            {
                "message": "Peer server ready",
                "server": server_info,
                "connections": P2P_NODE.connection_summary(),
            }
        )

    try:
        result = await P2P_NODE.connect(peer_username, peer_host, peer_port)
    except (ConnectionError, OSError) as exc:
        return json_response(
            {"error": "Peer unavailable", "message": str(exc)},
            status=502,
        )

    return json_response(
        {
            "message": "Peer connected",
            "server": server_info,
            "connection": result,
            "connections": P2P_NODE.connection_summary(),
        }
    )


@app.route("/send-peer", methods=["POST"])
async def send_peer(headers, body, request):
    data = parse_body(body, headers)
    local_username = data.get("local_username") or data.get("from")
    if local_username:
        P2P_NODE.username = local_username

    peer_username = data.get("peer_username") or data.get("username")
    peer_host = data.get("peer_ip") or data.get("host") or data.get("ip")
    peer_port = data.get("peer_port") or data.get("port")
    message = data.get("message")

    if not peer_username or not peer_host or not peer_port or message is None:
        return json_response(
            {
                "error": "Bad Request",
                "message": "peer username, peer_ip, peer_port and message required",
            },
            status=400,
        )

    try:
        result = await P2P_NODE.send_message(
            peer_username,
            peer_host,
            peer_port,
            message,
        )
    except (ConnectionError, OSError) as exc:
        return json_response(
            {"error": "Peer unavailable", "message": str(exc)},
            status=502,
        )

    return json_response(
        {
            "message": "Direct peer message sent",
            "result": result,
            "connections": P2P_NODE.connection_summary(),
        }
    )


@app.route("/broadcast-peer", methods=["POST"])
async def broadcast_peer(headers, body, request):
    data = parse_body(body, headers)
    local_username = data.get("local_username") or data.get("from")
    if local_username:
        P2P_NODE.username = local_username

    message = data.get("message")
    peers = data.get("peers")
    if peers is None:
        peers = peer_list()
    elif isinstance(peers, str):
        try:
            peers = json.loads(peers)
        except json.JSONDecodeError:
            peers = []

    if message is None:
        return json_response(
            {"error": "Bad Request", "message": "message is required"},
            status=400,
        )

    own_port = P2P_NODE.port
    own_host = P2P_NODE.host
    targets = [
        peer
        for peer in peers
        if not (
            str(peer.get("peer_ip") or peer.get("host") or peer.get("ip"))
            == str(own_host)
            and int(peer.get("peer_port") or peer.get("port") or 0)
            == int(own_port or 0)
        )
    ]

    results = await P2P_NODE.broadcast(targets, message)
    return json_response(
        {
            "message": "Broadcast complete",
            "targets": len(targets),
            "results": results,
            "connections": P2P_NODE.connection_summary(),
        }
    )


@app.route("/peer-inbox", methods=["GET"])
def peer_inbox(headers, body, request):
    return json_response(
        {
            "username": P2P_NODE.username,
            "listening": P2P_NODE.server is not None,
            "host": P2P_NODE.host,
            "port": P2P_NODE.port,
            "connections": P2P_NODE.connection_summary(),
            "messages": P2P_NODE.inbox(),
        }
    )


@app.route("/chat-state", methods=["GET"])
def chat_state(headers, body, request):
    username = request.query_params.get("username", ["guest"])[0] or "guest"
    channel_name = request.query_params.get("channel", ["general"])[0]
    since_id = request.query_params.get("since", ["0"])[0]
    ensure_default_channels()
    ensure_channel(channel_name)["members"].add(username)
    messages = chat_messages(channel_name, since_id=since_id)
    latest_by_channel = []
    for channel in CHAT_CHANNELS.values():
        if channel["name"] == channel_name or not channel["messages"]:
            continue
        latest = channel["messages"][-1]
        latest_by_channel.append({
            "channel": channel["name"],
            "text": latest["text"],
            "username": latest["username"],
            "id": latest["id"],
        })
    return json_response(
        {
            "username": username,
            "active_channel": channel_name,
            "channels": channel_summary(),
            "peers": chat_peers(),
            "messages": messages,
            "notifications": latest_by_channel[-5:],
        }
    )


@app.route("/chat-history", methods=["GET"])
def chat_history(headers, body, request):
    channel_name = request.query_params.get("channel", ["general"])[0]
    limit = request.query_params.get("limit", ["50"])[0]
    try:
        limit = int(limit)
    except ValueError:
        limit = 50
    channel = ensure_channel(channel_name)
    return json_response(
        {
            "channel": channel["name"],
            "messages": channel["messages"][-limit:],
        }
    )


@app.route("/channel-join", methods=["POST", "PUT"])
def channel_join(headers, body, request):
    data = parse_body(body, headers)
    username = data.get("username", "guest") or "guest"
    channel_name = data.get("channel", "general") or "general"
    channel = ensure_channel(channel_name)
    was_member = username in channel["members"]
    channel["members"].add(username)
    if not was_member:
        add_chat_message(channel["name"], "system", "{} joined".format(username), True)
    return json_response(
        {
            "joined": True,
            "channel": channel["name"],
            "channels": channel_summary(),
        }
    )


@app.route("/channel-create", methods=["POST", "PUT"])
def channel_create(headers, body, request):
    data = parse_body(body, headers)
    username = data.get("username", "guest") or "guest"
    channel_name = data.get("channel", "").strip().lower()
    if not channel_name:
        return json_response(
            {"error": "Bad Request", "message": "channel is required"},
            status=400,
        )

    existed = channel_name in CHAT_CHANNELS
    channel = ensure_channel(channel_name)
    channel["members"].add(username)
    if not existed:
        add_chat_message(
            channel["name"],
            "system",
            "{} created #{}".format(username, channel["name"]),
            True,
        )
    return json_response(
        {
            "created": not existed,
            "joined": True,
            "channel": channel["name"],
            "channels": channel_summary(),
        }
    )


@app.route("/channel-leave", methods=["POST", "PUT"])
def channel_leave(headers, body, request):
    data = parse_body(body, headers)
    username = data.get("username", "guest") or "guest"
    channel_name = data.get("channel", "general") or "general"
    channel = ensure_channel(channel_name)
    was_member = username in channel["members"]
    channel["members"].discard(username)
    if was_member:
        add_chat_message(channel["name"], "system", "{} left".format(username), True)
    return json_response(
        {
            "left": was_member,
            "channel": channel["name"],
            "channels": channel_summary(),
        }
    )


@app.route("/chat-message", methods=["POST"])
def chat_message(headers, body, request):
    data = parse_body(body, headers)
    username = data.get("username", "guest") or "guest"
    channel_name = data.get("channel", "general") or "general"
    text = data.get("message", "").strip()
    if not text:
        return json_response(
            {"error": "Bad Request", "message": "message is required"},
            status=400,
        )
    ensure_channel(channel_name)["members"].add(username)
    message = add_chat_message(channel_name, username, text)
    return json_response(
        {
            "sent": True,
            "message": message,
            "channels": channel_summary(),
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
