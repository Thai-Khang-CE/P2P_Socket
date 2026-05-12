# API Reference

## Authentication

### `POST /login` or `PUT /login`

Form fields:

- `username`
- `password`

Returns:

- `200` with `Set-Cookie`
- `401` for invalid credentials

### `POST /logout` or `PUT /logout`

Clears the session cookie.

### `GET /private`

Requires valid `session_id` cookie.

### `GET /admin`

Requires valid admin session.

## Tracker

### `POST /submit-info`

Fields:

- `username`
- `peer_ip`
- `peer_port`
- `status`
- `channels`

Registers or updates a peer.

### `GET /get-list`

Optional query:

- `channel`
- `include_inactive=true`

Returns active peer list.

### `POST /add-list`

Adds or updates a peer entry.

### `DELETE /add-list`

Removes a peer entry.

## P2P

### `POST /connect-peer`

Fields:

- `local_username`
- `listen_host`
- `listen_port`
- `peer_username`
- `peer_ip`
- `peer_port`

Starts the local peer socket server and optionally connects directly to a remote peer.

### `POST /send-peer`

Fields:

- `local_username`
- `peer_username`
- `peer_ip`
- `peer_port`
- `message`

Sends a direct P2P message.

### `POST /broadcast-peer`

Fields:

- `local_username`
- `message`
- `peers`

If `peers` is omitted, the current tracker peer list is used.

### `POST /disconnect-peer`

Fields:

- `peer_ip`
- `peer_port`

If no peer is provided, all peer connections are closed.

### `GET /peer-inbox`

Returns local direct P2P messages received by this peer.

## Chat UI

### `GET /chat-state`

Query:

- `username`
- `channel`
- `since`

Returns channels, peers, messages and notifications.

### `GET /chat-history`

Query:

- `channel`
- `limit`

Returns message history for one channel.

### `POST /channel-create`

Fields:

- `username`
- `channel`

Creates and joins a channel.

### `POST /channel-join`

Fields:

- `username`
- `channel`

Joins a channel.

### `POST /channel-leave`

Fields:

- `username`
- `channel`

Leaves a channel.

### `POST /chat-message`

Fields:

- `username`
- `channel`
- `message`

Adds a message to channel history.
