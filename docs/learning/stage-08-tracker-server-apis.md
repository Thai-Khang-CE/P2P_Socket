# Stage 08 - Tracker server APIs: client-server control plane, not live chat

## 1. Stage objective

Mục tiêu của stage này là trả lời:

> What APIs does the centralized server need, and why are they not the same as live chat?

Trong hybrid chat architecture, centralized server là **tracker server**. Nó không nên là nơi relay live chat messages. Nó chỉ nên giữ metadata để peers có thể:

- login;
- publish endpoint;
- discover peers;
- join/track channel metadata;
- refresh presence;
- leave/cleanup;
- obtain target endpoint before direct P2P connection.

Ranh giới:

```text
Tracker API = client-server control plane
Live chat   = P2P data plane
```

Nếu Alice gửi message cho Bob:

```text
Alice -> tracker -> Bob
```

thì đó là server-relay chat, không còn là true P2P live messaging.

Thiết kế đúng cho hybrid:

```text
Alice -> tracker: "Bob ở đâu?"
tracker -> Alice: "Bob ở 127.0.0.1:9002"
Alice -> Bob: direct TCP message
```

## 2. Theory needed before understanding this stage

### What a tracker server is

Tracker server là server trung tâm giữ metadata về peers. Nó giúp peer tìm nhau.

Tracker thường trả lời các câu hỏi:

- User này đã login chưa?
- Peer này đang listen ở IP/port nào?
- Peer này còn online không?
- Peer này ở channel nào?
- Danh sách active peers là gì?
- Target peer để connect trực tiếp là ai và endpoint nào?

Tracker không nên trả lời bằng cách:

- nhận live message rồi forward cho peer khác;
- lưu inbox live chat của tất cả peer;
- trở thành trung tâm vận chuyển mọi chat payload.

Trong project hiện tại, tracker là `apps/sampleapp.py`, chạy qua `start_sampleapp.py`.

### Peer registration

Peer registration là lúc một peer báo với tracker:

```text
Tôi là alice.
Tôi đang listen ở 127.0.0.1:9001.
Tôi online.
Tôi tham gia channel general.
```

Tracker lưu metadata này vào active peer registry.

Trong source hiện tại:

```python
PEERS[key] = {
    "username": username,
    "peer_ip": peer_ip,
    "peer_port": peer_port,
    "status": status,
    "channels": channels,
    "last_seen": time.time(),
}
```

Quan trọng: `username` phải lấy từ authenticated session, không lấy từ body client gửi. Nếu client tự gửi `username`, nó có thể giả mạo người khác.

### Peer discovery

Peer discovery là lúc một peer hỏi tracker để biết peer khác đang ở đâu.

Có hai kiểu:

```text
GET /get-list
  -> lấy danh sách active peers

POST /connect-peer
  -> lấy endpoint của một target peer cụ thể
```

Sau discovery, live message phải đi qua direct peer socket.

### Active peer list

Active peer list là danh sách peers đang online/available.

Source hiện tại coi các status này là active:

```python
ACTIVE_PEER_STATUSES = {"online", "away", "busy"}
```

Peer có status `offline` hoặc quá TTL sẽ bị cleanup.

Active peer list không phải inbox và không phải chat history. Nó chỉ là directory.

### Heartbeat or last_seen

Heartbeat là request định kỳ từ peer đến tracker để nói:

```text
Tôi vẫn còn sống.
```

Tracker update:

```python
peer["last_seen"] = time.time()
```

Nếu peer không heartbeat trong `PEER_TTL_SECONDS`, tracker có thể remove peer khỏi active registry.

Trong project:

```python
PEER_TTL_SECONDS = 300
```

### Channel metadata

Channel metadata mô tả peer thuộc channel nào:

```python
"channels": ["general"]
```

Tracker có thể dùng channel để:

- list channels;
- filter peer discovery by channel;
- record membership;
- help sender know which peers belong to a channel.

Nhưng channel metadata không đồng nghĩa tracker phải relay channel messages. Tracker có thể nói:

```text
Các peer trong channel general là Bob và Charlie.
```

Sau đó Alice vẫn gửi direct TCP đến Bob và Charlie.

### Why tracker stores metadata but should not relay live chat messages

Tracker metadata nhỏ và ít thay đổi:

- username;
- IP/port;
- status;
- channels;
- last_seen.

Live chat traffic có thể nhiều và liên tục:

- direct messages;
- broadcast messages;
- ACKs;
- retries;
- disconnect handling.

Nếu tracker relay live chat, tracker trở thành bottleneck và làm mờ mục tiêu P2P của assignment.

Hybrid design tốt:

```text
Tracker:
  who/where/online/channel metadata

Peer:
  actual chat transport and delivery
```

## 3. Where this concept appears in the assignment requirement

Các API tracker thường thuộc phần client-server initialization/control plane của hybrid chat assignment:

- `/login`
- `/submit-info`
- `/add-list`
- `/get-list`
- `/connect-peer`
- `/channels`
- `/channels/join`
- `/channels/my`

Trong source hiện tại:

- Có `apps/sampleapp.py`.
- Không thấy `apps/chatapp.py`.
- Đã có `/login`, `/submit-info`, `/add-list`, `/get-list`, `/connect-peer`.
- Có channel metadata helpers như `CHAT_CHANNELS`, `parse_channels()`, `channel_list()`.
- Chưa thấy route `/channels`, `/channels/join`, `/channels/my`.

Cần kiểm tra thêm: nếu requirement chính thức bắt buộc `/channels*`, source hiện tại cần implementation ở app layer, nhưng stage này chỉ thiết kế/giải thích, không implement code.

## 4. Related files in the project

- `apps/sampleapp.py`: current tracker server implementation.
- `apps/chatapp.py`: likely target name in assignment design, but not present in current repo.
- `daemon/asynaprous.py`: registers route handlers with `@app.route(...)`.
- `daemon/httpadapter.py`: dispatches parsed HTTP requests to route handlers.
- `daemon/request.py`: parses method/path/headers/body/cookies/query params.
- `daemon/response.py`: builds JSON HTTP responses from route return values.
- `peer.py`: consumes tracker APIs from peer process.

Framework flow:

```text
@app.route(...)
  -> AsynapRous stores handler in routes
  -> HttpAdapter dispatches request
  -> handler reads Request/body/session
  -> handler returns json_response(...)
  -> Response builds HTTP bytes
```

## 5. Detailed source-code reading notes

### 5.1 Current tracker state in `apps/sampleapp.py`

Important in-memory state:

```python
SESSION_COOKIE = "session_id"
SESSION_TTL_SECONDS = 3600
PEER_TTL_SECONDS = 300
ACTIVE_PEER_STATUSES = {"online", "away", "busy"}

USERS = {...}
SESSIONS = {}
PEERS = {}
CHAT_CHANNELS = {"general": {"name": "general", "members": set()}}
```

Meaning:

- `USERS`: demo credential store.
- `SESSIONS`: session ID -> authenticated user data.
- `PEERS`: peer endpoint registry.
- `CHAT_CHANNELS`: known channel metadata.

All are in memory. Restart tracker clears state.

### 5.2 Current helper functions

`parse_body(body, headers)`:

- Parses JSON or form-encoded body.
- Used by `/login`, `/submit-info`, `/heartbeat`, `/leave`, `/connect-peer`.

`parse_channels(value)`:

- Accepts list or comma-separated string.
- Returns normalized channel list.

`create_session(username)` and `get_session(request)`:

- Support cookie-based login.

`require_user(request)`:

- Guard for authenticated APIs.

`register_peer(data, request, session)`:

- Writes to `PEERS`.
- Updates `CHAT_CHANNELS`.

`peer_list(channel=None, include_inactive=False)`:

- Reads `PEERS`.
- Filters by active status and optional channel.

`find_peer_by_username(username, channel=None)`:

- Returns most recently seen active endpoint for target user.
- Used by `/connect-peer`.

## 6. Tracker API design and mapping

### 6.1 `POST /login`

Status in current source: implemented.

Purpose:

Authenticate a user and create a session cookie.

HTTP method:

```text
POST
```

Request JSON:

```json
{
  "username": "alice",
  "password": "wonderland"
}
```

Response JSON:

```json
{
  "username": "alice",
  "role": "user"
}
```

Response headers:

```http
Set-Cookie: session_id=<token>; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax
```

Error cases:

- Missing username/password -> effectively invalid credentials.
- Wrong password -> `401 Unauthorized`.
- Unknown username -> `401 Unauthorized`.
- Invalid JSON body -> parsed as `{}`, then invalid credentials.

Reads/writes state:

- Reads `USERS`.
- Writes `SESSIONS`.

Why client-server phase:

Login establishes identity before peer can register or discover others. It does not send chat messages.

Current source:

```python
@app.route("/login", methods=["POST"])
def login(headers, body, request):
    ...
```

### 6.2 `POST /submit-info`

Status in current source: implemented.

Purpose:

Register or update the current authenticated peer endpoint.

HTTP method:

```text
POST
```

Request JSON:

```json
{
  "peer_ip": "127.0.0.1",
  "peer_port": 9001,
  "status": "online",
  "channels": ["general"]
}
```

Aliases accepted by source:

```json
{
  "ip": "127.0.0.1",
  "port": 9001,
  "channel": "general"
}
```

Response JSON:

```json
{
  "message": "Peer registered",
  "duplicate": false,
  "removed_inactive": 0,
  "peers": [
    {
      "username": "alice",
      "peer_ip": "127.0.0.1",
      "peer_port": 9001,
      "status": "online",
      "channels": ["general"],
      "last_seen": 1760000000
    }
  ]
}
```

Error cases:

- Missing/invalid session cookie -> `401 Unauthorized`.
- Missing `peer_ip` or `peer_port` -> `400 Bad Request`.
- Non-integer `peer_port` -> `400 Bad Request`.
- Invalid status -> `400 Bad Request`.

Reads/writes state:

- Reads `SESSIONS` through `require_user()`.
- Writes `PEERS`.
- Writes/updates `CHAT_CHANNELS`.
- Calls `cleanup_inactive_peers()`.

Why client-server phase:

Peer registration tells tracker where a peer can be reached. It is metadata publication, not live chat.

Current source:

```python
@app.route("/submit-info", methods=["POST"])
def submit_info(headers, body, request):
    ...
```

### 6.3 `POST /add-list` and `DELETE /add-list`

Status in current source: implemented as compatibility alias.

Purpose:

Compatibility endpoint for adding/removing peer presence.

HTTP methods:

```text
POST
DELETE
```

Current behavior:

```python
if request.method == "DELETE":
    return leave(headers, body, request)
return submit_info(headers, body, request)
```

Request JSON for `POST`:

Same as `/submit-info`.

Request JSON for `DELETE`:

```json
{
  "peer_ip": "127.0.0.1",
  "peer_port": 9001
}
```

Response JSON:

For `POST`, same as `/submit-info`.

For `DELETE`, same as `/leave`:

```json
{
  "left": 1,
  "peers": []
}
```

Error cases:

- Missing/invalid session -> `401 Unauthorized`.
- Same validation as delegated endpoint.

Reads/writes state:

- `POST`: writes `PEERS`, `CHAT_CHANNELS`.
- `DELETE`: marks/removes peer from `PEERS`.

Why client-server phase:

It maintains tracker registry metadata. It does not deliver messages.

### 6.4 `GET /get-list`

Status in current source: implemented.

Purpose:

Return active peer list for discovery.

HTTP method:

```text
GET
```

Query parameters:

```text
channel=general
include_inactive=true
```

Request JSON:

None.

Response JSON:

```json
{
  "count": 2,
  "removed_inactive": 0,
  "channel": "general",
  "peers": [
    {
      "username": "bob",
      "peer_ip": "127.0.0.1",
      "peer_port": 9002,
      "status": "online",
      "channels": ["general"],
      "last_seen": 1760000000
    }
  ]
}
```

Error cases:

- Missing/invalid session -> `401 Unauthorized`.

Reads/writes state:

- Reads `SESSIONS`.
- Reads `PEERS`.
- May remove expired/offline peers through `cleanup_inactive_peers()`.

Why client-server phase:

It returns endpoint metadata so peer can open direct socket later. It does not send chat payload.

Current source:

```python
@app.route("/get-list", methods=["GET"])
def get_list(headers, body, request):
    ...
```

### 6.5 `POST /connect-peer`

Status in current source: implemented as control API.

Purpose:

Return target peer endpoint for direct connection setup.

HTTP method:

```text
POST
```

Request JSON:

```json
{
  "username": "bob",
  "channel": "general"
}
```

Source also accepts:

```json
{
  "peer": "bob"
}
```

or:

```json
{
  "target": "bob"
}
```

Response JSON:

```json
{
  "username": "bob",
  "peer_ip": "127.0.0.1",
  "peer_port": 9002,
  "status": "online",
  "channels": ["general"],
  "last_seen": 1760000000,
  "note": "Use this endpoint information to open a direct TCP socket from peer.py. The tracker does not forward chat messages."
}
```

Error cases:

- Missing/invalid session -> `401 Unauthorized`.
- Missing target -> `400 Bad Request`.
- Target is self -> `400 Bad Request`.
- Target not registered/active -> `404 Not Found`.

Reads/writes state:

- Reads `SESSIONS`.
- Reads `PEERS`.
- May cleanup expired peers.

Why client-server phase:

It is a control-plane lookup. It does not open socket and does not relay message. The returned `peer_ip`/`peer_port` are used by `peer.py` for direct P2P.

Current source:

```python
@app.route("/connect-peer", methods=["POST"])
def connect_peer(headers, body, request):
    ...
```

### 6.6 `GET /channels`

Status in current source: not implemented as route. Design target if assignment requires channel APIs.

Purpose:

Return known channels tracked by the server.

HTTP method:

```text
GET
```

Request JSON:

None.

Response JSON design:

```json
{
  "channels": [
    {
      "name": "general",
      "members": ["alice", "bob"],
      "active_count": 2
    }
  ]
}
```

Simpler response could be:

```json
{
  "channels": ["general"]
}
```

Error cases:

- Missing/invalid session -> `401 Unauthorized` if channels require login.
- Cần kiểm tra thêm: requirement may allow public channel listing; current tracker-state requires auth.

Reads/writes state:

- Reads `CHAT_CHANNELS`.
- May derive active members from `PEERS`.

Why client-server phase:

Channel list is metadata. It helps peers choose discovery scope; it does not deliver channel messages.

Likely implementation location:

```text
apps/chatapp.py if assignment expects chatapp
apps/sampleapp.py in current repo
```

Would use:

```python
@app.route("/channels", methods=["GET"])
```

### 6.7 `POST /channels/join`

Status in current source: not implemented as route. Design target if assignment requires channel APIs.

Purpose:

Add current authenticated user/peer to a channel metadata list.

HTTP method:

```text
POST
```

Request JSON design:

```json
{
  "channel": "general",
  "peer_ip": "127.0.0.1",
  "peer_port": 9001
}
```

Response JSON design:

```json
{
  "message": "Joined channel",
  "channel": "general",
  "username": "alice",
  "channels": ["general"]
}
```

Error cases:

- Missing/invalid session -> `401 Unauthorized`.
- Missing channel -> `400 Bad Request`.
- Peer not registered -> `404 Not Found`, if join requires existing peer endpoint.
- Invalid channel name -> `400 Bad Request`, if validation is added.

Reads/writes state:

- Reads `SESSIONS`.
- Writes `CHAT_CHANNELS`.
- Updates matching `PEERS[key]["channels"]`, if peer endpoint is known.

Why client-server phase:

Joining a channel updates metadata used for discovery/filtering. It should not send any live channel message.

Current source relation:

`register_peer()` already creates/updates channel metadata when peer registers:

```python
for channel in channels:
    CHAT_CHANNELS.setdefault(channel, {"name": channel, "members": set()})
    CHAT_CHANNELS[channel]["members"].add(username)
```

So `/channels/join` would be a more explicit API for the same concept.

### 6.8 `GET /channels/my`

Status in current source: not implemented as route. Design target if assignment requires channel APIs.

Purpose:

Return channels associated with the current authenticated user/peer.

HTTP method:

```text
GET
```

Request JSON:

None.

Response JSON design:

```json
{
  "username": "alice",
  "channels": ["general"]
}
```

If multiple peer endpoints per user exist:

```json
{
  "username": "alice",
  "peers": [
    {
      "peer_ip": "127.0.0.1",
      "peer_port": 9001,
      "channels": ["general"]
    }
  ],
  "channels": ["general"]
}
```

Error cases:

- Missing/invalid session -> `401 Unauthorized`.
- No registered peer -> could return empty channels or `404 Not Found`.

Reads/writes state:

- Reads `SESSIONS`.
- Reads `PEERS`.
- Reads `CHAT_CHANNELS`.

Why client-server phase:

It reports membership metadata. It does not deliver messages from those channels.

### 6.9 Related current APIs not in required list

Current source also has:

- `POST /heartbeat`: refresh `last_seen`.
- `POST/DELETE /leave`: mark peer offline.
- `GET /tracker-state`: browser dashboard payload.
- `GET /chat-state`: compatibility alias.
- `POST /send-peer`: rejected with `410 Gone`.
- `POST /broadcast-peer`: rejected with `410 Gone`.
- `GET /peer-inbox`: rejected with `410 Gone`.

These rejected endpoints are useful architecture evidence:

```text
Tracker is not the live message transport.
```

## 7. How these APIs map to framework files

### `apps/chatapp.py` or `apps/sampleapp.py`

This is where tracker route handlers belong.

Current repo has:

```text
apps/sampleapp.py
```

No `apps/chatapp.py` is present.

Therefore current implementation location is `apps/sampleapp.py`.

If assignment expects `apps/chatapp.py`, likely design would be similar:

```python
app = AsynapRous()

@app.route("/login", methods=["POST"])
def login(headers, body, request):
    ...
```

### `daemon/asynaprous.py`

Responsible for route registration:

```python
self.routes[(method.upper(), path)] = func
```

It does not know tracker semantics. It only maps:

```text
(method, path) -> handler function
```

### `daemon/httpadapter.py`

Responsible for request dispatch:

```python
req.prepare(msg, self.routes)
response = await self._dispatch_route_async(req, resp)
```

It calls route handler:

```python
result = await self._call_route_async(req)
```

It does not know whether `/get-list` means peer discovery. It only dispatches.

### `daemon/request.py`

Responsible for parsing:

- method;
- path;
- headers;
- body;
- cookies;
- query params;
- route hook.

Tracker APIs need it for:

- session cookie: `request.cookies`;
- query params: `request.query_params`;
- JSON body text: `request.body`.

### `daemon/response.py`

Responsible for converting route result into HTTP response bytes.

Tracker APIs usually return:

```python
json_response({...})
```

`Response.build_route_response()` turns that into:

```http
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8

{...}
```

## 8. Execution/data flow explanation

### 8.1 Registration flow

```text
peer.py Alice
  -> POST /login
  -> receives session_id cookie
  -> starts local TCP server on 127.0.0.1:9001
  -> POST /submit-info with peer_ip/peer_port/channels

tracker
  -> validates cookie
  -> writes PEERS
  -> writes CHAT_CHANNELS
  -> returns active peers metadata
```

### 8.2 Discovery flow

```text
peer.py Alice
  -> GET /get-list

tracker
  -> validates cookie
  -> cleanup inactive peers
  -> returns peer metadata

Alice
  -> chooses Bob endpoint
  -> opens direct TCP connection to Bob
```

### 8.3 Connect-peer control flow

```text
peer.py Alice
  -> POST /connect-peer {"username":"bob"}

tracker
  -> validates cookie
  -> finds active Bob peer endpoint
  -> returns peer_ip/peer_port

Alice
  -> uses returned endpoint for direct P2P
```

### 8.4 Channel metadata flow

Current source through `/submit-info`:

```text
peer registers channels ["general"]
  -> register_peer()
  -> peer["channels"] = ["general"]
  -> CHAT_CHANNELS["general"]["members"].add(username)
```

Target explicit API if required:

```text
POST /channels/join
  -> update channel membership metadata
GET /channels
  -> list channel metadata
GET /channels/my
  -> list current user's channel metadata
```

Then live channel message should still be:

```text
sender peer discovers peers in channel
sender peer sends direct TCP payload to each peer
```

Not:

```text
sender -> tracker /channels/send -> tracker forwards message
```

## 9. Important functions/classes and their role

| Function/state | File | Role |
|---|---|---|
| `USERS` | `apps/sampleapp.py` | Demo user credential store |
| `SESSIONS` | `apps/sampleapp.py` | In-memory session store |
| `PEERS` | `apps/sampleapp.py` | Active peer registry |
| `CHAT_CHANNELS` | `apps/sampleapp.py` | Channel metadata registry |
| `parse_body()` | `apps/sampleapp.py` | Parse JSON/form request body |
| `parse_channels()` | `apps/sampleapp.py` | Normalize channel input |
| `require_user()` | `apps/sampleapp.py` | Auth guard for tracker APIs |
| `register_peer()` | `apps/sampleapp.py` | Write peer metadata |
| `peer_list()` | `apps/sampleapp.py` | Read active peer metadata |
| `find_peer_by_username()` | `apps/sampleapp.py` | Find target endpoint for `/connect-peer` |
| `login()` | `apps/sampleapp.py` | `/login` handler |
| `submit_info()` | `apps/sampleapp.py` | `/submit-info` handler |
| `add_list()` | `apps/sampleapp.py` | `/add-list` compatibility handler |
| `get_list()` | `apps/sampleapp.py` | `/get-list` handler |
| `connect_peer()` | `apps/sampleapp.py` | `/connect-peer` control API |
| `legacy_peer_response()` | `apps/sampleapp.py` | Reject live relay APIs |
| `AsynapRous.route()` | `daemon/asynaprous.py` | Register API route |
| `Request.prepare()` | `daemon/request.py` | Parse request for API handler |
| `HttpAdapter._dispatch_route_async()` | `daemon/httpadapter.py` | Dispatch request to API handler |
| `Response.build_route_response()` | `daemon/response.py` | Build JSON response |

## 10. Common mistakes/misunderstandings

- Nghĩ tracker APIs là live chat APIs. Không đúng: tracker APIs là control plane.
- Nghĩ `/get-list` gửi message. Không đúng: nó chỉ trả peer metadata.
- Nghĩ `/connect-peer` mở socket. Không đúng: nó chỉ trả endpoint.
- Nghĩ `/channels` nên trả chat history. Không đúng nếu architecture là P2P; channel API nên trả metadata.
- Nghĩ channel membership đồng nghĩa message relay. Không đúng: membership helps discovery/filtering.
- Nghĩ `PEERS` là permanent database. Không đúng: it is in-memory and TTL-based.
- Nghĩ `last_seen` là message timestamp. Không đúng: it is presence timestamp.
- Nghĩ username in request body should decide owner. Không đúng: owner should come from session.
- Nghĩ rejected `/send-peer` is a bug. In hybrid architecture, rejecting server relay can be intentional.

## 11. Checklist: what I must understand before moving to the next stage

- [ ] I can explain peer registration.
- [ ] I can explain peer discovery.
- [ ] I can explain active peer registry.
- [ ] I can explain channel metadata.
- [ ] I know which APIs are required for client-server initialization.
- [ ] I know why live message relay should not be placed here.
- [ ] Tôi biết tracker stores metadata, not live chat payloads.
- [ ] Tôi biết `/submit-info` writes `PEERS`.
- [ ] Tôi biết `/get-list` reads `PEERS`.
- [ ] Tôi biết `/connect-peer` returns endpoint only.
- [ ] Tôi biết `/channels*` chưa có trong current source và cần implementation nếu assignment yêu cầu.

## 12. Suggested test commands or observation commands if applicable

Start tracker:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Login:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Register peer:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/submit-info -H "Content-Type: application/json" -H "Cookie: session_id=<alice-session>" -d "{\"peer_ip\":\"127.0.0.1\",\"peer_port\":9001,\"channels\":[\"general\"]}"
```

Get active peer list:

```powershell
curl.exe -i http://127.0.0.1:2026/get-list -H "Cookie: session_id=<alice-session>"
```

Get active peer list by channel:

```powershell
curl.exe -i "http://127.0.0.1:2026/get-list?channel=general" -H "Cookie: session_id=<alice-session>"
```

Connect-peer endpoint lookup:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/connect-peer -H "Content-Type: application/json" -H "Cookie: session_id=<alice-session>" -d "{\"username\":\"bob\"}"
```

Check relay APIs are rejected:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/send-peer
curl.exe -i -X POST http://127.0.0.1:2026/broadcast-peer
curl.exe -i http://127.0.0.1:2026/peer-inbox
```

Observe source routes:

```powershell
rg -n "@app\\.route|CHAT_CHANNELS|PEERS|connect_peer|submit_info|get_list|add_list|legacy_peer_response" apps/sampleapp.py
```

Check whether explicit channel APIs exist:

```powershell
rg -n '"/channels' apps daemon
```

## 13. Suggested commit message

Suggested commit message:

```text
docs: add stage 08 tracker server api design
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-08-tracker-server-apis.md
git commit -m "docs: add stage 08 tracker server api design" -- docs/learning/stage-08-tracker-server-apis.md
```
