# CO3094 Hybrid P2P Chat

This repository contains a standard-library-only hybrid chat demo for the
CO3093/CO3094 Computer Networks course.  The HTTP tracker handles login,
cookie sessions, peer registration, discovery, heartbeat, and leave events.
The tracker does not forward chat messages.  Each `peer.py` process is one
real peer and sends JSON-line messages directly to other peers over asyncio
TCP sockets.

## Architecture

```
Browser (login.html / chat.html)
  |  fetch /login, /me, /tracker-state, /get-list, /submit-info, /heartbeat, /leave
  v
sampleapp.py  (HTTP auth + peer tracker)
  |  cookie sessions, peer registry, heartbeat TTL
  v
peer.py  <--- asyncio TCP --->  peer.py
  direct messages, broadcast, ACK protocol
```

- **`apps/sampleapp.py`** is the central HTTP authentication server and peer
  discovery tracker.  It never forwards chat messages.
- **`peer.py`** is the real peer process.  Each terminal runs one peer that
  logs in, registers with the tracker, then sends chat payloads directly to
  other peers over asyncio TCP sockets using JSON-line framing.
- **Browser UI** (`www/login.html`, `www/chat.html`) is only a tracker
  dashboard.  It shows the authenticated user, active peers, and tracker
  status.  It does not send or receive P2P messages.
- **`asyncio`** provides non-blocking I/O for the tracker backend, peer TCP
  server, heartbeat timer, and terminal input.

## Requirements

- Python 3.9 or newer
- Python standard library only
- No Flask, FastAPI, Django, requests, websockets, aiohttp, or external
  frontend framework

## Quick Start

### 1. Start the tracker

PowerShell:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Unix shell:

```sh
python3 start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

### 2. Open the browser dashboard

```text
http://127.0.0.1:2026/login.html
```

Log in as `alice` with password `wonderland`.  The dashboard at `/chat.html`
shows the authenticated user, active peers, tracker status, and peer
registration controls.

### 3. Start three peers

Open three new terminals from the repository root.

PowerShell:

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
python peer.py --username bob --password wonderland --listen-port 9002
python peer.py --username charlie --password wonderland --listen-port 9003
```

Unix shell:

```sh
python3 peer.py --username alice --password wonderland --listen-port 9001
python3 peer.py --username bob --password wonderland --listen-port 9002
python3 peer.py --username charlie --password wonderland --listen-port 9003
```

### 4. Demo direct and broadcast chat

In Alice's terminal:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

## Expected Output

- `/list` shows bob and charlie with their IP, port, status, and channels.
- Bob's terminal prints `[direct] alice: hello bob` and Alice sees `ack=True`.
- Bob and Charlie both print `[broadcast] alice: hello everyone`.
- Alice sees `broadcast to 2 peer(s): 2 succeeded, 0 failed`.
- The browser dashboard shows all three peers after refreshing.
- The tracker server logs only auth, register, list, heartbeat, and leave
  requests.  No chat message appears in tracker logs.

## Tracker Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/login` | No | Authenticate and receive session cookie |
| POST | `/logout` | No | Clear session cookie |
| GET | `/me` | Yes | Current user identity |
| GET | `/private` | Yes | Protected user-only route |
| GET | `/admin` | Admin | Protected admin-only route |
| POST | `/submit-info` | Yes | Register or update peer endpoint |
| GET | `/get-list` | Yes | Active peer list |
| POST | `/heartbeat` | Yes | Refresh peer presence |
| POST/DELETE | `/leave` | Yes | Mark peer offline |
| GET | `/tracker-state` | Yes | Dashboard state payload |
| GET | `/chat-state` | Yes | Compatibility alias for tracker-state |
| POST | `/connect-peer` | Yes | Return target peer endpoint for connection setup |

Deprecated endpoints (`/send-peer`, `/broadcast-peer`, `/peer-inbox`) return
HTTP 410 Gone with a message explaining that direct chat is implemented by
`peer.py`.  `/connect-peer` is **not** deprecated; it returns the target
peer's `peer_ip` and `peer_port` so `peer.py` can open the direct TCP
socket itself.  The tracker never forwards chat messages.

Example:

```text
POST /connect-peer
Body: {"username": "bob"}

Returns bob's peer_ip and peer_port; peer.py then opens the direct TCP
socket.  The tracker does not forward chat messages.
```

## Peer CLI Commands

```text
/help            Show available commands
/login           Re-authenticate with the tracker
/register        Re-register peer endpoint
/list            Show active peers from tracker
/msg <user> <m>  Send direct message to one peer
/broadcast <m>   Send broadcast to all other peers
/inbox           Show received messages
/connections     Show open inbound connections
/heartbeat       Manually send heartbeat
/leave           Notify tracker this peer is leaving
/quit            Shut down gracefully
```

## Manual HTTP Checks

Login and capture the returned `Set-Cookie` header:

PowerShell:

```powershell
curl -i -X POST http://127.0.0.1:2026/login `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Unix shell:

```sh
curl -i -X POST http://127.0.0.1:2026/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"wonderland"}'
```

Use the cookie with a protected endpoint:

```powershell
curl -i http://127.0.0.1:2026/me `
  -H "Cookie: session_id=<value-from-login>"
```

Unauthenticated protected requests should return `HTTP/1.1 401 Unauthorized`.

## Test Checklist

- [ ] `python -m compileall .` passes with no errors
- [ ] Login returns `Set-Cookie: session_id=...; Path=/; HttpOnly; SameSite=Lax`
- [ ] `GET /me` without cookie returns 401
- [ ] `POST /submit-info` without cookie returns 401
- [ ] `GET /get-list` without cookie returns 401
- [ ] `POST /heartbeat` without cookie returns 401
- [ ] `POST /leave` without cookie returns 401
- [ ] `GET /tracker-state` without cookie returns 401
- [ ] `/submit-info` uses username from session, not request body
- [ ] Direct message between two peers succeeds with ACK
- [ ] Broadcast reaches all other peers
- [ ] Tracker logs show no chat message forwarding
- [ ] Browser dashboard shows peers after registration
- [ ] Deprecated endpoints return 410 Gone

## Smoke Test

A standard-library-only smoke test is included:

```sh
python tests/smoke_http.py
```

It logs in as alice, calls `/me`, registers a peer, fetches the peer list,
and prints PASS/FAIL for each step.

## Limitations

- All state is in-memory only.  Restarting the tracker clears sessions and
  peer records.
- No persistent database.
- No encryption or TLS.  All HTTP and TCP traffic is plaintext.
- Designed for local assignment demo on a single machine.
- Peer discovery requires the tracker to be running.  If the tracker stops,
  peers cannot discover each other but existing direct connections continue.
- The browser dashboard is read-only with respect to chat.  It cannot send
  or receive P2P messages.

## Checks

```powershell
python -m compileall .
```

If `python` is not on PATH in your environment, run the same command with the
full path to your Python executable.
