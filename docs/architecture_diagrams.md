# Architecture Diagrams

## Backend Request Lifecycle

```text
+---------+       +----------------+       +-----------------+
| Browser | ----> | backend.py     | ----> | httpadapter.py  |
| curl    |       | asyncio server |       | route dispatch  |
+---------+       +----------------+       +-----------------+
                                                   |
                                                   v
                   +----------------+       +-----------------+
                   | response.py    | <---- | apps/sampleapp  |
                   | HTTP builder   |       | route handlers  |
                   +----------------+       +-----------------+
```

## Reverse Proxy

```text
+---------+     Host: app2.local     +------------+
| Client  | -----------------------> | proxy.py   |
+---------+                          +------------+
                                           |
                          round-robin      |
                              +------------+------------+
                              v                         v
                       +--------------+          +--------------+
                       | backend 9002 |          | backend 9003 |
                       +--------------+          +--------------+
```

## Hybrid P2P Architecture (Current)

### Phase 1: Authentication and Peer Discovery

```text
+------------------+                          +-------------------+
| peer.py (Alice)  |  POST /login             | sampleapp.py      |
| terminal process | -----------------------> | HTTP tracker      |
|                  | <---- Set-Cookie -------- | (auth + registry) |
|                  |                          |                   |
|                  |  POST /submit-info       |                   |
|                  | ------[Cookie]---------> |  peer registry    |
|                  |                          |  (in memory)      |
|                  |  GET /get-list           |                   |
|                  | ------[Cookie]---------> |                   |
|                  | <---- peer list --------- |                   |
+------------------+                          +-------------------+
```

### Phase 2: Direct P2P Messaging

```text
+------------------+    asyncio TCP socket    +------------------+
| peer.py (Alice)  | -----------------------> | peer.py (Bob)    |
|                  |   {"type":"hello",...}    |                  |
|                  |   {"type":"direct",...}   |                  |
|                  | <--- {"type":"ack",...} - |                  |
+------------------+                          +------------------+
```

### Phase 3: Broadcast

```text
                           +--> TCP --> peer.py (Bob)
                           |           receives + ACK
peer.py (Alice) -----------+
  asyncio.gather           |
                           +--> TCP --> peer.py (Charlie)
                                       receives + ACK
```

### Browser Dashboard (Tracker Only)

```text
+--------------------+     REST (fetch)     +-------------------+
| www/chat.html      | ------------------> | sampleapp.py      |
| static/js/chat.js  |   /me               | HTTP tracker      |
|                    |   /tracker-state     |                   |
| tracker dashboard  |   /get-list         | auth + registry   |
| (read-only for     |   /submit-info      |                   |
|  chat -- does NOT  |   /heartbeat        |                   |
|  send P2P msgs)    |   /leave            |                   |
+--------------------+   /logout           +-------------------+
```

## P2P Protocol (JSON-Line over TCP)

```text
Sender                                          Receiver
  |                                                |
  |--- {"type":"hello","from":"alice",...} ------->|
  |                                                |  (no ACK required)
  |--- {"type":"direct","from":"alice",            |
  |     "to":"bob","message":"hi",                 |
  |     "message_id":"uuid",...} ----------------->|
  |                                                |  inbox.append(payload)
  |<-- {"type":"ack","from":"bob",                 |
  |     "message_id":"uuid",...} ------------------|
  |                                                |
  |  (connection closed)                           |
```

Message types:

- `hello` — handshake, no ACK required
- `direct` — point-to-point message, expects ACK
- `broadcast` — one-to-many message, expects ACK from each receiver
- `ack` — acknowledgement, matched by `message_id`
- `error` — protocol error from receiver
