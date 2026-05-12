# CO3094 Final Report Notes

## 1. Architecture

The system is a hybrid P2P chat application split into three layers:

```text
Client / Browser / curl
        |
        v
Async backend server
daemon/backend.py -> daemon/httpadapter.py
        |
        v
Application routes (auth + tracker only)
apps/sampleapp.py
        |
        +--> Static files: www/, static/
        +--> Auth/session store: in memory
        +--> Peer registry: in memory

peer.py (one process per user)
        |
        +--> TrackerClient: http.client to sampleapp.py
        +--> PeerNode: asyncio TCP server + client for direct chat
```

The tracker does not forward chat messages.  Direct P2P transport is handled
entirely by `peer.py` over asyncio TCP sockets.

### Main Modules

- `daemon/request.py`: parses request line, headers, body, query parameters and cookies.
- `daemon/response.py`: formats HTTP responses, status codes, JSON, static files and errors.
- `daemon/httpadapter.py`: handles one HTTP connection and dispatches routes.
- `daemon/backend.py`: owns the asyncio server lifecycle.
- `daemon/proxy.py`: reverse proxy with host routing and round-robin backend selection.
- `apps/sampleapp.py`: HTTP authentication, peer tracker, and deprecated endpoint stubs.
- `peer.py`: one-peer-per-terminal process with asyncio TCP server/client.

### What the Tracker Does

- Authenticates users with in-memory credentials and session cookies.
- Stores short-lived peer presence records (IP, port, status, channels).
- Expires inactive peers after a configurable TTL.
- Serves the browser dashboard (tracker state, peer list, registration).

### What the Tracker Does NOT Do

- Forward chat messages between peers.
- Store chat history.
- Manage chat channels beyond discovery metadata.

## 2. HTTP Flow

```text
1. Client opens TCP connection.
2. asyncio.start_server accepts the connection.
3. StreamReader reads headers and body.
4. Request.prepare parses the raw HTTP message.
5. HttpAdapter dispatches by (method, path).
6. Route handler returns a response envelope.
7. Response builds HTTP/1.1 bytes.
8. StreamWriter sends bytes and closes the connection.
```

## 3. Reverse Proxy Flow

```text
1. Proxy receives a request.
2. Proxy reads Host header.
3. config/proxy.conf maps Host to one or more backends.
4. If multiple backends exist, round-robin selects one.
5. Proxy forwards the raw HTTP request.
6. Backend response is streamed back to the client.
```

## 4. Authentication

Authentication uses in-memory users and cookie sessions.

```text
POST /login
  -> validate username/password
  -> create session_id (secrets.token_urlsafe)
  -> Set-Cookie: session_id=...; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax

GET /me
  -> parse Cookie header
  -> lookup session_id in SESSIONS
  -> check TTL expiration
  -> 200 if valid, 401 if missing or expired

GET /admin
  -> valid session required
  -> role must be admin
  -> 403 if role is insufficient
```

No JWT or database is used.  Session tokens are random URL-safe strings.

## 5. Tracker (Peer Discovery)

The tracker is centralized peer discovery with cookie-protected endpoints.

```text
POST /submit-info   (requires cookie)
  username from session, peer_ip, peer_port, status, channels

GET /get-list       (requires cookie)
  returns active peers as JSON

POST /heartbeat     (requires cookie)
  refreshes last_seen for peers owned by the logged-in user

POST /leave         (requires cookie)
  marks the logged-in user's peer as offline

GET /tracker-state  (requires cookie)
  returns dashboard state: user, peers, channels
```

The registry is in memory and removes inactive (TTL-expired) or offline
peers automatically.  The `/submit-info` endpoint always uses the username
from the authenticated session, never from the request body, preventing
impersonation.

## 6. Direct P2P Protocol

P2P messages do not pass through the central tracker.  Each `peer.py`
process is one real peer that connects directly to other peers using asyncio
TCP sockets.

The protocol uses JSON-line framing: one JSON object per line, terminated by
`\n`, read with `StreamReader.readline()`.

### Handshake (HELLO)

```json
{"type": "hello", "from": "alice", "listen_host": "127.0.0.1", "listen_port": 9001, "timestamp": 1234567890.0}
```

No ACK is required for HELLO.

### Direct Message

```json
{"type": "direct", "from": "alice", "to": "bob", "channel": "general", "message": "hello bob", "message_id": "uuid-...", "timestamp": 1234567890.0}
```

### Broadcast Message

```json
{"type": "broadcast", "from": "alice", "channel": "general", "message": "hello everyone", "message_id": "uuid-...", "timestamp": 1234567890.0}
```

### ACK

```json
{"type": "ack", "from": "bob", "message_id": "uuid-...", "timestamp": 1234567890.0}
```

The sender waits for an ACK with a matching `message_id`.  If the ACK does
not arrive within the timeout (default 3 seconds), the send is reported as
failed.  Unrelated ACKs are ignored.

### Error

```json
{"type": "error", "from": "bob", "message": "invalid payload", "timestamp": 1234567890.0}
```

### Send Flow

```text
1. Sender opens asyncio.open_connection to receiver's IP:port.
2. Sender writes HELLO (JSON-line).
3. Sender writes DIRECT or BROADCAST payload (JSON-line).
4. Sender reads lines until:
   a. ACK with matching message_id -> success
   b. ERROR -> failure
   c. Timeout -> failure
   d. Connection closed -> failure
5. Sender closes the connection.
```

### Broadcast Flow

```text
1. Sender fetches peer list from tracker (GET /get-list).
2. Sender excludes self from the list.
3. Sender creates asyncio tasks for each peer using asyncio.gather.
4. Each task performs the send flow above independently.
5. Results are collected: succeeded count, failed count, per-peer errors.
```

### Deprecated Server-Side P2P Endpoints

The following endpoints existed in earlier phases when sampleapp.py included
a server-side P2P node.  They are now rejected with HTTP 410 Gone:

- `POST /connect-peer`
- `POST /send-peer`
- `POST /broadcast-peer`
- `GET /peer-inbox`

## 7. Async Design

The backend uses `asyncio.start_server`.  Each accepted HTTP client is
handled by a coroutine without blocking the event loop.

Important async APIs used:

- `StreamReader.readuntil(b"\r\n\r\n")` — read HTTP headers
- `StreamReader.readexactly(content_length)` — read HTTP body
- `StreamWriter.write(...)` / `await StreamWriter.drain()`
- `StreamWriter.close()` / `await StreamWriter.wait_closed()`
- `asyncio.to_thread(...)` — run synchronous route handlers and
  `http.client` tracker calls without blocking
- `asyncio.wait_for(...)` — timeout for ACK reads
- `asyncio.gather(...)` — parallel broadcast sends

In `peer.py`, the event loop runs:

- The TCP peer server (`asyncio.start_server`)
- The terminal command loop (`asyncio.to_thread(input, "> ")`)
- The heartbeat timer (`asyncio.sleep` in a loop)

All three run concurrently in the same event loop.

## 8. Browser Dashboard

The frontend is plain HTML/CSS/JavaScript with no external frameworks.

Files:

- `www/login.html` — login form
- `www/chat.html` — tracker dashboard
- `static/js/chat.js` — dashboard logic
- `static/css/chat.css` — dashboard styles

The browser UI is only a tracker dashboard.  It shows:

- Current authenticated user (from `/me`)
- Tracker state: active peer count, channels (from `/tracker-state`)
- Active peer cards: username, IP, port, status, channels, last seen
  (from `/get-list`)
- Peer registration form (calls `/submit-info`)
- Heartbeat and leave buttons
- Architecture notice explaining that chat is handled by `peer.py`
- Demo CLI commands for `peer.py`

The browser UI does NOT send or receive P2P chat messages.

## 9. Error Handling

The system handles:

- malformed HTTP requests: `400`
- missing/invalid auth: `401`
- insufficient permissions: `403`
- missing route/file: `404`
- unsupported method: `405`
- slow/idle async client: `408`
- deprecated P2P endpoints: `410`
- oversized request body: `413`
- unexpected server error: `500`
- backend or peer unavailable: `502`

Sockets and writers are closed in `finally` blocks.

## 10. Demo Checklist

### Start the Tracker

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

### Browser Dashboard

```text
http://127.0.0.1:2026/login.html
```

Log in as `alice` with password `wonderland`.

### Start Three Peers

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
python peer.py --username bob --password wonderland --listen-port 9002
python peer.py --username charlie --password wonderland --listen-port 9003
```

### Direct Message and Broadcast

In Alice's terminal:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

Expected:

- `/list` shows bob and charlie with IP, port, status, channels.
- Bob receives `[direct] alice: hello bob`.
- Bob and Charlie receive `[broadcast] alice: hello everyone`.
- Alice sees ACK confirmation for each send.
- The tracker logs only auth/register/list/heartbeat/leave requests.

### HTTP Authentication Check

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
curl.exe -i http://127.0.0.1:2026/me -H "Cookie: session_id=<value-from-login>"
```

### Smoke Test

```powershell
python tests/smoke_http.py
```

## 11. Limitations

- All state (sessions, peers, channels) is in memory only.
- No persistent database.
- No encryption or TLS.  All HTTP and TCP traffic is plaintext.
- Designed for local assignment demo on a single machine.
- Peer discovery requires the tracker to be running.
- The browser dashboard cannot send or receive P2P messages.
