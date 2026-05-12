# CO3094 Hybrid P2P Chat

This repository contains a small standard-library-only hybrid chat demo.
The HTTP tracker handles login, cookie sessions, peer registration, peer
discovery, heartbeat, and leave events.  Chat messages are not forwarded by
the tracker.  Each `peer.py` process opens its own asyncio TCP server and sends
JSON-line chat payloads directly to other peers.

## Requirements

- Python 3.9 or newer
- Python standard library only
- No Flask, FastAPI, Django, requests, websockets, aiohttp, or other external
  dependency

## Start The Tracker

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

The tracker exposes:

- `POST /login`
- `POST /logout`
- `GET /me`
- `GET /private`
- `GET /admin`
- `POST /submit-info`
- `GET /get-list`
- `POST /heartbeat`
- `POST` or `DELETE /leave`

## Start Three Peers

Open three new terminals from the repository root.

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
```

```powershell
python peer.py --username bob --password wonderland --listen-port 9002
```

```powershell
python peer.py --username charlie --password wonderland --listen-port 9003
```

Each peer logs in, preserves the `session_id` cookie, starts a local TCP
listener with `asyncio.start_server`, and registers its address with the
tracker.

## Demo Sequence

In Alice's terminal:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

Expected result:

- Bob receives the direct message from Alice.
- Bob and Charlie receive the broadcast from Alice.
- The tracker logs only HTTP login/register/list/heartbeat/leave requests.
- The tracker does not forward or store direct P2P chat messages.

## Peer CLI Commands

```text
/help
/login
/register
/list
/msg <username> <message>
/broadcast <message>
/inbox
/connections
/heartbeat
/leave
/quit
```

## Architecture

The design separates the tracker/auth server from peer processes:

- `apps/sampleapp.py` is the central HTTP tracker and authentication app.
- `peer.py` is the real peer process for Alice, Bob, Charlie, or another user.
- The tracker uses cookies to protect `/submit-info`, `/get-list`,
  `/heartbeat`, and `/leave`.
- Peers use the tracker only for discovery.
- Actual chat messages travel over direct TCP peer-to-peer sockets.
- Peer messages use JSON-line framing, one JSON object followed by `\n`.
- `asyncio` keeps peer TCP reads, writes, heartbeat, and terminal input from
  blocking each other.

## Manual HTTP Checks

Login and capture the returned `Set-Cookie` header:

```powershell
curl -i -X POST http://127.0.0.1:2026/login `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Use the cookie with a protected endpoint:

```powershell
curl -i http://127.0.0.1:2026/me `
  -H "Cookie: session_id=<value-from-login>"
```

Unauthenticated protected requests should return `HTTP/1.1 401 Unauthorized`.

## Checks

```powershell
python -m compileall .
```

If `python` is not on PATH in your environment, run the same commands with the
full path to your Python executable.
