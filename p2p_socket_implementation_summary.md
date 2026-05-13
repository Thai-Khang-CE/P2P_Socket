# Tổng hợp chi tiết các phần đã implement — CO3094 Assignment 1: Hybrid P2P Chat

> Repository/branch: `Thai-Khang-CE/P2P_Socket` — branch `hybrid_application`  
> Mục tiêu assignment: triển khai HTTP server/webapp non-blocking, authentication bằng HTTP/cookies, và ứng dụng chat hybrid kết hợp client-server tracker + peer-to-peer direct socket.

---

## 1. Tóm tắt kết quả hiện tại

Project hiện đã hoàn thiện một hệ thống **Hybrid P2P Chat** theo kiến trúc:

```text
Browser / CLI client
        |
        | HTTP requests: /login, /me, /submit-info, /get-list, ...
        v
Async HTTP Backend + AsynapRous App
        |
        v
apps/sampleapp.py
Authentication + Cookie Session + Peer Tracker
        |
        | peer discovery only
        v
peer.py  <------ direct asyncio TCP socket ------>  peer.py
        direct message / broadcast / ACK protocol
```

Các điểm chính đã làm được:

- HTTP backend chạy bằng **asyncio coroutine-based non-blocking server**.
- Authentication sử dụng **cookie session** (`session_id`).
- Tracker server hỗ trợ **peer registration**, **peer list discovery**, **heartbeat**, **leave**, **tracker dashboard state**.
- `peer.py` là một **real peer process**, mỗi terminal chạy một peer riêng.
- Chat message thật sự đi qua **direct TCP socket giữa peer với peer**, không đi qua tracker.
- P2P protocol dùng **JSON-line framing** với các message type: `hello`, `direct`, `broadcast`, `ack`, `error`.
- Direct message có **ACK matching by `message_id`**.
- Broadcast gửi trực tiếp tới nhiều peer bằng `asyncio.gather`.
- Browser UI đã được chuyển thành **tracker dashboard**, không còn là server-side chat transport.
- README, API reference, architecture diagrams và final report notes đã được cập nhật theo kiến trúc mới.
- Có smoke test HTTP bằng standard library: `tests/smoke_http.py`.
- Demo 3 peer đã chạy thành công: Alice gửi direct cho Bob và broadcast cho Bob + Charlie.

---

## 2. Đối chiếu với yêu cầu specification

### 2.1 Non-blocking communication

Yêu cầu spec:

- Triển khai non-blocking communication.
- Có thể dùng multi-thread, callback/event-driven, hoặc coroutine/asyncio.
- Backend phải dùng standard Python library.
- Không dùng web framework có sẵn.

Đã implement:

- `daemon/backend.py` chạy backend với mode coroutine.
- Backend dùng `asyncio.start_server(...)`.
- `daemon/httpadapter.py` xử lý HTTP connection bằng async stream:
  - `StreamReader.readuntil(b"\r\n\r\n")`
  - `StreamReader.readexactly(content_length)`
  - `StreamWriter.write(...)`
  - `await writer.drain()`
  - `await writer.wait_closed()`
- `peer.py` dùng:
  - `asyncio.start_server(...)` cho incoming peer socket.
  - `asyncio.open_connection(...)` cho outgoing peer socket.
  - `asyncio.gather(...)` cho broadcast.
  - `asyncio.to_thread(input, "> ")` để input CLI không block event loop.
  - `asyncio.to_thread(...)` để gọi `http.client` tới tracker mà không block event loop chính.

Ý nghĩa:

- Khi một peer/server đang đợi network I/O, coroutine nhường quyền lại event loop.
- Nhiều HTTP request, heartbeat, terminal input, và P2P socket có thể cùng tồn tại trong một event loop.
- Không cần external framework như Flask/FastAPI/aiohttp/websockets.

---

### 2.2 Authentication handling + cookies access control

Yêu cầu spec:

- Implement authentication mechanism.
- Có thể dùng HTTP headers hoặc cookies.
- Cookies access control subsystem là yêu cầu quan trọng.

Đã implement trong `apps/sampleapp.py`:

Endpoint authentication:

| Method | Endpoint | Mục đích |
|---|---|---|
| `POST` | `/login` | Validate username/password, tạo `session_id` |
| `POST` | `/logout` | Xóa session và clear cookie |
| `GET` | `/me` | Trả về user hiện tại nếu cookie hợp lệ |
| `GET` | `/private` | Protected route cho user đã login |
| `GET` | `/admin` | Protected route yêu cầu role `admin` |

Cookie behavior:

```text
Set-Cookie: session_id=<random-token>; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax
```

Các helper đã có:

- `create_session(username)`
- `get_session(request)`
- `require_user(request)`
- `require_role(request, role)`
- `session_cookie(session_id)`
- `expired_session_cookie()`

Điểm quan trọng:

- Protected endpoints đều reject request thiếu cookie bằng `401 Unauthorized`.
- `/submit-info`, `/get-list`, `/heartbeat`, `/leave`, `/tracker-state` đều yêu cầu session cookie.
- `/submit-info` lấy username từ `session["username"]`, không tin username từ request body, tránh impersonation.

---

### 2.3 Client-server paradigm: tracker phase

Yêu cầu spec:

- Peer registration: peer submit IP/port tới centralized server.
- Tracker update: server maintain active peer list.
- Peer discovery: peer request current list of active peers.
- Connection setup: peer dùng tracking list để initiate direct P2P connection.

Đã implement trong `apps/sampleapp.py`:

Tracker endpoints:

| Method | Endpoint | Auth | Chức năng |
|---|---|---|---|
| `POST` | `/submit-info` | Yes | Đăng ký/cập nhật peer endpoint |
| `GET` | `/get-list` | Yes | Lấy danh sách active peers |
| `POST` | `/heartbeat` | Yes | Refresh `last_seen` |
| `POST`/`DELETE` | `/leave` | Yes | Mark peer offline |
| `POST`/`DELETE` | `/add-list` | Yes | Compatibility alias |
| `GET` | `/tracker-state` | Yes | State cho browser dashboard |
| `GET` | `/chat-state` | Yes | Alias cho `/tracker-state` |

Peer record structure:

```python
{
    "username": "alice",
    "peer_ip": "127.0.0.1",
    "peer_port": 9001,
    "status": "online",
    "channels": ["general"],
    "last_seen": 1234567890
}
```

Đã có:

- `PEERS = {}` in-memory tracker registry.
- `PEER_TTL_SECONDS = 300`.
- `cleanup_inactive_peers(...)` để remove peer offline/expired.
- `peer_list(...)` để trả active peers.
- `tracker_state_payload(...)` để trả dashboard state.

---

### 2.4 Peer-to-peer paradigm: direct peer socket

Yêu cầu spec:

- Direct peer communication.
- Peers exchange messages without routing through centralized server during live sessions.
- Broadcast connection/message to connected peers.
- Multiple peer processes connect together.

Đã implement trong `peer.py`:

Mỗi peer chạy bằng một process riêng:

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
python peer.py --username bob --password wonderland --listen-port 9002
python peer.py --username charlie --password wonderland --listen-port 9003
```

Các thành phần chính:

- `TrackerClient`
  - Login vào tracker.
  - Lưu cookie `session_id`.
  - Gọi `/submit-info`, `/get-list`, `/heartbeat`, `/leave`.
- `PeerNode`
  - Mở TCP server local bằng `asyncio.start_server`.
  - Nhận message từ peer khác.
  - Gửi direct message bằng `asyncio.open_connection`.
  - Broadcast bằng `asyncio.gather`.
  - Lưu inbox local in-memory.
  - Gửi ACK cho message hợp lệ.

CLI commands:

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

Kết quả demo đã chạy:

```text
Alice /list thấy:
alice (you) 127.0.0.1:9001 online channels=['general']
bob 127.0.0.1:9002 online channels=['general']
charlie 127.0.0.1:9003 online channels=['general']

Alice gửi:
> /msg bob hello bob
sent to bob ack=True

Bob nhận:
[direct] alice: hello bob

Alice broadcast:
> /broadcast hello everyone
broadcast to 2 peer(s): 2 succeeded, 0 failed

Bob nhận:
[broadcast] alice: hello everyone

Charlie nhận:
[broadcast] alice: hello everyone
```

Điểm quan trọng:

- Tracker không forward chat message.
- Tracker log chỉ có login/register/get-list/heartbeat/leave.
- Message thật đi qua direct TCP socket giữa `peer.py` processes.

---

## 3. Protocol design đã implement

### 3.1 Framing

P2P protocol dùng **JSON-line framing**:

```text
<JSON object>\n
```

Lý do:

- TCP là byte stream, không giữ ranh giới message.
- JSON-line giúp `StreamReader.readline()` đọc đúng từng message.
- Dễ debug bằng terminal/log.
- Dễ mở rộng message type.

---

### 3.2 Message types

#### HELLO

```json
{
  "type": "hello",
  "from": "alice",
  "listen_host": "127.0.0.1",
  "listen_port": 9001,
  "timestamp": 1234567890.0
}
```

- Dùng để giới thiệu peer.
- Không yêu cầu ACK.

#### DIRECT

```json
{
  "type": "direct",
  "from": "alice",
  "to": "bob",
  "channel": "general",
  "message": "hello bob",
  "message_id": "uuid-...",
  "timestamp": 1234567890.0
}
```

- Gửi trực tiếp từ Alice tới Bob.
- Bob chỉ accept nếu `to == bob`.

#### BROADCAST

```json
{
  "type": "broadcast",
  "from": "alice",
  "channel": "general",
  "message": "hello everyone",
  "message_id": "uuid-...",
  "timestamp": 1234567890.0
}
```

- Alice gửi trực tiếp tới từng peer trong peer list.
- Không đi qua tracker.

#### ACK

```json
{
  "type": "ack",
  "from": "bob",
  "message_id": "uuid-...",
  "timestamp": 1234567890.0
}
```

- Peer nhận gửi lại ACK.
- Sender chờ ACK có đúng `message_id`.

#### ERROR

```json
{
  "type": "error",
  "from": "bob",
  "message": "invalid payload",
  "timestamp": 1234567890.0
}
```

- Dùng khi payload sai format, message sai recipient, hoặc unknown type.

---

### 3.3 Send flow

```text
1. Sender lấy peer list từ tracker.
2. Sender chọn peer target.
3. Sender mở direct TCP connection tới target peer_ip:peer_port.
4. Sender gửi HELLO.
5. Sender gửi DIRECT hoặc BROADCAST payload.
6. Sender đọc response line-by-line.
7. Nếu ACK có đúng message_id -> success.
8. Nếu ERROR hoặc timeout -> failure.
9. Sender close connection.
```

---

## 4. Browser UI đã implement

Browser UI hiện là **tracker dashboard**, không phải chat transport.

Files:

```text
www/login.html
www/chat.html
static/css/chat.css
static/js/chat.js
www/js/chat.js
```

### 4.1 Login page

`www/login.html` có:

- Username field.
- Password field.
- Demo hint: `alice`, `bob`, `charlie` / password `wonderland`.
- Gọi `fetch("/login")`.
- Dùng `credentials: "include"`.
- Login thành công redirect sang `/chat.html`.

### 4.2 Tracker dashboard

`www/chat.html` có:

- Current user.
- Tracker status.
- Active peer count.
- Channel count.
- Peer registration form:
  - `peer_ip`
  - `peer_port`
  - `channel`
- Buttons:
  - Refresh peers.
  - Register peer.
  - Heartbeat.
  - Leave.
  - Logout.
- Active peer cards.
- Demo commands cho `peer.py`.
- Notice rõ ràng:

```text
This web page is only a tracker dashboard.
Direct chat messages are sent by peer.py through TCP sockets.
The tracker does not forward chat messages.
```

### 4.3 JavaScript dashboard logic

`static/js/chat.js` chỉ gọi tracker endpoints:

```text
/me
/tracker-state
/get-list
/submit-info
/heartbeat
/leave
/logout
```

Không gọi các endpoint cũ:

```text
/chat-message
/channel-create
/channel-join
/channel-leave
/send-peer
/broadcast-peer
/connect-peer
```

Điều này giữ đúng kiến trúc: browser UI chỉ hỗ trợ tracker/dashboard, không làm chat transport qua server.

---

## 5. Static serving đã hỗ trợ

`daemon/response.py` đã hỗ trợ static file path:

```text
/login.html
/chat.html
/css/chat.css
/js/chat.js
/static/css/chat.css
/static/js/chat.js
```

Đã có:

- MIME type cho HTML/CSS/JS/JSON.
- `Content-Length`.
- `Connection: close`.
- Path traversal protection.
- 404/405/500 style error response.

---

## 6. Deprecated endpoint handling

Các endpoint server-forwarded P2P cũ hiện được giữ lại để compatibility nhưng reject bằng HTTP 410:

```text
POST /connect-peer
POST /send-peer
POST /broadcast-peer
GET  /peer-inbox
```

Response dạng:

```json
{
  "error": "Deprecated",
  "message": "Direct chat is implemented by peer.py. The tracker does not forward peer messages."
}
```

Ý nghĩa:

- Không phá những test cũ nếu có route check.
- Không làm thầy hiểu nhầm rằng tracker forward chat message.
- Khẳng định kiến trúc P2P thật nằm trong `peer.py`.

---

## 7. Testing đã thực hiện

### 7.1 Compile check

Đã chạy:

```powershell
python -m compileall .
```

Kết quả:

```text
PASS
```

Không có syntax error.

---

### 7.2 HTTP smoke test

Đã chạy:

```powershell
python tests/smoke_http.py
```

Kết quả:

```text
21/21 checks passed
ALL PASSED
```

Các nhóm test đã pass:

- Login returns 200.
- Login returns username.
- Login sets session cookie.
- `/me` without cookie returns 401.
- `/me` with cookie returns 200.
- `/submit-info` returns 200.
- `/submit-info` without cookie returns 401.
- `/get-list` returns 200.
- `/get-list` contains Alice.
- `/heartbeat` returns 200.
- `/tracker-state` returns 200.
- Deprecated endpoints return 410.
- `/leave` returns 200.

---

### 7.3 Live P2P demo test

Đã chạy tracker:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Đã chạy 3 peers:

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
python peer.py --username bob --password wonderland --listen-port 9002
python peer.py --username charlie --password wonderland --listen-port 9003
```

Alice:

```text
/list
/msg bob hello bob
/broadcast hello everyone
```

Kết quả:

```text
sent to bob ack=True
broadcast to 2 peer(s): 2 succeeded, 0 failed
```

Bob nhận:

```text
[direct] alice: hello bob
[broadcast] alice: hello everyone
```

Charlie nhận:

```text
[broadcast] alice: hello everyone
```

=> P2P direct + broadcast đã chạy đúng.

---

## 8. Report/docs đã cập nhật

Các file tài liệu đã có:

```text
README.md
docs/api_reference.md
docs/architecture_diagrams.md
docs/final_report.md
```

Nội dung đã cập nhật đúng:

- Kiến trúc hybrid mới.
- Tracker chỉ làm auth/discovery.
- `peer.py` là transport P2P thật.
- Deprecated server-forwarded endpoints.
- Direct TCP message protocol.
- ACK by `message_id`.
- asyncio non-blocking behavior.
- Demo checklist.
- Limitations.

---

## 9. PEP 8 và PEP 257

Đã áp dụng ở mức tốt:

- Có module docstring trong các file chính như `apps/sampleapp.py`, `peer.py`, `tests/smoke_http.py`.
- Có class docstring:
  - `TrackerClient`
  - `PeerNode`
  - `PeerMessage`
  - `TrackerError`
- Có function/method docstring cho route handlers và public helpers.
- Tên biến/function theo `snake_case`.
- Tên class theo `PascalCase`.
- Hằng số theo `UPPER_CASE`.
- Không dùng external dependencies.
- Giữ copyright/instructor headers trong file framework.

---

## 10. Source cleanliness

Đã làm:

- `.gitignore` ignore:

```text
__pycache__/
*.py[cod]
*$py.class
.env
.venv/
venv/
.DS_Store
**/.DS_Store
```

- `__pycache__/*.pyc` đã được remove khỏi Git tracking.
- Có test folder `tests/`.
- Có README/demo commands.

Trước khi zip nộp LMS, cần xóa generated files local:

```powershell
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -Include *.pyc | Remove-Item -Force
```

---

## 11. Những phần không implement và lý do

### 11.1 Database thật

Không implement database thật.

Lý do:

- Spec không bắt buộc persistent database.
- In-memory state đủ cho assignment demo.
- Đã ghi rõ limitation: restart tracker sẽ mất sessions/peer records.

### 11.2 TLS

Không implement TLS.

Lý do:

- Spec không yêu cầu TLS.
- Tập trung chính là non-blocking, authentication/cookie, tracker, P2P protocol.
- Đã ghi limitation: traffic plaintext.

### 11.3 Browser-based P2P chat

Không cho browser gửi P2P message.

Lý do:

- Browser không mở raw TCP socket trực tiếp như Python peer process.
- Nếu browser gửi message qua `/chat-message`, đó sẽ là server-side chat, làm yếu kiến trúc P2P.
- Vì vậy browser chỉ là tracker dashboard; P2P thật chạy trong `peer.py`.

### 11.4 Full channel creation UI

Không implement server-side full channel create/join/leave UI.

Hiện đã có lightweight channel support:

- Peer register kèm `channels`.
- Tracker trả channel list.
- Message payload có field `channel`.
- UI hiển thị channels.
- Peer CLI/inbox đóng vai trò message display/submission.

Lý do không làm thêm:

- Thêm `/channel-create`, `/chat-message` có thể khiến hệ thống trở lại server-side chat.
- Hiện kiến trúc P2P đã đúng và demo ổn định.

---

## 12. Mapping với rubric điểm

| Rubric | Evidence hiện tại |
|---|---|
| Authentication — 2 điểm | `/login`, cookie `session_id`, `/me`, protected endpoints, smoke test pass |
| ChatApp Client-server — 1 điểm | `/submit-info`, `/get-list`, `/heartbeat`, `/leave`, tracker active peer list |
| ChatApp P2P — 2 điểm | `peer.py`, direct TCP `/msg`, broadcast `/broadcast`, Bob/Charlie nhận message |
| Non-blocking — 2 điểm | asyncio backend + peer server/client + heartbeat + CLI non-blocking |
| Report — 3 điểm | `README.md`, `docs/api_reference.md`, `docs/final_report.md`, architecture diagrams |

---

## 13. Demo script đề xuất

### Step 1: Start tracker

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

### Step 2: Open browser dashboard

```text
http://127.0.0.1:2026/login.html
```

Login:

```text
alice / wonderland
```

### Step 3: Start peers

Terminal Alice:

```powershell
python peer.py --username alice --password wonderland --listen-port 9001
```

Terminal Bob:

```powershell
python peer.py --username bob --password wonderland --listen-port 9002
```

Terminal Charlie:

```powershell
python peer.py --username charlie --password wonderland --listen-port 9003
```

### Step 4: Show tracker discovery

Trong Alice:

```text
/list
```

Expected:

```text
alice (you) 127.0.0.1:9001 online channels=['general']
bob 127.0.0.1:9002 online channels=['general']
charlie 127.0.0.1:9003 online channels=['general']
```

### Step 5: Show direct P2P

Trong Alice:

```text
/msg bob hello bob
```

Expected Alice:

```text
sent to bob ack=True
```

Expected Bob:

```text
[direct] alice: hello bob
```

### Step 6: Show broadcast P2P

Trong Alice:

```text
/broadcast hello everyone
```

Expected Alice:

```text
broadcast to 2 peer(s): 2 succeeded, 0 failed
```

Expected Bob:

```text
[broadcast] alice: hello everyone
```

Expected Charlie:

```text
[broadcast] alice: hello everyone
```

### Step 7: Explain tracker log

Nói rõ:

```text
Tracker log chỉ có /login, /submit-info, /get-list, /heartbeat, /leave.
Không có route nào forward chat message.
```

---

## 14. Câu giải thích ngắn khi thầy hỏi

### Vì sao gọi là hybrid?

Vì hệ thống dùng **client-server** cho authentication và peer discovery, nhưng dùng **peer-to-peer** cho live chat message. Tracker chỉ cung cấp danh sách IP/port của active peers; sau đó peer tự mở direct TCP socket tới nhau.

### Non-blocking nằm ở đâu?

Backend server dùng `asyncio.start_server`, mỗi HTTP connection là coroutine. Peer process cũng dùng `asyncio.start_server` để nhận message và `asyncio.open_connection` để gửi message. Khi một coroutine chờ đọc/ghi socket, event loop tiếp tục xử lý các task khác như CLI input, heartbeat, hoặc connection khác.

### Vì sao tracker không forward message?

Để đảm bảo đúng P2P paradigm. Nếu tracker forward message thì hệ thống trở thành client-server chat. Trong implementation này, message thật chỉ đi qua direct TCP socket giữa `peer.py` processes.

### Vì sao dùng JSON-line?

TCP là byte stream nên cần framing. Mỗi JSON object kết thúc bằng `\n`, giúp peer đọc từng message bằng `readline()` mà không bị dính message.

---

## 15. Final status

Tình trạng hiện tại:

```text
Authentication:                 DONE
Cookie access control:          DONE
Client-server tracker phase:    DONE
Peer registration:              DONE
Peer discovery:                 DONE
Direct P2P communication:       DONE
P2P broadcast:                  DONE
ACK protocol:                   DONE
Non-blocking asyncio:           DONE
Browser tracker dashboard:      DONE
Smoke test:                     PASS
Live 3-peer demo:               PASS
README/docs/report notes:       DONE
```

Project đã sẵn sàng cho final demo/submission sau khi:

1. Xóa `__pycache__` local.
2. Đảm bảo report PDF nằm trong source directory.
3. Zip toàn bộ source đúng tên LMS yêu cầu.
