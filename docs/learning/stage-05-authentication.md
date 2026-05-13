# Stage 05 - Authentication, cookie session và protected routes

## 1. Stage objective

Mục tiêu của stage này là hiểu:

> How does login create a session and how does the server know the user is still logged in?

Sau stage này, bạn cần nắm được:

- Authentication khác authorization như thế nào.
- HTTP Basic Authentication dùng `Authorization` và `WWW-Authenticate` ra sao.
- Cookie-based authentication hoạt động thế nào.
- `Set-Cookie` response header và `Cookie` request header khác nhau ra sao.
- Session ID là gì.
- In-memory session store là gì.
- Vì sao browser tự động gửi cookie trong request sau.
- Vì sao incognito mode hữu ích khi test login/logout.
- Trong project này, login, cookie parsing, `Set-Cookie`, protected route check nằm ở đâu.

Luồng chính của project:

```text
POST /login with username/password
  -> apps/sampleapp.py validates credentials
  -> create random session_id
  -> store session_id in SESSIONS
  -> response has Set-Cookie: session_id=...

Later request to /me or /submit-info
  -> browser/peer sends Cookie: session_id=...
  -> daemon/request.py parses cookies
  -> apps/sampleapp.py looks up session_id in SESSIONS
  -> valid session means user is still logged in
```

## 2. Theory needed before understanding this stage

### Authentication vs authorization

Authentication trả lời câu hỏi:

```text
Bạn là ai?
```

Ví dụ: user nhập username/password. Server kiểm tra đúng thì biết user là `alice`.

Authorization trả lời câu hỏi:

```text
Bạn có quyền làm việc này không?
```

Ví dụ: `alice` đã login nhưng không phải admin, nên không được vào `/admin`.

Trong project:

- Authentication: `/login`, `create_session()`, `get_session()`, `require_user()`.
- Authorization: `require_role(request, "admin")` cho `/admin`.

Nếu chưa login hoặc session invalid, server trả `401 Unauthorized`.

Nếu đã login nhưng không đủ quyền, server trả `403 Forbidden`.

### HTTP Basic Authentication

HTTP Basic Authentication là cơ chế auth có sẵn trong HTTP. Client gửi username/password trong header:

```http
Authorization: Basic <base64(username:password)>
```

Ví dụ nếu `username:password` là:

```text
alice:wonderland
```

client base64 encode chuỗi đó và gửi trong `Authorization`.

Server kiểm tra credentials mỗi request. Nếu thiếu hoặc sai, server thường trả:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="..."
```

`WWW-Authenticate` nói cho browser biết server yêu cầu kiểu authentication nào. Browser có thể hiện dialog login built-in.

Project hiện tại không dùng Basic Authentication cho tracker chính. Source có helper placeholder như `Request.prepare_auth()` và `HttpAdapter.build_proxy_headers()`, nhưng login thật dùng JSON/form body + cookie session.

Cần kiểm tra thêm: assignment gốc có thể nhắc đến Basic Auth ở phase khác. Source hiện tại của `apps/sampleapp.py` dùng cookie-based authentication.

### Authorization header

`Authorization` là request header client gửi lên server:

```http
Authorization: Basic ...
```

hoặc trong hệ thống khác:

```http
Authorization: Bearer <token>
```

Nó nằm trong headers, không nằm trong body.

Trong project hiện tại, `daemon/request.py` parse mọi header vào `request.headers`, nên nếu client gửi `Authorization`, nó sẽ có trong:

```python
request.headers.get("Authorization")
```

Nhưng `apps/sampleapp.py` hiện không dùng header này để login.

### WWW-Authenticate header

`WWW-Authenticate` là response header server gửi khi muốn yêu cầu client authenticate theo cơ chế HTTP authentication.

Ví dụ:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Basic realm="CO3094"
```

Với Basic Auth, header này là tín hiệu chuẩn để browser hỏi username/password.

Trong project hiện tại, response `401` từ `apps/sampleapp.py` là JSON error, không kèm `WWW-Authenticate`, vì project không dùng Basic Auth flow.

### Cookie-based authentication

Cookie-based authentication thường có flow:

1. User gửi credentials đến `/login`.
2. Server validate credentials.
3. Server tạo session ID random.
4. Server lưu session ID trong session store.
5. Server gửi session ID cho client bằng `Set-Cookie`.
6. Browser lưu cookie.
7. Request sau browser tự gửi `Cookie`.
8. Server đọc cookie, tìm session ID trong store, biết user là ai.

Ưu điểm:

- User không cần gửi username/password lại ở mỗi request.
- Server có thể expire session.
- Browser hỗ trợ cookie tự động.

Nhược điểm:

- Nếu không có HTTPS, cookie đi plaintext trên network.
- Nếu session store chỉ ở memory, restart server là mất login.
- Cần chống CSRF/XSS trong app production. Project demo hiện chưa xử lý đầy đủ các vấn đề production này.

### Set-Cookie response header

`Set-Cookie` là response header server gửi cho client:

```http
Set-Cookie: session_id=abc123; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax
```

Ý nghĩa:

- `session_id=abc123`: tên cookie và giá trị.
- `Path=/`: cookie áp dụng cho toàn site.
- `Max-Age=3600`: browser giữ cookie khoảng 3600 giây.
- `HttpOnly`: JavaScript browser không đọc cookie này bằng `document.cookie`.
- `SameSite=Lax`: giảm một số rủi ro CSRF trong navigation cross-site.

Trong project, `apps/sampleapp.py:session_cookie()` tạo chuỗi này.

### Cookie request header

Sau khi browser đã lưu cookie, các request sau đến cùng origin/path sẽ có:

```http
Cookie: session_id=abc123
```

Nếu có nhiều cookie:

```http
Cookie: session_id=abc123; theme=dark
```

Server parse header này để lấy session ID.

Trong project, `daemon/request.py:prepare_cookies()` parse header `Cookie` bằng `http.cookies.SimpleCookie`.

### Session ID

Session ID là token random đại diện cho một login session.

Nó không nên đoán được. Nếu attacker đoán được session ID của user khác, attacker có thể giả làm user đó.

Trong project:

```python
session_id = secrets.token_urlsafe(32)
```

`secrets` phù hợp hơn `random` cho token bảo mật.

Session ID được gửi cho client qua cookie, còn thông tin user thật nằm trong server-side store.

### In-memory session store

Session store là nơi server lưu:

```text
session_id -> user/session data
```

Trong project:

```python
SESSIONS = {}
```

Sau login:

```python
SESSIONS[session_id] = {
    "username": username,
    "role": USERS[username]["role"],
    "created_at": time.time(),
}
```

Đây là in-memory session store. Nó đơn giản, dễ demo, nhưng:

- restart tracker là mất session;
- không share được giữa nhiều process/server;
- không bền vững như database/Redis.

### Why browser automatically sends cookies

Cookie là cơ chế của browser. Khi server trả `Set-Cookie`, browser lưu cookie theo domain/path/same-site/expiration.

Sau đó browser tự gắn cookie vào request phù hợp:

```http
Cookie: session_id=...
```

Frontend JavaScript không cần tự copy session ID vào header. Trong `static/js/chat.js`, các request dùng:

```javascript
fetch(path, { credentials: "include" })
```

Điều này đảm bảo cookie được gửi trong fetch request cùng origin/có credential policy phù hợp.

Với normal page navigation như mở `/chat.html`, browser cũng tự gửi cookie nếu domain/path match.

### Why incognito mode is useful for testing

Incognito/private window có cookie jar riêng. Nó hữu ích khi test auth vì:

- không bị cookie cũ làm nhiễu kết quả;
- dễ test trạng thái "chưa login";
- mở nhiều session khác nhau song song;
- đóng incognito là cookie/session browser-side biến mất;
- tránh nhầm giữa user `alice`, `bob`, `admin` trong cùng browser profile.

Khi debug lỗi `GET /me` vẫn trả user cũ dù bạn tưởng đã logout, incognito là cách nhanh để test sạch.

## 3. Where this concept appears in the assignment requirement

Authentication trong project phục vụ các yêu cầu:

- user phải login trước khi dùng tracker/dashboard;
- peer registration phải gắn với user đã login;
- client không được tự khai username trong request body để giả mạo user khác;
- route riêng tư cần `401` nếu chưa login;
- route admin cần `403` nếu login rồi nhưng role không đủ;
- browser dashboard và `peer.py` có thể dùng session cookie để gọi protected APIs.

Mapping sang source:

- Login route: `apps/sampleapp.py`, route `POST /login`.
- Session creation: `create_session(username)`.
- Cookie creation: `session_cookie(session_id)`.
- Cookie parsing: `daemon/request.py:prepare_cookies()`.
- Protected route checks: `require_user(request)`, `require_role(request, role)`.
- Response header `Set-Cookie`: route result envelope -> `Response.build_route_response()` -> `Response._format()`.
- HTTP dispatch: `HttpAdapter` parse request, call route handler, send response.

Cần kiểm tra thêm: không thấy `future chatapp.py` trong repo hiện tại. Authentication hiện nằm trong `apps/sampleapp.py`.

## 4. Related files in the project

- `apps/sampleapp.py`: chứa `USERS`, `SESSIONS`, `/login`, `/logout`, `/me`, `/private`, `/admin`, tracker protected routes.
- `daemon/request.py`: parse request headers và cookies.
- `daemon/response.py`: build JSON response và gắn response headers như `Set-Cookie`.
- `daemon/httpadapter.py`: đọc HTTP request, tạo `Request`, gọi route handler, gửi response.
- `static/js/chat.js`: browser dashboard dùng `fetch(..., credentials: "include")`.
- `peer.py`: `TrackerClient` lưu cookie từ `Set-Cookie` và gửi lại qua `Cookie` header.

## 5. Detailed source-code reading notes

### 5.1 Where login route is implemented

Login route nằm trong `apps/sampleapp.py`:

```python
@app.route("/login", methods=["POST"])
def login(headers, body, request):
    data = parse_body(body, headers)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    user = USERS.get(username)

    if not user or user["password"] != password:
        return error_response(
            "Invalid credentials",
            status=401,
            error="Unauthorized",
        )

    session_id = create_session(username)
    return json_response(
        {"username": username, "role": user["role"]},
        headers={"Set-Cookie": session_cookie(session_id)},
    )
```

Input:

```http
POST /login HTTP/1.1
Content-Type: application/json

{"username":"alice","password":"wonderland"}
```

Handler làm:

1. Parse body bằng `parse_body(body, headers)`.
2. Lấy `username`, `password`.
3. Tìm user trong `USERS`.
4. So sánh password.
5. Sai -> `401 Unauthorized`.
6. Đúng -> tạo session ID.
7. Trả JSON response kèm `Set-Cookie`.

### 5.2 User database trong project

Source dùng in-memory hard-coded user store:

```python
USERS = {
    "alice": {"password": "wonderland", "role": "user"},
    "bob": {"password": "wonderland", "role": "user"},
    "charlie": {"password": "wonderland", "role": "user"},
    "admin": {"password": "admin123", "role": "admin"},
}
```

Đây không phải database thật. Nó đủ cho assignment demo.

Cần kiểm tra thêm: production system không nên lưu plain text password như vậy. Source hiện tại là demo học networking.

### 5.3 How login creates a session

`create_session(username)`:

```python
def create_session(username):
    session_id = secrets.token_urlsafe(32)
    SESSIONS[session_id] = {
        "username": username,
        "role": USERS[username]["role"],
        "created_at": time.time(),
    }
    return session_id
```

Input:

```python
username = "alice"
```

Output:

```python
session_id = "random-url-safe-token"
```

Side effect:

```python
SESSIONS[session_id] = {
    "username": "alice",
    "role": "user",
    "created_at": 176...,
}
```

Session ID là thứ client giữ. Session data nằm ở server.

### 5.4 Where Set-Cookie is added

`session_cookie(session_id)` tạo header value:

```python
return "{}={}; Path=/; Max-Age={}; HttpOnly; SameSite=Lax".format(
    SESSION_COOKIE,
    session_id,
    SESSION_TTL_SECONDS,
)
```

Với `SESSION_COOKIE = "session_id"` và TTL 3600, output:

```text
session_id=<token>; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax
```

Login route đưa nó vào response envelope:

```python
headers={"Set-Cookie": session_cookie(session_id)}
```

Sau đó `daemon/response.py:build_route_response()` merge route headers vào response headers:

```python
response_headers = {"Content-Type": content_type}
response_headers.update(headers)
return self._format(status_code, content, response_headers)
```

Cuối cùng `_format()` thêm header mặc định và xuất raw HTTP response.

### 5.5 Raw login response looks like what

Sau login thành công, browser/curl nhận response gần như:

```http
HTTP/1.1 200 OK
Date: ...
Server: AsynapRous/1.0
Content-Length: ...
Connection: close
Content-Type: application/json; charset=utf-8
Set-Cookie: session_id=<token>; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax

{"username": "alice", "role": "user"}
```

Browser thấy `Set-Cookie`, rồi lưu cookie `session_id`.

### 5.6 Where cookies are parsed

Cookie parsing nằm trong `daemon/request.py`.

`Request.prepare()` parse headers trước:

```python
self.headers = self.prepare_headers(self._raw_headers)
```

Sau đó parse cookie từ header:

```python
self.cookies = self.prepare_cookies(self.headers.get("Cookie", ""))
```

`prepare_cookies()`:

```python
parsed = cookies.SimpleCookie()
parsed.load(cookie_header or "")
return {key: morsel.value for key, morsel in parsed.items()}
```

Input:

```text
session_id=abc123; theme=dark
```

Output:

```python
{
    "session_id": "abc123",
    "theme": "dark",
}
```

Sau đó route handler có thể đọc:

```python
request.cookies.get("session_id")
```

### 5.7 How the server knows user is still logged in

Server biết user còn login nhờ `get_session(request)`:

```python
def get_session(request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None

    session = SESSIONS.get(session_id)
    if not session:
        return None

    if time.time() - session["created_at"] > SESSION_TTL_SECONDS:
        SESSIONS.pop(session_id, None)
        return None

    return session
```

Flow:

```text
Request has Cookie: session_id=<token>
  -> Request.prepare() parses request.cookies
  -> get_session() reads request.cookies["session_id"]
  -> SESSIONS lookup by token
  -> if exists and not expired, return session data
```

Session data contains:

```python
{"username": "alice", "role": "user", "created_at": ...}
```

Vì vậy server không cần hỏi password lại. Session ID là "vé" tạm thời để server tìm lại login state.

### 5.8 Where protected route checks happen

Protected routes gọi `require_user(request)`:

```python
def require_user(request):
    session = get_session(request)
    if not session:
        return None, error_response(
            "Login required",
            status=401,
            error="Unauthorized",
        )
    return session, None
```

Ví dụ `/me`:

```python
@app.route("/me", methods=["GET"])
def me(headers, body, request):
    session, error = require_user(request)
    if error:
        return error
    return json_response(
        {"username": session["username"], "role": session["role"]}
    )
```

Nếu chưa login:

```text
require_user -> error_response(... status=401)
```

Nếu đã login:

```text
require_user -> session
route returns user JSON
```

Tracker protected routes cũng dùng pattern này:

- `/submit-info`
- `/get-list`
- `/heartbeat`
- `/leave`
- `/tracker-state`
- `/chat-state`

### 5.9 Authorization: admin route and 403

`require_role(request, role)`:

```python
session, error = require_user(request)
if error:
    return None, error
if session["role"] != role:
    return None, error_response(
        "Insufficient permission",
        status=403,
        error="Forbidden",
    )
return session, None
```

`/admin`:

```python
@app.route("/admin", methods=["GET"])
def admin(headers, body, request):
    session, error = require_role(request, "admin")
    if error:
        return error
    return json_response(...)
```

Cases:

- No valid session -> `401 Unauthorized`.
- Valid session but role is `user` -> `403 Forbidden`.
- Valid session and role is `admin` -> `200 OK`.

Đây là khác biệt quan trọng giữa authentication và authorization.

### 5.10 Logout and clearing cookies

`/logout`:

```python
@app.route("/logout", methods=["POST"])
def logout(headers, body, request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        SESSIONS.pop(session_id, None)
    return json_response(
        {"message": "Logout successful"},
        headers={"Set-Cookie": expired_session_cookie()},
    )
```

Nó làm 2 việc:

1. Xóa session server-side khỏi `SESSIONS`.
2. Gửi `Set-Cookie` với `Max-Age=0` để browser xóa cookie.

`expired_session_cookie()`:

```python
return "session_id=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
```

Nếu chỉ xóa cookie nhưng không xóa `SESSIONS`, token cũ có thể vẫn valid nếu client nào đó còn giữ. Nếu chỉ xóa `SESSIONS` nhưng không clear browser cookie, browser vẫn gửi cookie cũ, nhưng server sẽ lookup fail và trả 401. Project làm cả hai.

### 5.11 How Request, HttpAdapter, Response cooperate

Authentication không nằm trong một file duy nhất. Nó là sự phối hợp:

```text
HttpAdapter
  -> reads full HTTP request
  -> Request.prepare()

Request
  -> parses headers
  -> parses Cookie header into request.cookies
  -> finds route handler

HttpAdapter
  -> calls route handler

apps/sampleapp.py
  -> login creates session
  -> protected routes validate session
  -> returns json_response with status/headers/body

Response
  -> turns route result into HTTP response
  -> includes Set-Cookie if route supplied it

HttpAdapter
  -> sends response bytes back to client
```

No single part does everything:

- `Request` does not validate sessions.
- `Response` does not know login logic.
- `HttpAdapter` does not know user roles.
- `apps/sampleapp.py` does not manually read socket or build raw HTTP bytes.

### 5.12 How peer.py uses the same cookie idea

Browser tự quản cookie, nhưng `peer.py` không phải browser. Nó phải tự lưu cookie.

Trong `peer.py`, `TrackerClient._store_cookie()` đọc `Set-Cookie` từ tracker response và lưu:

```python
self.session_cookie = "session_id={}".format(morsel.value)
```

Các request sau thêm:

```python
headers["Cookie"] = self.session_cookie
```

Nghĩa là `peer.py` mô phỏng hành vi browser: nhận `Set-Cookie`, gửi lại `Cookie`.

Stage này không yêu cầu đọc `peer.py`, nhưng chi tiết này giúp hiểu vì sao peer CLI cũng authenticate được với tracker.

## 6. Execution/data flow explanation

### 6.1 Login from browser

```text
Browser submits login form
  -> POST /login with username/password
  -> HttpAdapter reads HTTP request
  -> Request.prepare parses headers/body
  -> req.hook = login
  -> login parses body
  -> login checks USERS
  -> create_session("alice")
  -> SESSIONS[token] = session data
  -> response envelope contains Set-Cookie
  -> Response builds HTTP response
  -> browser stores session_id cookie
```

### 6.2 Later browser request to protected route

```text
Browser requests /me
  -> automatically sends Cookie: session_id=<token>
  -> Request.prepare parses cookies
  -> me() calls require_user(request)
  -> get_session() finds token in SESSIONS
  -> route returns {"username":"alice","role":"user"}
```

### 6.3 Unauthenticated request

```text
GET /me with no Cookie
  -> request.cookies = {}
  -> get_session() returns None
  -> require_user() returns 401 error response
  -> client receives HTTP 401 JSON
```

### 6.4 Authenticated but not authorized

```text
alice logs in
GET /admin with alice session cookie
  -> get_session() returns {"username":"alice","role":"user"}
  -> require_role(..., "admin") sees role mismatch
  -> returns 403 Forbidden
```

### 6.5 Session expiration

```text
GET /me with old Cookie
  -> get_session() finds session
  -> current time - created_at > SESSION_TTL_SECONDS
  -> SESSIONS.pop(session_id)
  -> return None
  -> require_user returns 401
```

## 7. Important functions/classes and their role

| Function/class/constant | File | Role |
|---|---|---|
| `Request.prepare()` | `daemon/request.py` | Parse raw HTTP request and populate `request.cookies` |
| `Request.prepare_headers()` | `daemon/request.py` | Parse headers before cookies can be read |
| `Request.prepare_cookies()` | `daemon/request.py` | Convert `Cookie` header into dict |
| `HttpAdapter.handle_client_coroutine()` | `daemon/httpadapter.py` | Read request, call `Request.prepare()`, dispatch route |
| `HttpAdapter._dispatch_route_async()` | `daemon/httpadapter.py` | Call protected route handler after routing |
| `Response.build_route_response()` | `daemon/response.py` | Convert route envelope into response with headers |
| `Response._format()` | `daemon/response.py` | Build final HTTP response bytes, including `Set-Cookie` |
| `USERS` | `apps/sampleapp.py` | In-memory credential/role store |
| `SESSIONS` | `apps/sampleapp.py` | In-memory session store |
| `SESSION_COOKIE` | `apps/sampleapp.py` | Cookie name: `session_id` |
| `SESSION_TTL_SECONDS` | `apps/sampleapp.py` | Session lifetime: 3600 seconds |
| `parse_body()` | `apps/sampleapp.py` | Parse login body JSON/form |
| `login()` | `apps/sampleapp.py` | Authenticate credentials and issue cookie |
| `create_session()` | `apps/sampleapp.py` | Generate token and store session |
| `session_cookie()` | `apps/sampleapp.py` | Build `Set-Cookie` value |
| `expired_session_cookie()` | `apps/sampleapp.py` | Build cookie-clearing `Set-Cookie` value |
| `get_session()` | `apps/sampleapp.py` | Lookup and validate session ID from request cookie |
| `require_user()` | `apps/sampleapp.py` | Protected route guard, returns 401 if not logged in |
| `require_role()` | `apps/sampleapp.py` | Authorization guard, returns 403 if role insufficient |
| `logout()` | `apps/sampleapp.py` | Remove server session and clear browser cookie |

## 8. Common mistakes/misunderstandings

- Nhầm authentication với authorization. Login thành công chưa chắc có quyền admin.
- Nghĩ `Set-Cookie` là request header. Không đúng: server gửi `Set-Cookie` trong response.
- Nghĩ `Cookie` là response header. Không đúng: client gửi `Cookie` trong request.
- Nghĩ session ID chứa toàn bộ user data. Trong project, session ID chỉ là key; user data nằm trong `SESSIONS`.
- Nghĩ browser cần JavaScript tự gửi cookie. Browser tự gửi cookie phù hợp; fetch chỉ cần credential policy đúng khi cần.
- Nghĩ `Request` tự quyết định user đã login. Không đúng: `Request` chỉ parse cookie; `apps/sampleapp.py` validate session.
- Nghĩ `HttpAdapter` biết route nào cần login. Không đúng: protected checks nằm trong route handler/helper như `require_user()`.
- Nghĩ restart tracker vẫn giữ login. Không đúng: `SESSIONS` là in-memory.
- Nghĩ `401` và `403` giống nhau. `401` là chưa authenticated; `403` là authenticated nhưng không đủ quyền.
- Nghĩ Basic Auth đang được dùng trong tracker. Source hiện tại dùng cookie-based authentication.
- Quên test bằng incognito, dẫn đến cookie cũ làm kết quả khó hiểu.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] I can explain Set-Cookie.
- [ ] I can explain Cookie header.
- [ ] I can explain session ID.
- [ ] I know where to parse cookies in this project.
- [ ] I know where to validate authenticated requests.
- [ ] I know the difference between 401 and 403.
- [ ] Tôi giải thích được login tạo session như thế nào.
- [ ] Tôi biết `SESSIONS` lưu gì và vì sao restart server sẽ mất login.
- [ ] Tôi biết browser tự gửi cookie trong request sau.
- [ ] Tôi biết `Request.prepare_cookies()` chỉ parse cookie, không authenticate.
- [ ] Tôi biết `require_user()` là guard chính cho protected routes.
- [ ] Tôi biết `require_role()` là authorization guard cho admin route.

## 10. Suggested test commands or observation commands if applicable

Chạy tracker:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Login và xem `Set-Cookie`:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Gọi `/me` không cookie, kỳ vọng `401`:

```powershell
curl.exe -i http://127.0.0.1:2026/me
```

Gọi `/me` với cookie:

```powershell
curl.exe -i http://127.0.0.1:2026/me -H "Cookie: session_id=<value-from-login>"
```

Test user thường vào admin, kỳ vọng `403`:

```powershell
curl.exe -i http://127.0.0.1:2026/admin -H "Cookie: session_id=<alice-session>"
```

Login admin rồi vào admin:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"admin\",\"password\":\"admin123\"}"
curl.exe -i http://127.0.0.1:2026/admin -H "Cookie: session_id=<admin-session>"
```

Logout:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/logout -H "Cookie: session_id=<value-from-login>"
```

Quan sát code auth:

```powershell
rg -n "SESSION|USERS|login|logout|get_session|require_user|require_role|Set-Cookie|prepare_cookies" apps/sampleapp.py daemon/request.py daemon/response.py
```

Chạy smoke test nếu tracker đang chạy:

```powershell
python tests/smoke_http.py
```

## 11. Suggested commit message

Suggested commit message:

```text
docs: add stage 05 authentication explanation
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-05-authentication.md
git commit -m "docs: add stage 05 authentication explanation" -- docs/learning/stage-05-authentication.md
```
