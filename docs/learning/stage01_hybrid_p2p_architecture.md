# Stage 01 - Kiến trúc hybrid P2P và ranh giới tracker/peer

## 1. Stage objective

Mục tiêu của stage này là hiểu bức tranh tổng thể trước khi đọc sâu từng module:

- Vì sao project này được gọi là **hybrid P2P chat**.
- `apps/sampleapp.py` đóng vai trò **HTTP tracker**: login, cookie session, đăng ký peer, discovery, heartbeat, leave.
- `peer.py` đóng vai trò **real peer**: mỗi terminal là một peer process, tự mở TCP server, tự kết nối TCP trực tiếp đến peer khác.
- `daemon/` là lớp framework/server tự viết: đọc socket, parse HTTP request, route request, build HTTP response.
- Browser UI chỉ là dashboard của tracker, không phải chat client P2P thật.
- Chat message không đi qua tracker. Tracker chỉ giúp các peer tìm thấy IP/port của nhau.

Sau stage này, bạn nên nhìn được project như 3 lớp tách biệt:

```text
Browser / curl / peer.py TrackerClient
        |
        v
daemon backend + HTTP adapter
        |
        v
apps/sampleapp.py: auth + tracker registry

peer.py process A  <------ asyncio TCP socket ------>  peer.py process B
```

Nếu chưa nắm ranh giới này, rất dễ đọc nhầm `sampleapp.py` là nơi gửi chat, hoặc nhầm browser dashboard là giao diện chat P2P. Source hiện tại cố tình ngược lại: tracker không forward chat message.

## 2. Theory needed before understanding this stage

### Hybrid P2P

Trong mô hình P2P thuần, các node tự tìm nhau và tự gửi dữ liệu cho nhau. Trong mô hình client-server thuần, mọi message đi qua server trung tâm.

Project này là **hybrid P2P**:

- Phần server trung tâm vẫn tồn tại để xử lý authentication và peer discovery.
- Phần chat data plane là P2P: message đi trực tiếp giữa các peer process qua TCP socket.

Tracker tồn tại vì nếu không có tracker, Alice không biết Bob đang listen ở IP/port nào. Nhưng sau khi biết endpoint của Bob, Alice không cần gửi chat qua tracker nữa.

### socket và TCP stream

Cả HTTP backend và P2P chat đều chạy trên TCP socket, nhưng protocol khác nhau:

- HTTP backend nhận raw HTTP request từ browser, curl hoặc `http.client`.
- P2P peer nhận JSON-line message: mỗi message là một JSON object kết thúc bằng `\n`.

TCP là stream, không giữ sẵn biên giới message. Vì vậy:

- HTTP phải đọc đến `\r\n\r\n` để kết thúc headers, rồi đọc tiếp theo `Content-Length`.
- P2P dùng newline framing để `StreamReader.readline()` biết khi nào một JSON object kết thúc.

### HTTP request và HTTP response

Tracker API dùng HTTP. Một request quan trọng có dạng:

```http
POST /submit-info HTTP/1.1
Host: 127.0.0.1:2026
Cookie: session_id=...
Content-Type: application/json
Content-Length: ...

{"peer_ip":"127.0.0.1","peer_port":9001}
```

Backend phải:

1. Đọc bytes từ socket.
2. Parse method, path, headers, body.
3. Tìm route theo `(method, path)`.
4. Gọi handler trong `apps/sampleapp.py`.
5. Build HTTP response có status line, headers, body.

### cookie session

Sau `POST /login`, server trả `Set-Cookie: session_id=...`. Các request sau gửi lại:

```http
Cookie: session_id=...
```

`apps/sampleapp.py` dùng cookie này để biết user hiện tại là ai. Điểm quan trọng: `/submit-info` lấy `username` từ session, không tin `username` trong request body. Đây là cách tránh một peer giả mạo đăng ký endpoint cho user khác.

### non-blocking và asyncio

`asyncio` cho phép nhiều việc chờ I/O cùng tồn tại trong một event loop:

- HTTP backend dùng `asyncio.start_server`.
- `peer.py` vừa chạy TCP server, vừa đọc terminal input, vừa heartbeat định kỳ.
- Broadcast dùng `asyncio.gather()` để gửi đến nhiều peer cùng lúc.

Trong project này vẫn có code synchronous cũ, nhưng mặc định `daemon/backend.py` đặt `mode_async = "coroutine"`, nên backend hiện tại ưu tiên asyncio.

### in-memory state và TTL

`SESSIONS`, `PEERS`, `CHAT_CHANNELS` đều là dictionary trong memory. Restart tracker là mất hết.

TTL là thời gian sống:

- `SESSION_TTL_SECONDS = 3600`: session login hết hạn sau 1 giờ.
- `PEER_TTL_SECONDS = 300`: peer không heartbeat trong 5 phút sẽ bị cleanup.

Đây là kỹ thuật presence cơ bản: peer không cần gửi "I am alive" liên tục từng giây, chỉ cần heartbeat định kỳ.

## 3. Where this concept appears in the assignment requirement

Trong repo hiện tại, yêu cầu/định hướng project xuất hiện rõ nhất ở:

- `README.md`: mô tả "CO3094 Hybrid P2P Chat", yêu cầu standard library only, tracker endpoints, peer CLI commands, smoke test.
- `docs/final_report.md`: mô tả kiến trúc 3 lớp, HTTP flow, tracker, direct P2P protocol, async design.
- `docs/api_reference.md`: liệt kê API authentication/tracker và các deprecated endpoints trả `410 Gone`.
- `docs/architecture_diagrams.md`: minh hoạ Phase 1 authentication/discovery, Phase 2 direct P2P messaging, Phase 3 broadcast.

Mapping khái niệm sang requirement trong repo:

- "Tracker handles login, cookie sessions, peer registration, discovery, heartbeat, leave" tương ứng với các route `/login`, `/me`, `/submit-info`, `/get-list`, `/heartbeat`, `/leave`.
- "Tracker does not forward chat messages" tương ứng với việc `/connect-peer`, `/send-peer`, `/broadcast-peer`, `/peer-inbox` đều trả deprecated response HTTP `410`.
- "Each `peer.py` process is one real peer" tương ứng với CLI `python peer.py --username ... --listen-port ...`.
- "Direct messages and broadcast use asyncio TCP sockets" tương ứng với `PeerNode.send_payload()`, `PeerNode.handle_peer()`, `PeerNode.broadcast()`.

Cần kiểm tra thêm: repo không có file assignment statement chính thức từ LMS/giảng viên ngoài các tài liệu nội bộ trong `README.md` và `docs/`. Vì vậy phần này dựa trên source code và tài liệu có trong repo, không khẳng định chính xác từng dòng của đề bài gốc.

## 4. Related files in the project

- `start_sampleapp.py`: entry point để chạy tracker HTTP server ở port mặc định `2026`.
- `apps/sampleapp.py`: application layer, chứa user/password mẫu, session store, peer registry, route handlers của tracker.
- `peer.py`: peer process thật, vừa nói chuyện với tracker qua HTTP, vừa nói chuyện với peer khác qua TCP.
- `daemon/backend.py`: server lifecycle, mặc định chạy asyncio backend bằng `asyncio.start_server`.
- `daemon/httpadapter.py`: xử lý một HTTP connection: read request, parse, dispatch route, write response.
- `daemon/request.py`: parse raw HTTP message thành `Request`.
- `daemon/response.py`: build HTTP/1.1 response, JSON response, static file response, error response.
- `daemon/asynaprous.py`: mini web framework/router dùng decorator `@app.route(...)`.
- `daemon/proxy.py`: reverse proxy độc lập, dùng host-based routing và round-robin. Stage này chỉ cần biết nó là phần phụ, không nằm trên đường direct P2P chat chính.
- `www/login.html`, `www/chat.html`, `static/js/chat.js`: browser dashboard cho tracker.
- `tests/smoke_http.py`: smoke test HTTP tracker bằng standard library.
- `config/proxy.conf`: cấu hình proxy, không phải cấu hình P2P peer discovery chính.

## 5. Detailed source-code reading notes

### 5.1 Entry point của tracker

`start_sampleapp.py` parse:

```text
--server-ip
--server-port
```

rồi gọi:

```text
apps.create_sampleapp(ip, port)
```

Trong `apps/__init__.py`, `create_sampleapp` được export từ `apps/sampleapp.py`.

Trong `apps/sampleapp.py`, `create_sampleapp(ip, port)` làm 2 việc:

1. `app.prepare_address(ip, port)`
2. `app.run()`

`app` là instance của `AsynapRous`, được tạo ở đầu file:

```python
app = AsynapRous()
```

Ý nghĩa: `sampleapp.py` không tự mở socket. Nó đăng ký route và nhờ framework trong `daemon/` chạy HTTP backend.

### 5.2 Route registry trong `AsynapRous`

`daemon/asynaprous.py` định nghĩa `AsynapRous.routes` là dictionary:

```text
(HTTP_METHOD, PATH) -> function
```

Ví dụ khi source có:

```python
@app.route("/login", methods=["POST"])
def login(...):
    ...
```

thì registry có key:

```text
("POST", "/login")
```

Điểm cần để ý: decorator tạo wrapper sync/async, nhưng `self.routes[(method.upper(), path)] = func` lưu function gốc vào route table trước. Vì vậy adapter thường gọi function route gốc, không gọi wrapper in log. Đây không phải bug bắt buộc, chỉ là chi tiết đọc code để không ngạc nhiên khi log wrapper không xuất hiện như kỳ vọng.

### 5.3 Backend server lifecycle

`daemon/backend.py` có `mode_async = "coroutine"`. Trong `run_backend()`:

- Nếu mode là `"coroutine"`, gọi `asyncio.run(async_server(ip, port, routes))`.
- `async_server()` gọi `asyncio.start_server(...)`.
- Mỗi connection mới được đưa vào `handle_client_coroutine(reader, writer, routes)`.
- `handle_client_coroutine()` tạo `HttpAdapter` rồi gọi `daemon.handle_client_coroutine(reader, writer)`.

Nói ngắn gọn:

```text
start_sampleapp.py
  -> apps/sampleapp.py:create_sampleapp
  -> AsynapRous.run
  -> daemon.create_backend
  -> daemon.backend.run_backend
  -> daemon.backend.async_server
  -> daemon.httpadapter.HttpAdapter.handle_client_coroutine
```

Phần synchronous bằng `socket.accept()` và thread vẫn còn trong file, nhưng mặc định không phải đường chạy chính vì `mode_async = "coroutine"`.

### 5.4 HTTP adapter đọc request như thế nào

`daemon/httpadapter.py` có 2 đường đọc:

- `_read_http_message(conn)` cho blocking socket.
- `_read_http_message_async(reader)` cho asyncio stream.

Đường async:

1. `reader.readuntil(b"\r\n\r\n")` đọc hết HTTP headers.
2. `_content_length_from_headers(...)` tìm `Content-Length`.
3. Nếu có body, `reader.readexactly(content_length)` đọc đúng số bytes.
4. Ghép header + blank line + body thành text request.

Đây là điểm nền tảng của HTTP: server không thể chỉ `read(4096)` rồi hy vọng đủ toàn bộ request, vì body có thể đến sau headers.

### 5.5 Request parsing

`daemon/request.py` biến raw HTTP text thành object:

- `method`: ví dụ `GET`, `POST`.
- `url`: target gốc từ request line, ví dụ `/get-list?channel=general`.
- `path`: phần path, ví dụ `/get-list`.
- `version`: ví dụ `HTTP/1.1`.
- `headers`: case-insensitive dict.
- `query_params`: dict từ query string, ví dụ `{"channel": ["general"]}`.
- `cookies`: dict parse từ `Cookie`.
- `body`: phần sau `\r\n\r\n`.
- `hook`: route handler lấy từ `routes.get((method, path))`.

Điểm quan trọng: request parser không biết logic login, peer, P2P. Nó chỉ parse protocol HTTP và gắn route hook tương ứng.

### 5.6 Dispatch route và build response

`HttpAdapter._dispatch_route_async()`:

- Chặn method không thuộc `GET`, `POST`, `PUT`, `DELETE` bằng `405`.
- Nếu không có route và method là `GET`, thử serve static file.
- Nếu không có route và không phải static GET, trả `404`.
- Nếu có route, gọi `_call_route_async(req)`.
- Kết quả route được đưa sang `Response.build_response(..., envelop_content=result)`.

`Response.build_route_response()` hiểu response envelope dạng:

```python
{
    "status": 200,
    "headers": {...},
    "body": {...},
    "content_type": "application/json; charset=utf-8",
}
```

Đó là format mà `apps/sampleapp.py:json_response()` trả về. Nhờ vậy route handler không cần tự build bytes HTTP.

### 5.7 Auth/session trong tracker

Trong `apps/sampleapp.py`:

- `USERS`: user/password/role hard-code.
- `SESSIONS`: map `session_id -> username, role, created_at`.
- `create_session(username)`: tạo token bằng `secrets.token_urlsafe(32)`.
- `session_cookie(session_id)`: tạo header `Set-Cookie`.
- `get_session(request)`: đọc `request.cookies["session_id"]`, kiểm tra tồn tại và TTL.
- `require_user(request)`: helper cho route cần login.
- `require_role(request, "admin")`: helper cho route cần admin.

Flow login:

```text
POST /login
  -> parse_body()
  -> check USERS
  -> create_session()
  -> Set-Cookie: session_id=...
```

Flow protected API:

```text
GET /me hoặc POST /submit-info
  -> Request.prepare() parse Cookie header
  -> require_user()
  -> get_session()
  -> trả data hoặc 401
```

### 5.8 Peer registry trong tracker

`PEERS` là dictionary lưu endpoint của peer:

```text
"username@ip:port" -> {
    username,
    peer_ip,
    peer_port,
    status,
    channels,
    last_seen
}
```

`peer_key(username, peer_ip, peer_port)` tạo key. Vì key có cả username, IP, port nên một user có thể có nhiều endpoint nếu chạy nhiều peer process khác port.

`register_peer(data, request, session)`:

- Lấy `peer_ip` từ body hoặc fallback sang address của TCP connection.
- Lấy `peer_port` từ body.
- Validate port là integer.
- Validate status nằm trong `online`, `away`, `busy`, `offline`.
- Lấy `username` từ `session["username"]`, không lấy từ client body.
- Update `PEERS`.
- Update `CHAT_CHANNELS`.

`peer_list(channel=None, include_inactive=False)`:

- Gọi `cleanup_inactive_peers()`.
- Bỏ peer có status không active nếu `include_inactive` false.
- Filter theo channel nếu có.
- Trả list đã sort để output ổn định.

### 5.9 Heartbeat và leave

`heartbeat()` refresh `last_seen` cho peer thuộc user đang login. Nếu không tìm thấy peer đã đăng ký, trả `404`.

`leave()` không trực tiếp delete trước, mà set status `"offline"` rồi gọi `cleanup_inactive_peers()`. Vì `cleanup_inactive_peers()` xóa peer offline, kết quả thực tế là peer sẽ bị remove khỏi registry active.

Ý nghĩa network: khi peer process còn sống, nó định kỳ báo "tôi vẫn online". Khi tắt, nó báo leave để tracker không đưa endpoint chết cho peer khác.

### 5.10 Deprecated server-side P2P endpoints

Các route:

- `/connect-peer`
- `/send-peer`
- `/broadcast-peer`
- `/peer-inbox`

đều gọi `legacy_peer_response()` và trả `410 Gone`.

Đây là bằng chứng quan trọng nhất trong source rằng tracker không còn là nơi relay chat. Nếu bạn thấy endpoint tên giống gửi message, đừng đọc nó như logic chat hiện tại.

### 5.11 `peer.py`: TrackerClient

`TrackerClient` nói chuyện với tracker bằng `http.client.HTTPConnection`.

Các method chính:

- `login(username, password)` -> `POST /login`.
- `register(listen_host, listen_port, channels)` -> `POST /submit-info`.
- `get_list()` -> `GET /get-list`.
- `heartbeat(...)` -> `POST /heartbeat`.
- `leave(...)` -> `POST /leave`.

`request()` dùng:

```python
await asyncio.to_thread(self._request_sync, method, path, payload)
```

Lý do: `http.client` là blocking API. Nếu gọi trực tiếp trong event loop, terminal input, heartbeat và P2P server có thể bị đứng trong lúc HTTP request chờ network. `asyncio.to_thread()` đẩy việc blocking sang thread phụ.

`_store_cookie()` đọc `Set-Cookie`, lấy `session_id`, rồi lưu header cookie cho request sau.

### 5.12 `peer.py`: PeerNode

`PeerNode.start()`:

1. Login tracker.
2. Mở TCP server bằng `asyncio.start_server(self.handle_peer, listen_host, listen_port)`.
3. Register endpoint lên tracker.
4. Tạo heartbeat task.

`handle_peer(reader, writer)`:

- Chạy cho mỗi inbound TCP connection từ peer khác.
- Đọc từng line bằng `reader.readline()`.
- Decode JSON.
- Gọi `handle_payload(...)`.

`send_direct(recipient, message)`:

- `find_peer(recipient)` hỏi tracker danh sách peer.
- Tạo payload type `"direct"`.
- Gọi `send_payload(peer, payload)`.

`broadcast(message)`:

- Hỏi tracker peer list.
- Loại chính mình ra.
- Tạo cùng một payload type `"broadcast"`.
- Dùng `asyncio.gather()` để gửi tới nhiều peer đồng thời.

`send_payload(peer, payload)`:

1. `asyncio.open_connection(host, port)` mở TCP socket trực tiếp tới peer.
2. Gửi `hello` JSON-line.
3. Gửi `direct` hoặc `broadcast` JSON-line.
4. Chờ `ack` có cùng `message_id`.
5. Nếu timeout, connection closed, invalid JSON hoặc error payload thì báo fail.
6. Close connection.

### 5.13 Browser dashboard

`static/js/chat.js` gọi:

- `/me`
- `/get-list`
- `/tracker-state`
- `/submit-info`
- `/heartbeat`
- `/leave`
- `/logout`

Nó render user, peer list, channel count và form register/heartbeat/leave. Không có code mở TCP socket tới peer khác, cũng không có WebSocket. Vì vậy browser không phải P2P chat client trong kiến trúc hiện tại.

## 6. Execution/data flow explanation

### 6.1 Start tracker

```text
User runs:
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026

start_sampleapp.py
  -> create_sampleapp()
  -> app.run()
  -> create_backend()
  -> asyncio.start_server()
```

Từ thời điểm này, tracker lắng nghe HTTP request ở `127.0.0.1:2026`.

### 6.2 Browser login/dashboard flow

```text
Browser GET /login.html
  -> static file from www/login.html

Browser POST /login
  -> sampleapp.login()
  -> Set-Cookie session_id=...

Browser GET /chat.html
  -> static file from www/chat.html

static/js/chat.js GET /me, /get-list, /tracker-state
  -> Cookie tự đi kèm vì fetch dùng credentials: "include"
  -> tracker trả JSON dashboard data
```

Browser chỉ quan sát và quản lý tracker state. Nó không nhận direct message từ `peer.py`.

### 6.3 Peer startup flow

```text
User runs:
python peer.py --username alice --password wonderland --listen-port 9001

peer.py
  -> TrackerClient.login()
  -> tracker POST /login
  -> store session cookie
  -> asyncio.start_server(handle_peer, 127.0.0.1, 9001)
  -> TrackerClient.register()
  -> tracker POST /submit-info
  -> heartbeat_loop starts
  -> command_loop waits for /msg, /broadcast, ...f
```

Điểm mấu chốt: peer register `peer_ip`/`peer_port` để peer khác connect tới chính process này.

### 6.4 Direct message flow

Ví dụ Alice gửi Bob:

```text
Alice terminal:
/msg bob hello bob

Alice peer.py
  -> GET /get-list từ tracker
  -> tìm peer username == bob
  -> open TCP connection trực tiếp tới bob_ip:bob_port
  -> send {"type":"hello", ...}\n
  -> send {"type":"direct","to":"bob","message":"hello bob","message_id":"..."}\n

Bob peer.py
  -> handle_peer() đọc line
  -> handle_payload() thấy type direct
  -> kiểm tra payload["to"] == "bob"
  -> append vào inbox
  -> print [direct] alice: hello bob
  -> send {"type":"ack","message_id":"..."}\n

Alice peer.py
  -> đọc ACK match message_id
  -> print sent to bob ack=True
```

Tracker chỉ xuất hiện ở bước discovery (`GET /get-list`). Nội dung `"hello bob"` không đi qua tracker.

### 6.5 Broadcast flow

```text
Alice terminal:
/broadcast hello everyone

Alice peer.py
  -> GET /get-list
  -> bỏ alice khỏi list
  -> tạo payload broadcast
  -> asyncio.gather(send_payload(bob), send_payload(charlie), ...)

Mỗi receiver
  -> nhận broadcast
  -> append inbox
  -> gửi ACK

Alice
  -> gom kết quả
  -> print số succeeded/failed
```

Broadcast ở đây không phải multicast IP-level. Nó là nhiều direct TCP connection được mở song song từ sender tới từng peer.

### 6.6 Heartbeat/leave flow

```text
peer.py heartbeat_loop
  -> sleep HEARTBEAT_INTERVAL
  -> POST /heartbeat
  -> tracker update last_seen

peer.py shutdown hoặc /leave
  -> POST /leave
  -> tracker set offline rồi cleanup
```

Nếu heartbeat dừng quá `PEER_TTL_SECONDS`, tracker cleanup peer để tránh trả endpoint cũ.

### 6.7 Optional proxy flow

`daemon/proxy.py` là reverse proxy:

```text
client -> proxy -> backend
```

Nó đọc `Host`, chọn backend theo `config/proxy.conf`, rồi forward raw HTTP request. Đây là phần học network hữu ích, nhưng không phải đường gửi P2P chat chính.

Cần kiểm tra thêm: requirement chính thức có bắt buộc demo proxy chung với hybrid P2P hay proxy là phase riêng. Source hiện tại giữ proxy như module độc lập.

## 7. Important functions/classes and their role

| Function/class | File | Role |
|---|---|---|
| `AsynapRous` | `daemon/asynaprous.py` | Mini app/router, giữ route table và gọi backend |
| `AsynapRous.route()` | `daemon/asynaprous.py` | Decorator đăng ký `(method, path) -> handler` |
| `create_backend()` | `daemon/backend.py` | Entry để chạy backend server |
| `async_server()` | `daemon/backend.py` | Mở asyncio HTTP server bằng `asyncio.start_server` |
| `HttpAdapter` | `daemon/httpadapter.py` | Xử lý một HTTP connection |
| `_read_http_message_async()` | `daemon/httpadapter.py` | Đọc headers/body theo HTTP framing |
| `_dispatch_route_async()` | `daemon/httpadapter.py` | Chọn static file hoặc route handler |
| `Request.prepare()` | `daemon/request.py` | Parse raw HTTP request thành object |
| `Response.build_response()` | `daemon/response.py` | Build static hoặc route HTTP response |
| `json_response()` | `apps/sampleapp.py` | Chuẩn hóa return value của route thành response envelope |
| `create_session()` | `apps/sampleapp.py` | Tạo session token sau login |
| `get_session()` | `apps/sampleapp.py` | Kiểm tra cookie session và TTL |
| `require_user()` | `apps/sampleapp.py` | Guard route cần login |
| `register_peer()` | `apps/sampleapp.py` | Ghi peer endpoint vào `PEERS` |
| `peer_list()` | `apps/sampleapp.py` | Trả danh sách peer active cho discovery |
| `cleanup_inactive_peers()` | `apps/sampleapp.py` | Xóa peer offline hoặc quá TTL |
| `legacy_peer_response()` | `apps/sampleapp.py` | Chứng minh server-side P2P endpoint đã deprecated |
| `TrackerClient` | `peer.py` | HTTP client của peer để login/register/discover |
| `PeerMessage` | `peer.py` | Tạo wire-format JSON payload có `message_id` |
| `PeerNode` | `peer.py` | Peer process: TCP server, direct send, broadcast, CLI |
| `PeerNode.handle_peer()` | `peer.py` | Nhận inbound peer TCP connection |
| `PeerNode.send_payload()` | `peer.py` | Gửi message trực tiếp và chờ ACK |
| `PeerNode.broadcast()` | `peer.py` | Gửi song song tới nhiều peer bằng `asyncio.gather()` |

## 8. Common mistakes/misunderstandings

- Nhầm tracker là chat relay. Source hiện tại phản bác điều này: các endpoint gửi chat ở tracker trả `410 Gone`.
- Nhầm browser dashboard là chat client. Browser chỉ gọi REST tracker API, không mở direct TCP socket đến peer.
- Nghĩ `/submit-info` tin `username` từ body. Thực tế username lấy từ cookie session.
- Quên cookie khi gọi protected endpoint bằng curl, dẫn tới `401 Unauthorized`.
- Nhầm port tracker với port peer. Tracker mặc định `2026`; peer listen port do từng lệnh `peer.py --listen-port ...` quyết định.
- Nghĩ broadcast là một packet gửi cho cả nhóm. Thực tế là nhiều TCP connection riêng, chạy song song.
- Nghĩ `channels` là chat room đầy đủ. Source hiện tại chỉ dùng channel như metadata/filter trong tracker; không có lưu history hay enforce routing theo channel trong direct send. Cần kiểm tra thêm nếu đề bài yêu cầu channel semantics mạnh hơn.
- Nghĩ state được lưu bền vững. `SESSIONS`, `PEERS`, `CHAT_CHANNELS` chỉ ở memory.
- Bỏ qua `message_id`. ACK phải match `message_id`, nếu không sender không xem là success.
- Gọi blocking HTTP client trực tiếp trong async code. Project tránh việc này trong `peer.py` bằng `asyncio.to_thread()`.
- Đọc `daemon/proxy.py` như thành phần bắt buộc của P2P chat. Nó là reverse proxy HTTP riêng, không tham gia direct peer message.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] Tôi giải thích được sự khác nhau giữa tracker và peer.
- [ ] Tôi biết vì sao đây là hybrid P2P, không phải client-server chat thuần.
- [ ] Tôi vẽ được flow `POST /login -> Set-Cookie -> POST /submit-info -> GET /get-list`.
- [ ] Tôi biết chat message đi qua `peer.py -> TCP socket -> peer.py`, không đi qua `sampleapp.py`.
- [ ] Tôi biết `daemon/backend.py`, `daemon/httpadapter.py`, `daemon/request.py`, `daemon/response.py` hợp lại thành HTTP server tự viết.
- [ ] Tôi biết cookie session được parse ở `Request.prepare()` và validate ở `apps/sampleapp.py`.
- [ ] Tôi biết peer registry lưu `username`, `peer_ip`, `peer_port`, `status`, `channels`, `last_seen`.
- [ ] Tôi hiểu heartbeat dùng để giữ presence sống và TTL dùng để cleanup peer chết.
- [ ] Tôi phân biệt được static dashboard files trong `www/`/`static/` với API route trong `apps/sampleapp.py`.
- [ ] Tôi giải thích được direct message cần discovery trước, rồi mới open TCP connection trực tiếp.
- [ ] Tôi giải thích được broadcast là nhiều direct sends song song, không phải tracker broadcast.

## 10. Suggested test commands or observation commands if applicable

Kiểm tra source vẫn compile:

```powershell
python -m compileall .
```

Chạy tracker:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Quan sát browser dashboard:

```text
http://127.0.0.1:2026/login.html
```

Login bằng curl và quan sát `Set-Cookie`:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Gọi protected endpoint bằng cookie:

```powershell
curl.exe -i http://127.0.0.1:2026/me -H "Cookie: session_id=<value-from-login>"
```

Chạy smoke test HTTP tracker sau khi tracker đang chạy:

```powershell
python tests/smoke_http.py
```

Chạy 3 peer ở 3 terminal khác nhau:

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
python peer.py --username bob --password wonderland --listen-port 9002
python peer.py --username charlie --password wonderland --listen-port 9003
```

Trong terminal Alice:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

Quan sát quan trọng:

- Tracker log chỉ có login/register/list/heartbeat/leave.
- Bob nhận direct message trong terminal Bob.
- Bob và Charlie nhận broadcast trong terminal riêng.
- Alice thấy ACK/result, không phải response từ tracker cho nội dung chat.

## 11. Suggested commit message

Suggested commit message:

```text
docs(learning): add stage 01 hybrid P2P architecture notes
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage01_hybrid_p2p_architecture.md
git commit -m "docs(learning): add stage 01 hybrid P2P architecture notes" -- docs/learning/stage01_hybrid_p2p_architecture.md
```
