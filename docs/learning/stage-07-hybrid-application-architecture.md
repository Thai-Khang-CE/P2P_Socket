# Stage 07 - Hybrid application architecture: tracker + direct P2P chat

## 1. Stage objective

Mục tiêu của stage này là trả lời thật rõ:

> Why is this application hybrid, and where exactly does client-server stop and P2P begin?

Project này là **hybrid chat application** vì nó kết hợp hai mô hình:

- **Client-server** cho login, cookie session, peer registration, peer discovery, heartbeat, leave, dashboard state.
- **Peer-to-peer (P2P)** cho live chat messages giữa các peer process.

Ranh giới quan trọng:

```text
Client-server stops at:
  tracker gives authenticated identity + active peer endpoint list

P2P begins when:
  one peer opens a direct TCP connection to another peer_ip:peer_port
  and sends live chat payload over that socket
```

Trong source hiện tại:

- `apps/sampleapp.py` là tracker server.
- `peer.py` là peer node thật.
- Browser UI là tracker dashboard, không phải live P2P chat client.
- Live message không đi qua tracker.
- `/connect-peer` chỉ trả endpoint của target peer, không mở socket, không forward message.
- `/send-peer`, `/broadcast-peer`, `/peer-inbox` trả `410 Gone` để chứng minh server-side message relay không còn là đường chat chính.

## 2. Theory needed before understanding this stage

### Client-server paradigm

Client-server là mô hình có một server trung tâm cung cấp service cho nhiều client.

Ví dụ:

```text
Browser/peer.py -> HTTP tracker server
```

Client gửi request, server xử lý và trả response.

Ưu điểm:

- Dễ quản lý authentication.
- Dễ lưu state tập trung.
- Dễ discovery: client hỏi server "ai đang online?".
- Dễ kiểm soát quyền truy cập.

Nhược điểm:

- Server có thể thành bottleneck.
- Nếu mọi live chat đi qua server, server phải gánh toàn bộ message traffic.
- Server là single point of failure cho các chức năng tập trung.

Trong project này, client-server dùng cho tracker duties, không dùng để relay live chat.

### Peer-to-peer paradigm

Peer-to-peer nghĩa là các node nói chuyện trực tiếp với nhau. Mỗi peer vừa có thể gửi request như client, vừa có thể nhận connection như server.

Ví dụ:

```text
peer.py Alice <---- TCP socket ----> peer.py Bob
```

Không có server trung tâm đứng giữa message.

Ưu điểm:

- Live message không tải lên tracker.
- Message đi đường ngắn hơn trong demo local/LAN.
- Mỗi peer tự quản inbox/connection của mình.
- Có thể tiếp tục một số direct connection nếu tracker tạm mất sau khi peers đã biết endpoint nhau.

Nhược điểm:

- Peer phải mở listen socket.
- Peer discovery cần cơ chế hỗ trợ.
- NAT/firewall có thể làm direct connection khó hơn trong hệ thống thực.
- Mỗi peer phải xử lý protocol, ACK, timeout, disconnect.

### Hybrid architecture

Hybrid architecture kết hợp client-server và P2P.

Server trung tâm không biến mất. Nó giữ vai trò tracker:

```text
auth + discovery + presence
```

Nhưng data path của live chat là:

```text
peer -> peer
```

Trong project:

```text
Tracker plane:
  HTTP /login, /submit-info, /get-list, /connect-peer, /heartbeat, /leave

Chat data plane:
  asyncio TCP socket from peer.py to peer.py
```

### Tracker server

Tracker server là server trung tâm giúp peer tìm nhau.

Tracker thường biết:

- user nào đã login;
- peer nào đang online;
- mỗi peer listen ở IP/port nào;
- peer thuộc channel nào;
- last_seen/heartbeat gần nhất.

Tracker không nhất thiết biết:

- nội dung live chat;
- inbox của từng peer;
- socket direct giữa peers.

Trong project, tracker là `apps/sampleapp.py` chạy qua `start_sampleapp.py`.

### Peer discovery

Peer discovery là quá trình một peer tìm endpoint của peer khác.

Ví dụ Alice muốn gửi Bob:

```text
Alice asks tracker:
  "Bob đang ở IP/port nào?"

Tracker replies:
  bob -> 127.0.0.1:9002

Alice opens TCP:
  127.0.0.1:9002
```

Project hỗ trợ discovery qua:

- `GET /get-list`: lấy danh sách active peers.
- `POST /connect-peer`: lấy endpoint của một target peer cụ thể.

Trong `peer.py`, direct send hiện dùng `get_list()` + `find_peer(username)`.

### Direct peer connection

Direct peer connection là socket mở thẳng từ peer gửi đến peer nhận.

Trong `peer.py`:

```python
reader, writer = await asyncio.open_connection(host, port)
```

Sau khi connect:

```text
sender writes hello JSON-line
sender writes direct/broadcast JSON-line
receiver handles payload
receiver writes ack JSON-line
sender waits for matching ack
```

Tracker không nằm trong đoạn này.

### Why live messages should not always go through centralized server

Nếu mọi live message đi qua server:

```text
Alice -> tracker -> Bob
```

thì tracker phải:

- nhận message;
- validate recipient;
- lưu/forward message;
- quản lý inbox hoặc delivery;
- chịu toàn bộ traffic;
- trở thành bottleneck.

Assignment hybrid/P2P muốn chứng minh ý khác:

```text
Tracker only helps peers find each other.
Peers carry live traffic themselves.
```

Điều này làm ranh giới kiến trúc rõ hơn:

- Server trung tâm cho control plane.
- Direct socket cho data plane.

### Why each peer must act as both client and server

Mỗi peer phải là **client** vì nó cần:

- login vào tracker;
- register endpoint;
- heartbeat;
- ask tracker for peers;
- open connection to target peer;
- send message.

Mỗi peer phải là **server** vì nó cần:

- listen ở `listen_host:listen_port`;
- accept inbound TCP connection từ peer khác;
- read JSON-line payload;
- append inbox;
- send ACK.

Trong `peer.py`, `PeerNode.start()` mở server:

```python
self.server = await asyncio.start_server(
    self.handle_peer,
    self.listen_host,
    self.listen_port,
)
```

Và `send_payload()` mở client connection:

```python
reader, writer = await asyncio.open_connection(host, port)
```

Đó là bản chất peer: vừa client, vừa server.

## 3. Where this concept appears in the assignment requirement

Trong repo hiện tại, hybrid requirement xuất hiện ở:

- `README.md`: "HTTP tracker handles login, cookie sessions, peer registration, discovery, heartbeat, leave. The tracker does not forward chat messages."
- `peer.py`: docstring nói mỗi terminal là một peer process, login tracker rồi gửi JSON-line messages trực tiếp qua asyncio TCP sockets.
- `apps/sampleapp.py`: tracker routes và deprecated server-forwarded endpoints.
- `docs/architecture_diagrams.md`: Phase 1 tracker, Phase 2 direct P2P, Phase 3 broadcast.

Mapping sang requirement:

- Login/session: `POST /login`, `GET /me`.
- Peer registration: `POST /submit-info`.
- Peer discovery: `GET /get-list`, `POST /connect-peer`.
- Presence: `POST /heartbeat`, `POST/DELETE /leave`.
- Dashboard state: `GET /tracker-state`, `GET /chat-state`.
- Direct P2P live chat: `peer.py` methods `send_direct()`, `send_payload()`, `handle_peer()`.
- Broadcast/channel-style message: `peer.py:broadcast()` sends direct TCP payload to each peer.

Cần kiểm tra thêm: source hiện tại có `channel` metadata và broadcast payload contains `channel`, nhưng không enforce channel filtering in `peer.py:broadcast()`. Broadcast sends to all other active peers returned by tracker, regardless of channel. Channel-aware broadcast would need extra filtering if required by rubric.

## 4. Related files in the project

- `start_sampleapp.py`: starts tracker HTTP server.
- `apps/sampleapp.py`: tracker application, authentication, session, peer registry, discovery endpoints.
- `peer.py`: actual peer node, tracker client, local TCP server, direct message sender, broadcast sender.
- `daemon/backend.py`: runs HTTP tracker backend using asyncio.
- `daemon/httpadapter.py`: dispatches HTTP tracker requests to route handlers.
- `www/login.html`, `www/chat.html`, `static/js/chat.js`: browser tracker dashboard.
- `README.md`: current demo instructions and expected proof.
- `docs/architecture_diagrams.md`: existing high-level diagrams.

## 5. Detailed source-code reading notes

### 5.1 Which existing server can act as tracker

The existing tracker is:

```text
apps/sampleapp.py
```

It is launched by:

```text
start_sampleapp.py
```

`apps/sampleapp.py` keeps central state:

```python
SESSIONS = {}
PEERS = {}
CHAT_CHANNELS = {"general": {"name": "general", "members": set()}}
```

Tracker responsibilities in source:

- authenticate users;
- issue session cookies;
- protect endpoints;
- register peer endpoint;
- return peer list;
- return target peer endpoint;
- update heartbeat;
- mark peer offline;
- serve dashboard state.

Tracker non-responsibilities:

- not storing live chat history;
- not forwarding direct messages;
- not owning peer inbox;
- not opening P2P sockets on behalf of peers.

### 5.2 Client-server initialization APIs

These APIs belong to the client-server initialization/control plane:

| API | Role |
|---|---|
| `POST /login` | Authenticate user and issue session cookie |
| `POST /logout` | Clear session |
| `GET /me` | Check current logged-in user |
| `POST /submit-info` | Register/update this peer endpoint |
| `GET /get-list` | Discover active peers |
| `POST /connect-peer` | Return target peer endpoint for direct connection setup |
| `POST /heartbeat` | Refresh peer presence |
| `POST/DELETE /leave` | Mark peer offline |
| `GET /tracker-state` | Dashboard state |
| `GET /chat-state` | Dashboard compatibility alias |

These requests are HTTP client-server requests:

```text
peer.py or browser -> sampleapp.py tracker
```

They do not carry live chat messages.

### 5.3 `POST /connect-peer` in current source

Current `apps/sampleapp.py` has:

```python
@app.route("/connect-peer", methods=["POST"])
def connect_peer(headers, body, request):
    ...
    peer = find_peer_by_username(target, channel=channel)
    ...
    payload = dict(peer)
    payload["note"] = (
        "Use this endpoint information to open a direct TCP socket from "
        "peer.py. The tracker does not forward chat messages."
    )
    return json_response(payload)
```

Meaning:

```text
/connect-peer does not connect peers by itself.
It returns peer_ip and peer_port.
The caller must open the TCP socket.
```

This endpoint is still client-server control plane.

### 5.4 Deprecated server-forwarded chat APIs

These endpoints return legacy/deprecated response:

```python
@app.route("/send-peer", methods=["POST"])
def send_peer(...):
    return legacy_peer_response()

@app.route("/broadcast-peer", methods=["POST"])
def broadcast_peer(...):
    return legacy_peer_response()

@app.route("/peer-inbox", methods=["GET"])
def peer_inbox(...):
    return legacy_peer_response()
```

`legacy_peer_response()` says direct chat is implemented by `peer.py`.

This is important evidence:

```text
Server-side message forwarding is intentionally rejected.
```

### 5.5 Peer node components

`PeerNode` in `peer.py` contains:

```python
self.username
self.password
self.listen_host
self.listen_port
self.tracker
self.channel
self.server
self.inbox
self.connections
self.lock
self.heartbeat_task
self.running
```

Conceptually, a peer node needs:

- identity: username/password;
- tracker client: HTTP API calls;
- local server: accept inbound peer sockets;
- outbound client: connect to other peer sockets;
- protocol encoder/decoder: JSON-line payloads;
- inbox: received direct/broadcast payloads;
- presence loop: heartbeat;
- CLI loop: user commands;
- graceful shutdown: leave tracker and close server.

### 5.6 TrackerClient: peer as HTTP client

`TrackerClient` uses `http.client.HTTPConnection` to talk to tracker.

Methods:

```python
login()
me()
register()
get_list()
heartbeat()
leave()
request()
_request_sync()
_store_cookie()
```

It stores cookie:

```python
self.session_cookie = "session_id={}".format(morsel.value)
```

It sends cookie later:

```python
headers["Cookie"] = self.session_cookie
```

This is client-server behavior.

### 5.7 PeerNode startup

`PeerNode.start()`:

```python
user = await self.tracker.login(self.username, self.password)
self.server = await asyncio.start_server(
    self.handle_peer,
    self.listen_host,
    self.listen_port,
)
await self.register_self()
self.heartbeat_task = asyncio.create_task(self.heartbeat_loop())
```

Startup sequence:

```text
login to tracker
start local TCP server
register listen endpoint with tracker
start heartbeat loop
```

This sequence shows why the app is hybrid:

- first half is client-server;
- second half prepares P2P server role.

### 5.8 Peer discovery in `peer.py`

Direct message starts with discovery:

```python
async def find_peer(self, username):
    for peer in await self.tracker.get_list():
        if peer.get("username") == username:
            return peer
    raise TrackerError(...)
```

Input:

```text
recipient username, e.g. bob
```

Output:

```python
{
    "username": "bob",
    "peer_ip": "127.0.0.1",
    "peer_port": 9002,
    "status": "online",
    "channels": ["general"],
    "last_seen": ...
}
```

After this point, the tracker has done its job for that send.

### 5.9 Direct P2P send

`send_direct()`:

```python
peer = await self.find_peer(recipient)
payload = PeerMessage(
    type="direct",
    sender=self.username,
    recipient=recipient,
    channel=self.channel,
    message=message,
).to_payload()
return await self.send_payload(peer, payload)
```

`send_payload()`:

```python
reader, writer = await asyncio.open_connection(host, port)
...
await self.write_json(writer, {"type": "hello", ...})
await self.write_json(writer, payload)
...
line = await asyncio.wait_for(reader.readline(), timeout=remaining)
```

This is P2P live chat:

```text
peer.py -> peer.py
```

not:

```text
peer.py -> tracker -> peer.py
```

### 5.10 Peer receiving live message

Receiver side:

```python
async def handle_peer(self, reader, writer):
    line = await reader.readline()
    payload = json.loads(line.decode("utf-8"))
    await self.handle_payload(key, payload, writer)
```

`handle_payload()`:

```python
if message_type in {"direct", "broadcast"}:
    if message_type == "direct" and payload.get("to") != self.username:
        await self.write_json(writer, self.error_payload(...))
        return

    self.inbox.append(payload)
    print("\n[{}] {}: {}\n> ".format(...))
    await self.write_json(writer, {"type": "ack", ...})
```

Receiver stores message in local process memory:

```python
self.inbox
```

Tracker does not store this inbox.

### 5.11 Channel message flow in current source

`PeerMessage` includes:

```python
channel: str = DEFAULT_CHANNEL
```

Payload contains:

```python
"channel": self.channel
```

`register_self()` registers peer with:

```python
channels=[self.channel]
```

Tracker stores channels as metadata:

```python
"channels": channels
```

`GET /get-list` can filter by query param `channel`.

But current `PeerNode.broadcast()` does:

```python
peers = [
    peer
    for peer in await self.tracker.get_list()
    if peer.get("username") != self.username
]
```

It does not pass channel filter to tracker and does not filter peer channels locally.

Therefore current channel message behavior is:

```text
Broadcast payload includes channel metadata,
but broadcast is sent to all other active peers returned by /get-list.
```

Cần kiểm tra thêm: if assignment requires strict channel broadcast, implementation may need channel filtering. This stage documents current source behavior, not a new feature.

### 5.12 Browser UI interaction

Browser dashboard interacts with tracker:

- login form -> `/login`;
- current user -> `/me`;
- peer list -> `/get-list`;
- tracker state -> `/tracker-state`;
- manual peer registration -> `/submit-info`;
- heartbeat button -> `/heartbeat`;
- leave button -> `/leave`;
- logout -> `/logout`.

Browser does not open direct TCP sockets to peers in this source. Browser is not the live chat transport.

Meaning:

```text
Browser UI = tracker dashboard
peer.py terminal = real P2P chat node
```

### 5.13 What must be logged to prove true P2P

To prove true P2P, show:

1. Tracker logs only control-plane requests:

```text
POST /login
POST /submit-info
GET /get-list
POST /heartbeat
POST /leave
```

2. Tracker logs do not show live message body:

```text
hello bob
hello everyone
```

3. Receiver peer terminal prints:

```text
[direct] alice: hello bob
[broadcast] alice: hello everyone
```

4. Sender peer terminal prints ACK result:

```text
sent to bob ack=True
broadcast to 2 peer(s): 2 succeeded, 0 failed
```

5. Deprecated relay endpoints return `410`:

```text
POST /send-peer -> 410 Gone
POST /broadcast-peer -> 410 Gone
GET /peer-inbox -> 410 Gone
```

6. Optionally show `/connect-peer` returns only endpoint:

```json
{
  "username": "bob",
  "peer_ip": "127.0.0.1",
  "peer_port": 9002,
  "note": "Use this endpoint information to open a direct TCP socket..."
}
```

This evidence demonstrates:

```text
tracker helps discover
peer socket carries message
```

## 6. Execution/data flow explanation

### Diagram 1: Login and peer registration flow

```text
Alice peer.py                                      HTTP tracker
terminal process                                  apps/sampleapp.py
     |                                                   |
     |  POST /login                                     |
     |  {"username":"alice","password":"wonderland"}     |
     |-------------------------------------------------->|
     |                                                   | validate USERS
     |                                                   | create session_id
     |  200 OK + Set-Cookie: session_id=...              |
     |<--------------------------------------------------|
     |                                                   |
     |  asyncio.start_server(handle_peer, 127.0.0.1:9001)|
     |  local peer TCP server is now listening           |
     |                                                   |
     |  POST /submit-info                               |
     |  Cookie: session_id=...                          |
     |  {"peer_ip":"127.0.0.1","peer_port":9001}         |
     |-------------------------------------------------->|
     |                                                   | PEERS["alice@127.0.0.1:9001"] = ...
     |  200 OK {"message":"Peer registered", ...}        |
     |<--------------------------------------------------|
```

What this proves:

```text
client-server phase registers identity and endpoint.
No chat message has been sent yet.
```

### Diagram 2: Peer discovery flow

```text
Alice peer.py                         HTTP tracker
     |                                      |
     |  GET /get-list                       |
     |  Cookie: session_id=...              |
     |------------------------------------->|
     |                                      | cleanup inactive peers
     |                                      | read PEERS
     |  200 OK                              |
     |  {"peers":[                          |
     |    {"username":"bob",                |
     |     "peer_ip":"127.0.0.1",           |
     |     "peer_port":9002}                |
     |  ]}                                  |
     |<-------------------------------------|
     |                                      |
     | Alice now knows Bob endpoint         |
```

Alternative with `/connect-peer`:

```text
Alice peer.py                         HTTP tracker
     |                                      |
     | POST /connect-peer                   |
     | {"username":"bob"}                   |
     |------------------------------------->|
     |                                      | find_peer_by_username("bob")
     | 200 OK {"peer_ip":"127.0.0.1",       |
     |         "peer_port":9002, ...}       |
     |<-------------------------------------|
```

What this proves:

```text
tracker returns location information only.
tracker does not connect sockets for peers.
```

### Diagram 3: Direct P2P message flow

```text
Alice peer.py                                         Bob peer.py
127.0.0.1:9001                                        127.0.0.1:9002
     |                                                     |
     |  asyncio.open_connection("127.0.0.1", 9002)         |
     |---------------------------------------------------->|
     |                                                     | handle_peer(reader, writer)
     |  {"type":"hello","from":"alice",...}\n              |
     |---------------------------------------------------->|
     |                                                     | record connection sender
     |  {"type":"direct",                                  |
     |   "from":"alice",                                   |
     |   "to":"bob",                                      |
     |   "message":"hello bob",                            |
     |   "message_id":"uuid",                              |
     |   "channel":"general"}\n                            |
     |---------------------------------------------------->|
     |                                                     | validate to == "bob"
     |                                                     | inbox.append(payload)
     |                                                     | print [direct] alice: hello bob
     |  {"type":"ack","from":"bob","message_id":"uuid"}\n  |
     |<----------------------------------------------------|
     |                                                     |
     | Alice sees ack=True                                 |
```

Notice what is absent:

```text
No POST /send-peer to tracker.
No tracker relay.
No tracker inbox.
```

### Diagram 4: Channel message flow

Current source channel/broadcast flow:

```text
Alice peer.py                         HTTP tracker
     |                                      |
     | GET /get-list                        |
     |------------------------------------->|
     |                                      | returns active peers
     | peers: Bob, Charlie                  |
     |<-------------------------------------|
     |
     | create payload:
     | {"type":"broadcast",
     |  "from":"alice",
     |  "channel":"general",
     |  "message":"hello everyone",
     |  "message_id":"uuid"}
     |
     |---------------- TCP ----------------> Bob peer.py
     |                                      Bob prints [broadcast] alice: ...
     |<--------------- ACK ----------------|
     |
     |---------------- TCP ----------------> Charlie peer.py
     |                                      Charlie prints [broadcast] alice: ...
     |<--------------- ACK ----------------|
     |
     | Alice prints:
     | broadcast to 2 peer(s): 2 succeeded, 0 failed
```

Important current-source detail:

```text
Channel is included in payload and registration metadata.
Current peer.py broadcast does not strictly filter recipients by channel.
```

If strict channel semantics are required, the intended architecture would be:

```text
Alice asks tracker for peers in channel=general
  -> tracker returns only general peers
Alice sends direct TCP broadcast payload to those peers
```

But current source should be described honestly as metadata + all-active-peer broadcast.

## 7. Important functions/classes and their role

| Function/class/constant | File | Role |
|---|---|---|
| `TrackerClient` | `peer.py` | HTTP client for login/register/discovery/heartbeat/leave |
| `TrackerClient.login()` | `peer.py` | Client-server login to tracker |
| `TrackerClient.register()` | `peer.py` | Register peer endpoint with tracker |
| `TrackerClient.get_list()` | `peer.py` | Discover active peers from tracker |
| `PeerMessage` | `peer.py` | Build JSON-line direct/broadcast payload |
| `PeerNode` | `peer.py` | Actual peer: local server + outbound client + CLI |
| `PeerNode.start()` | `peer.py` | Login, start local TCP server, register, start heartbeat |
| `PeerNode.handle_peer()` | `peer.py` | Accept inbound peer messages |
| `PeerNode.handle_payload()` | `peer.py` | Process hello/direct/broadcast/ack/error payload |
| `PeerNode.send_direct()` | `peer.py` | Discover target and send direct message |
| `PeerNode.broadcast()` | `peer.py` | Send broadcast payload to all other active peers |
| `PeerNode.send_payload()` | `peer.py` | Open direct TCP socket, write payload, wait for ACK |
| `PeerNode.write_json()` | `peer.py` | JSON-line framing writer |
| `USERS` | `apps/sampleapp.py` | In-memory users |
| `SESSIONS` | `apps/sampleapp.py` | In-memory login sessions |
| `PEERS` | `apps/sampleapp.py` | In-memory peer registry |
| `POST /submit-info` | `apps/sampleapp.py` | Register endpoint for authenticated peer |
| `GET /get-list` | `apps/sampleapp.py` | Return active peer list |
| `POST /connect-peer` | `apps/sampleapp.py` | Return target endpoint only |
| `POST /heartbeat` | `apps/sampleapp.py` | Refresh peer presence |
| `POST/DELETE /leave` | `apps/sampleapp.py` | Mark peer offline |
| `legacy_peer_response()` | `apps/sampleapp.py` | Reject server-forwarded live chat APIs |

## 8. Common mistakes/misunderstandings

- Nghĩ tracker là chat relay. Không đúng: tracker không forward live messages.
- Nghĩ browser dashboard là P2P chat client. Không đúng: browser chỉ gọi tracker REST APIs.
- Nghĩ `/connect-peer` tự kết nối hai peer. Không đúng: nó chỉ trả endpoint.
- Nghĩ `/send-peer` là live chat API hiện tại. Không đúng: endpoint này bị deprecated/rejected.
- Nghĩ peer chỉ là client. Không đúng: peer phải listen như server để nhận message.
- Nghĩ peer chỉ là server. Không đúng: peer cũng là client khi login tracker và connect outbound to another peer.
- Nghĩ channel hiện tại là full chat room enforcement. Source hiện tại dùng channel mostly as metadata; broadcast does not strictly filter by channel.
- Nghĩ ACK đến từ tracker. Không đúng: ACK đến từ receiving peer over direct TCP socket.
- Nghĩ tracker state contains inbox. Không đúng: inbox nằm trong each `peer.py` process.
- Nghĩ restart tracker xóa peer inbox. Restart tracker xóa sessions/PEERS, nhưng inbox đang trong peer process memory; nếu peer process còn chạy, local inbox vẫn ở process đó.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] I can explain tracker server responsibility.
- [ ] I can explain peer responsibility.
- [ ] I can explain direct peer-to-peer messaging.
- [ ] I can explain why tracker must not relay live messages.
- [ ] I can draw the hybrid architecture.
- [ ] I know what evidence/logs prove P2P.
- [ ] Tôi biết client-server phase gồm login, register, discovery, heartbeat, leave.
- [ ] Tôi biết P2P phase bắt đầu khi `peer.py` gọi `asyncio.open_connection(peer_ip, peer_port)`.
- [ ] Tôi biết receiver peer dùng `handle_peer()` để đọc JSON-line messages.
- [ ] Tôi biết ACK được gửi từ receiving peer, không phải tracker.
- [ ] Tôi biết browser dashboard chỉ quan sát tracker state.
- [ ] Tôi biết channel trong source hiện tại là metadata, chưa phải strict channel delivery.

## 10. Suggested test commands or observation commands if applicable

Start tracker:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Open browser dashboard:

```text
http://127.0.0.1:2026/login.html
```

Start three peers:

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
python peer.py --username bob --password wonderland --listen-port 9002
python peer.py --username charlie --password wonderland --listen-port 9003
```

In Alice terminal:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

Expected proof:

```text
Bob terminal:
  [direct] alice: hello bob
  [broadcast] alice: hello everyone

Charlie terminal:
  [broadcast] alice: hello everyone

Alice terminal:
  sent to bob ack=True
  broadcast to 2 peer(s): 2 succeeded, 0 failed

Tracker logs:
  show login/register/list/heartbeat
  do not show "hello bob" as a forwarded chat message
```

Check deprecated relay endpoints:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/send-peer
curl.exe -i -X POST http://127.0.0.1:2026/broadcast-peer
curl.exe -i http://127.0.0.1:2026/peer-inbox
```

Check `/connect-peer` returns endpoint only:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/connect-peer -H "Content-Type: application/json" -H "Cookie: session_id=<alice-session>" -d "{\"username\":\"bob\"}"
```

Observe code paths:

```powershell
rg -n "connect_peer|send_peer|broadcast_peer|legacy_peer_response|submit_info|get_list|heartbeat|leave" apps/sampleapp.py
rg -n "class PeerNode|send_direct|broadcast|send_payload|handle_peer|handle_payload|open_connection|start_server" peer.py
```

## 11. Suggested commit message

Suggested commit message:

```text
docs: add stage 07 hybrid application architecture
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-07-hybrid-application-architecture.md
git commit -m "docs: add stage 07 hybrid application architecture" -- docs/learning/stage-07-hybrid-application-architecture.md
```
