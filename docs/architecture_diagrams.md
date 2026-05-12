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

## Tracker And P2P

```text
Central tracker:

+--------+       /submit-info       +-------------------+
| Peer A | -----------------------> | Peer registry     |
| Peer B |       /get-list          | apps/sampleapp.py |
+--------+ <----------------------- +-------------------+

Direct P2P message:

+--------+       JSON over TCP       +--------+
| Peer A | ------------------------> | Peer B |
+--------+                           +--------+
```

## Chat UI

```text
+----------------+       REST polling       +-------------------+
| www/chat.html  | -----------------------> | /chat-state       |
| www/js/chat.js |                          | /chat-message     |
+----------------+ <----------------------- | /channel-create   |
                                           +-------------------+
```
