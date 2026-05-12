"""Run one authenticated peer in the hybrid P2P chat demo.

Each terminal starts one peer process.  The peer logs in to the HTTP tracker
for cookie-based authentication and discovery, then sends chat payloads
directly to other peers over asyncio TCP sockets.  JSON-line framing is used
because every message is a single JSON object followed by a newline, which lets
``StreamReader.readline`` parse messages without blocking the event loop.
"""

import argparse
import asyncio
import http.client
import json
import signal
import time
import uuid
from dataclasses import dataclass
from http.cookies import SimpleCookie


DEFAULT_TRACKER_HOST = "127.0.0.1"
DEFAULT_TRACKER_PORT = 2026
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_CHANNEL = "general"
HEARTBEAT_INTERVAL = 20
READ_ACK_TIMEOUT = 3


class TrackerError(RuntimeError):
    """Represent a failed tracker HTTP request."""


class TrackerClient:
    """Communicate with the HTTP tracker using session cookies."""

    def __init__(self, host, port):
        self.host = host
        self.port = int(port)
        self.session_cookie = ""

    async def login(self, username, password):
        """Authenticate with the tracker and store the session cookie."""
        data = await self.request(
            "POST",
            "/login",
            {"username": username, "password": password},
        )
        return data

    async def me(self):
        """Return the tracker identity for the current session."""
        return await self.request("GET", "/me")

    async def register(self, listen_host, listen_port, channels=None):
        """Register this peer endpoint with the tracker."""
        return await self.request(
            "POST",
            "/submit-info",
            {
                "peer_ip": listen_host,
                "peer_port": int(listen_port),
                "status": "online",
                "channels": channels or [DEFAULT_CHANNEL],
            },
        )

    async def get_list(self):
        """Return the active peer list from the tracker."""
        data = await self.request("GET", "/get-list")
        return data.get("peers", [])

    async def heartbeat(self, listen_host, listen_port):
        """Refresh this peer's tracker presence."""
        return await self.request(
            "POST",
            "/heartbeat",
            {
                "peer_ip": listen_host,
                "peer_port": int(listen_port),
                "status": "online",
            },
        )

    async def leave(self, listen_host, listen_port):
        """Tell the tracker this peer is leaving."""
        return await self.request(
            "POST",
            "/leave",
            {"peer_ip": listen_host, "peer_port": int(listen_port)},
        )

    async def request(self, method, path, payload=None):
        """Send one tracker request without blocking the event loop."""
        return await asyncio.to_thread(self._request_sync, method, path, payload)

    def _request_sync(self, method, path, payload=None):
        body = b""
        headers = {"Host": "{}:{}".format(self.host, self.port)}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie

        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            self._store_cookie(response.getheaders())
            data = self._decode_json(raw)
            if response.status >= 400:
                message = data.get("message") if isinstance(data, dict) else raw
                raise TrackerError(
                    "tracker {} {} failed: HTTP {} {}".format(
                        method,
                        path,
                        response.status,
                        message,
                    )
                )
            return data
        finally:
            connection.close()

    def _store_cookie(self, headers):
        for name, value in headers:
            if name.lower() != "set-cookie":
                continue
            cookie = SimpleCookie()
            cookie.load(value)
            if "session_id" in cookie:
                morsel = cookie["session_id"]
                self.session_cookie = "session_id={}".format(morsel.value)

    @staticmethod
    def _decode_json(raw):
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrackerError("tracker returned invalid JSON") from exc


@dataclass
class PeerMessage:
    """Represent one JSON-line peer protocol payload."""

    type: str
    sender: str
    message: str = ""
    channel: str = DEFAULT_CHANNEL
    recipient: str = ""
    message_id: str = ""
    timestamp: float = 0.0

    def to_payload(self):
        """Return the wire-format dictionary for this message."""
        payload = {
            "type": self.type,
            "from": self.sender,
            "channel": self.channel,
            "message": self.message,
            "message_id": self.message_id or str(uuid.uuid4()),
            "timestamp": self.timestamp or time.time(),
        }
        if self.recipient:
            payload["to"] = self.recipient
        return payload


class PeerNode:
    """Run the local TCP server and direct peer socket messaging."""

    def __init__(
        self,
        username,
        password,
        listen_host,
        listen_port,
        tracker,
        channel=DEFAULT_CHANNEL,
    ):
        self.username = username
        self.password = password
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.tracker = tracker
        self.channel = channel
        self.server = None
        self.inbox = []
        self.connections = {}
        self.lock = asyncio.Lock()
        self.heartbeat_task = None
        self.running = True

    async def start(self):
        """Start the local peer server and register with the tracker."""
        user = await self.tracker.login(self.username, self.password)
        print("logged in as {} ({})".format(user["username"], user["role"]))
        self.server = await asyncio.start_server(
            self.handle_peer,
            self.listen_host,
            self.listen_port,
        )
        sockets = ", ".join(
            str(sock.getsockname()) for sock in self.server.sockets or []
        )
        print("listening for peers on {}".format(sockets))
        await self.register_self()
        self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())

    async def login_and_register(self):
        """Log in and publish this peer endpoint to the tracker."""
        user = await self.tracker.login(self.username, self.password)
        print("logged in as {} ({})".format(user["username"], user["role"]))
        await self.register_self()

    async def register_self(self):
        """Publish this peer endpoint to the tracker."""
        await self.tracker.register(
            self.listen_host,
            self.listen_port,
            channels=[self.channel],
        )
        print(
            "registered {} at {}:{}".format(
                self.username,
                self.listen_host,
                self.listen_port,
            )
        )

    async def heartbeat_loop(self):
        """Keep tracker presence fresh while the CLI remains responsive."""
        while self.running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await self.tracker.heartbeat(self.listen_host, self.listen_port)
            except TrackerError as exc:
                print("heartbeat failed: {}".format(exc))

    async def handle_peer(self, reader, writer):
        """Read JSON-line messages from one incoming peer connection."""
        addr = writer.get_extra_info("peername")
        key = "{}:{}".format(addr[0], addr[1])
        async with self.lock:
            self.connections[key] = {"addr": addr, "from": "unknown"}

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await self.write_json(
                        writer,
                        self.error_payload("invalid payload"),
                    )
                    continue
                await self.handle_payload(key, payload, writer)
        finally:
            async with self.lock:
                self.connections.pop(key, None)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def handle_payload(self, key, payload, writer):
        """Process one decoded peer protocol payload."""
        message_type = payload.get("type")
        sender = payload.get("from", "unknown")
        async with self.lock:
            if key in self.connections:
                self.connections[key]["from"] = sender

        if message_type == "hello":
            return

        if message_type in {"direct", "broadcast"}:
            if message_type == "direct" and payload.get("to") != self.username:
                await self.write_json(
                    writer,
                    self.error_payload("message addressed to another peer"),
                )
                return

            async with self.lock:
                self.inbox.append(payload)
            print(
                "\n[{}] {}: {}\n> ".format(
                    message_type,
                    sender,
                    payload.get("message", ""),
                ),
                end="",
                flush=True,
            )
            await self.write_json(
                writer,
                {
                    "type": "ack",
                    "from": self.username,
                    "message_id": payload.get("message_id"),
                    "timestamp": time.time(),
                },
            )
            return

        if message_type == "ack":
            print("ack from {} for {}".format(sender, payload.get("message_id")))
            return

        await self.write_json(writer, self.error_payload("unknown message type"))

    def error_payload(self, message):
        """Return a protocol error payload from this peer."""
        return {
            "type": "error",
            "from": self.username,
            "message": message,
            "timestamp": time.time(),
        }

    async def send_direct(self, recipient, message):
        """Send a direct JSON-line message to one peer."""
        peer = await self.find_peer(recipient)
        payload = PeerMessage(
            type="direct",
            sender=self.username,
            recipient=recipient,
            channel=self.channel,
            message=message,
        ).to_payload()
        return await self.send_payload(peer, payload)

    async def broadcast(self, message):
        """Send a broadcast JSON-line message directly to all other peers."""
        peers = [
            peer
            for peer in await self.tracker.get_list()
            if peer.get("username") != self.username
        ]
        payloads = [
            self.send_payload(
                peer,
                PeerMessage(
                    type="broadcast",
                    sender=self.username,
                    channel=self.channel,
                    message=message,
                ).to_payload(),
            )
            for peer in peers
        ]
        if not payloads:
            return []
        return await asyncio.gather(*payloads, return_exceptions=True)

    async def find_peer(self, username):
        """Find one active peer by username."""
        for peer in await self.tracker.get_list():
            if peer.get("username") == username:
                return peer
        raise TrackerError("peer '{}' is not registered".format(username))

    async def send_payload(self, peer, payload):
        """Open a direct TCP socket and send one JSON-line payload."""
        host = peer["peer_ip"]
        port = int(peer["peer_port"])
        reader, writer = await asyncio.open_connection(host, port)
        try:
            await self.write_json(
                writer,
                {
                    "type": "hello",
                    "from": self.username,
                    "listen_host": self.listen_host,
                    "listen_port": self.listen_port,
                    "timestamp": time.time(),
                },
            )
            await self.write_json(writer, payload)
            try:
                line = await asyncio.wait_for(
                    reader.readline(),
                    timeout=READ_ACK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                return {"peer": peer["username"], "ack": False}
            if not line:
                return {"peer": peer["username"], "ack": False}
            ack = json.loads(line.decode("utf-8"))
            return {"peer": peer["username"], "ack": ack}
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    @staticmethod
    async def write_json(writer, payload):
        """Write one JSON object plus newline to a stream writer."""
        writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await writer.drain()

    async def print_peer_list(self):
        """Fetch and print active peers from the tracker."""
        peers = await self.tracker.get_list()
        if not peers:
            print("no active peers")
            return
        for peer in peers:
            marker = " (you)" if peer["username"] == self.username else ""
            print(
                "{username}{marker} {peer_ip}:{peer_port} {status} channels={channels}"
                .format(marker=marker, **peer)
            )

    async def print_inbox(self):
        """Print messages received by this peer process."""
        async with self.lock:
            messages = list(self.inbox)
        if not messages:
            print("inbox is empty")
            return
        for item in messages:
            print(
                "[{type}] {from}: {message}".format(
                    type=item.get("type"),
                    **{"from": item.get("from", "unknown")},
                    message=item.get("message", ""),
                )
            )

    async def print_connections(self):
        """Print currently open inbound peer connections."""
        async with self.lock:
            connections = dict(self.connections)
        if not connections:
            print("no open peer connections")
            return
        for key, info in connections.items():
            print("{} from {}".format(key, info.get("from", "unknown")))

    async def command_loop(self):
        """Run the asynchronous terminal command loop."""
        print_help()
        while self.running:
            try:
                raw = await asyncio.to_thread(input, "> ")
            except EOFError:
                raw = "/quit"

            command = raw.strip()
            if not command:
                continue
            await self.handle_command(command)

    async def handle_command(self, command):
        """Execute one CLI command."""
        if command == "/help":
            print_help()
        elif command == "/login":
            await self.login_and_register()
        elif command == "/register":
            await self.register_self()
        elif command == "/list":
            await self.print_peer_list()
        elif command.startswith("/msg "):
            parts = command.split(" ", 2)
            if len(parts) < 3:
                print("usage: /msg <username> <message>")
                return
            result = await self.send_direct(parts[1], parts[2])
            print("sent to {} ack={}".format(parts[1], bool(result.get("ack"))))
        elif command.startswith("/broadcast "):
            message = command.split(" ", 1)[1]
            results = await self.broadcast(message)
            print("broadcast attempted to {} peer(s)".format(len(results)))
        elif command == "/inbox":
            await self.print_inbox()
        elif command == "/connections":
            await self.print_connections()
        elif command == "/heartbeat":
            await self.tracker.heartbeat(self.listen_host, self.listen_port)
            print("heartbeat sent")
        elif command == "/leave":
            await self.tracker.leave(self.listen_host, self.listen_port)
            print("left tracker")
        elif command in {"/quit", "/exit"}:
            self.running = False
        else:
            print("unknown command; use /help")

    async def run(self):
        """Run this peer until the user quits or the task is cancelled."""
        await self.start()
        try:
            await self.command_loop()
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Notify the tracker and close local server resources."""
        if not self.running:
            print("shutting down")
        self.running = False
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        try:
            await self.tracker.leave(self.listen_host, self.listen_port)
        except TrackerError as exc:
            print("leave failed: {}".format(exc))
        if self.server:
            self.server.close()
            await self.server.wait_closed()


def print_help():
    """Print supported peer CLI commands."""
    print(
        "\n".join(
            [
                "commands:",
                "  /help",
                "  /login",
                "  /register",
                "  /list",
                "  /msg <username> <message>",
                "  /broadcast <message>",
                "  /inbox",
                "  /connections",
                "  /heartbeat",
                "  /leave",
                "  /quit",
            ]
        )
    )


def build_parser():
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(description="Run one P2P chat peer")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--listen-host", default=DEFAULT_LISTEN_HOST)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--tracker-host", default=DEFAULT_TRACKER_HOST)
    parser.add_argument("--tracker-port", type=int, default=DEFAULT_TRACKER_PORT)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    return parser


async def async_main(args):
    """Create and run the peer node."""
    tracker = TrackerClient(args.tracker_host, args.tracker_port)
    node = PeerNode(
        username=args.username,
        password=args.password,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        tracker=tracker,
        channel=args.channel,
    )
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, setattr, node, "running", False)
        except (NotImplementedError, RuntimeError):
            pass
    await node.run()


def main():
    """Parse arguments and run the asyncio peer."""
    args = build_parser().parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
