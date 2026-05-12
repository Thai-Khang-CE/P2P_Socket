# CO3094 Final Report Notes

## 1. Architecture

The system is split into four cooperating layers:

```text
Client / Browser / curl
        |
        v
Reverse proxy, optional
daemon/proxy.py
        |
        v
Async backend server
daemon/backend.py -> daemon/httpadapter.py
        |
        v
Application routes
apps/sampleapp.py
        |
        +--> Static files: www/, static/
        +--> Auth/session store: in memory
        +--> Peer registry: in memory
        +--> P2P node: asyncio socket server/client
        +--> Chat UI state: in memory
```

### Main Modules

- `daemon/request.py`: parses request line, headers, body, query parameters and cookies.
- `daemon/response.py`: formats HTTP responses, status codes, JSON, static files and errors.
- `daemon/httpadapter.py`: handles one HTTP connection and dispatches routes.
- `daemon/backend.py`: owns the asyncio server lifecycle.
- `daemon/proxy.py`: reverse proxy with host routing and round-robin backend selection.
- `apps/sampleapp.py`: sample REST app, authentication, tracker, P2P and chat routes.

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
  -> create session_id
  -> Set-Cookie: session_id=...

GET /private
  -> parse Cookie header
  -> lookup session_id
  -> 200 if valid, 401 if missing

GET /admin
  -> valid session required
  -> role must be admin
  -> 403 if role is not enough
```

No JWT or database is used.

## 5. Tracker

The tracker is centralized peer discovery.

```text
POST /submit-info
  username, peer_ip, peer_port, status, channels

GET /get-list
  returns active peers as JSON

POST/DELETE /add-list
  add/update/remove peer entries
```

The registry is in memory and removes inactive or offline peers.

## 6. P2P Protocol

P2P messages do not pass through the central tracker. The REST API only tells a
local peer node what to do.

The direct peer protocol is newline-delimited JSON over asyncio sockets.

Handshake:

```json
{"type": "hello", "from": "alice", "listen_host": "127.0.0.1", "listen_port": 6001}
```

Direct message:

```json
{"type": "message", "from": "alice", "to": "bob", "message": "hello", "timestamp": 123}
```

Routes:

- `POST /connect-peer`: starts local peer server and optionally connects to a remote peer.
- `POST /send-peer`: sends one direct peer message.
- `POST /broadcast-peer`: sends one message to many peers.
- `POST /disconnect-peer`: gracefully closes peer connections.
- `GET /peer-inbox`: demo helper to inspect received direct messages.

## 7. Async Design

The backend uses `asyncio.start_server`. Each accepted client is handled by a
coroutine.

Important async APIs:

- `StreamReader.readuntil(b"\r\n\r\n")`
- `StreamReader.readexactly(content_length)`
- `StreamWriter.write(...)`
- `await StreamWriter.drain()`
- `StreamWriter.close()`
- `await StreamWriter.wait_closed()`

Synchronous route handlers are supported with `asyncio.to_thread(...)` so they
do not block the event loop.

## 8. Chat UI

The frontend is plain HTML/CSS/JavaScript.

Files:

- `www/chat.html`
- `www/js/chat.js`
- `static/css/chat.css`

Features:

- message window
- text input and send button
- channel list
- explicit create/join/leave channel controls
- peer list
- message history
- live polling updates
- in-page and optional browser notifications

## 9. Error Handling

The system now handles:

- malformed HTTP requests: `400`
- missing/invalid auth: `401`
- insufficient permissions: `403`
- missing route/file: `404`
- unsupported method: `405`
- slow/idle async client: `408`
- oversized request body: `413`
- backend or peer unavailable: `502`
- unexpected server error: `500`

Sockets are closed in `finally` blocks where possible.

## 10. Demo Checklist

Authentication:

```powershell
curl.exe -i -c cookies.txt -X POST http://127.0.0.1:2026/login -H "Content-Type: application/x-www-form-urlencoded" -d "username=alice&password=wonderland"
curl.exe -i -b cookies.txt http://127.0.0.1:2026/private
```

Proxy:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9002
python start_backend.py --server-ip 127.0.0.1 --server-port 9003
python start_proxy.py --server-ip 127.0.0.1 --server-port 8080
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
```

Async stress:

```powershell
python tools/stress_test.py --url http://127.0.0.1:2026/async-hello --requests 50 --concurrency 10 --timeout 10
```

P2P:

```powershell
curl.exe -i -X POST http://127.0.0.1:2027/connect-peer -H "Content-Type: application/x-www-form-urlencoded" -d "local_username=bob&listen_host=127.0.0.1&listen_port=6002"
curl.exe -i -X POST http://127.0.0.1:2026/connect-peer -H "Content-Type: application/x-www-form-urlencoded" -d "local_username=alice&listen_host=127.0.0.1&listen_port=6001&peer_username=bob&peer_ip=127.0.0.1&peer_port=6002"
curl.exe -i -X POST http://127.0.0.1:2026/send-peer -H "Content-Type: application/x-www-form-urlencoded" -d "local_username=alice&peer_username=bob&peer_ip=127.0.0.1&peer_port=6002&message=hello"
curl.exe -i http://127.0.0.1:2027/peer-inbox
```

Chat UI:

```text
http://127.0.0.1:2026/chat.html
```

## 11. Screenshot List

Capture these for the report:

- backend startup logs
- proxy round-robin logs
- successful login response with `Set-Cookie`
- `/private` after login
- `/get-list` peer registry response
- P2P inbox after direct message
- chat UI with two browser windows
- stress test output
