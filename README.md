# CO3094 Hybrid P2P Chat

This repository contains a standard-library-only hybrid chat demo.  The HTTP
tracker handles login, cookie sessions, peer registration, discovery,
heartbeat, and leave events.  The tracker does not forward chat messages.
Each `peer.py` process is one real peer and sends JSON-line messages directly
to other peers over asyncio TCP sockets.

## Requirements

- Python 3.9 or newer
- Python standard library only
- No Flask, FastAPI, Django, requests, websockets, aiohttp, or external
  frontend framework

## Start The Tracker

PowerShell:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Unix shell:

```sh
python3 start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
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
- `GET /tracker-state`

## Browser Dashboard Demo

Start the tracker, then open:

```text
http://127.0.0.1:2026/login.html
```

Log in as `alice` with password `wonderland`.  The browser dashboard at
`/chat.html` can show the authenticated user, active peers, tracker status,
and peer registration controls.

Important: the browser UI is only a tracker dashboard and demo helper.  It does
not send direct chat messages.  Direct P2P transport is still handled by
`peer.py`.

## Start Three Peers

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

Each peer logs in, preserves the `session_id` cookie, starts a local TCP
listener with `asyncio.start_server`, and registers its address with the
tracker.

## Authoritative P2P Demo

In Alice's terminal:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

Expected result:

- Bob receives the direct message from Alice.
- Bob and Charlie receive the broadcast from Alice.
- The tracker logs only auth/register/list/heartbeat/leave requests.
- No server-forwarded chat route is used.

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

- `apps/sampleapp.py` is the central HTTP tracker and authentication app.
- `peer.py` is the real peer process for Alice, Bob, Charlie, or another user.
- The tracker uses cookies to protect `/submit-info`, `/get-list`,
  `/heartbeat`, `/leave`, and `/tracker-state`.
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

## Checks

```powershell
python -m compileall .
```

If `python` is not on PATH in your environment, run the same command with the
full path to your Python executable.
