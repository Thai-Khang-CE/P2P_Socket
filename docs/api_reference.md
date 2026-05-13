# API Reference

## Authentication

### `POST /login`

Accepts JSON or form-encoded body.

Fields:

- `username`
- `password`

Returns:

- `200` with JSON `{"username": "...", "role": "..."}` and
  `Set-Cookie: session_id=...; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax`
- `401` for invalid credentials

### `POST /logout`

Clears the session cookie with `Max-Age=0`.

### `GET /me`

Requires valid `session_id` cookie.

Returns `{"username": "...", "role": "..."}` or `401`.

### `GET /private`

Requires valid `session_id` cookie.  Returns a protected user-only response.

### `GET /admin`

Requires valid admin session (`role == "admin"`).  Returns `403` if the
role is insufficient.

## Tracker

All tracker endpoints require a valid `session_id` cookie and return `401`
if the cookie is missing or expired.

### `POST /submit-info`

Registers or updates the peer endpoint owned by the logged-in user.
The username is taken from the session, not from the request body.

Fields:

- `peer_ip` — IP address of the peer listener
- `peer_port` — port number (converted to int)
- `status` — one of `online`, `away`, `busy`, `offline` (default: `online`)
- `channels` — list or comma-separated string (default: `["general"]`)

Returns:

- `200` with `{"message": "Peer registered", "peers": [...]}`

### `GET /get-list`

Returns the active peer list.

Optional query parameters:

- `channel` — filter by channel name
- `include_inactive=true` — include offline peers

Returns:

- `200` with `{"count": N, "peers": [...]}`

Each peer object contains: `username`, `peer_ip`, `peer_port`, `status`,
`channels`, `last_seen`.

### `POST /heartbeat`

Refreshes `last_seen` for the logged-in user's peer entry.

Fields:

- `peer_ip` — optional, filter by IP
- `peer_port` — optional, filter by port
- `status` — optional, must be one of `online`, `away`, `busy`, `offline`

Returns:

- `200` with `{"refreshed": N, "peers": [...]}`
- `404` if no matching peer is registered

### `POST /leave` or `DELETE /leave`

Marks the logged-in user's peer as offline.

Fields:

- `peer_ip` — optional
- `peer_port` — optional

Returns:

- `200` with `{"left": N, "peers": [...]}`

### `POST /add-list` or `DELETE /add-list`

Compatibility alias.  `POST` delegates to `/submit-info`, `DELETE` delegates
to `/leave`.

### `GET /tracker-state`

Returns the full tracker dashboard payload for the browser UI.

Returns:

- `200` with `{"user": {...}, "peers": [...], "channels": [...], "note": "..."}`

### `GET /chat-state`

Compatibility alias for `/tracker-state`.  Returns the same payload.

## Deprecated Endpoints (HTTP 410 Gone)

The following endpoints existed in earlier phases when the tracker forwarded
P2P messages server-side.  In the current hybrid architecture, direct chat is
implemented by `peer.py` over asyncio TCP sockets.  These endpoints are
retained only for compatibility and always return:

```json
{
  "error": "Deprecated",
  "message": "Direct chat is implemented by peer.py. The tracker does not forward peer messages."
}
```

- `POST /connect-peer` — rejected
- `POST /send-peer` — rejected
- `POST /broadcast-peer` — rejected
- `GET /peer-inbox` — rejected

## Utility Endpoints

### `POST /echo`

Echoes a JSON payload.  Used for basic framework testing.

### `POST /hello`

Returns a small static JSON object.

### `GET /async-hello`

Returns a small JSON object from an async route handler.
