# Stage 02 - HTTP request/response lifecycle

## 1. Stage objective

Mục tiêu của stage này là trả lời thật rõ câu hỏi:

> Khi browser gửi request đến server này, làm sao bytes trên TCP connection trở thành một `Request` object, rồi cuối cùng thành một HTTP response gửi ngược lại browser?

Stage này tập trung vào 3 file:

- `daemon/httpadapter.py`: nhận bytes từ socket/async stream, đọc đủ HTTP message, dispatch route, gửi response bytes.
- `daemon/request.py`: parse raw HTTP message thành object có `method`, `path`, `headers`, `body`, `cookies`, `hook`.
- `daemon/response.py`: build HTTP response bytes, gồm status line, headers, body, static file content, MIME type, JSON response.

Không có code mới trong stage này. Mục tiêu là hiểu lifecycle:

```text
TCP bytes
  -> complete HTTP request text
  -> Request object
  -> route/static dispatch
  -> Response bytes
  -> TCP bytes back to browser
```

## 2. Theory needed before understanding this stage

### TCP connection vs HTTP message

TCP connection là kênh truyền bytes giữa client và server. HTTP request là một message có cấu trúc nằm bên trong dòng bytes đó.

TCP không tự biết đâu là "một HTTP request hoàn chỉnh". Server phải tự đọc theo quy tắc HTTP:

- Headers kết thúc bằng blank line `\r\n\r\n`.
- Nếu có body, body dài bao nhiêu được chỉ ra bởi `Content-Length`.

Vì vậy không thể hiểu đơn giản rằng một lần `recv()` hoặc một lần `read()` là một request. TCP có thể chia request thành nhiều chunk hoặc gộp nhiều bytes tùy network/buffer.

Trong project:

- Blocking path dùng `conn.recv(...)` trong `_read_http_message()`.
- Async path dùng `StreamReader.readuntil(...)` và `StreamReader.readexactly(...)` trong `_read_http_message_async()`.

### HTTP request line

Request line là dòng đầu tiên của HTTP request:

```http
GET /chat.html HTTP/1.1
```

Nó có 3 phần:

- HTTP method: `GET`
- request target/URL path: `/chat.html`
- HTTP version: `HTTP/1.1`

Trong project, `Request.extract_request_line()` tách dòng này và validate rằng có đúng 3 phần, version bắt đầu bằng `HTTP/`.

### HTTP method

Method nói client muốn làm gì:

- `GET`: lấy resource, thường là static file hoặc API đọc dữ liệu.
- `POST`: gửi dữ liệu tạo/thực hiện action, ví dụ `/login`, `/submit-info`.
- `PUT`: update resource, project support ở adapter nhưng không phải trọng tâm tracker hiện tại.
- `DELETE`: xóa/leave, ví dụ `/leave` có support `DELETE`.

Trong project, `HttpAdapter.SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE"}`.

Nếu method không nằm trong tập này, server trả `405 Method Not Allowed`.

### URL/path

Trong request line, phần thứ hai là request target:

```http
GET /get-list?channel=general HTTP/1.1
```

Target gồm:

- Path: `/get-list`
- Query string: `channel=general`

Route matching thường dùng path, không dùng query string. Trong project:

- `Request.prepare_query_params()` dùng `urlsplit(target)`.
- `self.path = parsed.path or "/"`.
- `self.query_params = parse_qs(parsed.query, keep_blank_values=True)`.
- `self.hook = routes.get((self.method, self.path))`.

Vì vậy `/get-list?channel=general` vẫn match route `("GET", "/get-list")`.

### Headers

Headers là metadata sau request line:

```http
Host: 127.0.0.1:2026
User-Agent: curl/...
Content-Type: application/json
Content-Length: 42
Cookie: session_id=abc
```

Headers giúp server hiểu body, cookie, connection, accepted format, v.v.

Trong project, `Request.prepare_headers()` parse từng dòng header bằng dấu `:` đầu tiên, rồi lưu vào `CaseInsensitiveDict`. Điều này quan trọng vì HTTP header names không phân biệt hoa thường: `content-length` và `Content-Length` nên được hiểu giống nhau.

### Body

Body là phần sau blank line `\r\n\r\n`. Không phải request nào cũng có body.

Ví dụ `POST /login`:

```http
POST /login HTTP/1.1
Host: 127.0.0.1:2026
Content-Type: application/json
Content-Length: 44

{"username":"alice","password":"wonderland"}
```

Trong project:

- `HttpAdapter` chịu trách nhiệm đọc đủ body từ TCP stream.
- `Request.fetch_headers_body()` chỉ split raw request text thành header text và body text.
- `Request.prepare()` gán `self.body = self._raw_body`.

Điểm cần nhớ: body được đọc ở adapter, còn body được tách và lưu vào object ở request parser.

### Content-Length

`Content-Length` cho biết body có bao nhiêu bytes. Đây là header cực kỳ quan trọng cho request có body.

Nếu server chỉ đọc đến `\r\n\r\n`, nó mới có headers, chưa chắc đã có body. Sau khi đọc headers, server phải nhìn `Content-Length` để đọc tiếp đúng số bytes body.

Trong project:

- `_content_length_from_headers()` đọc header `Content-Length`.
- Nếu không có, mặc định body length là `0`.
- Nếu giá trị không parse được thành integer, code warning và trả `0`.
- Nếu body vượt `MAX_BODY_BYTES = 1024 * 1024`, raise `ValueError("request body too large")`, sau đó trả `413 Payload Too Large`.

Cần kiểm tra thêm: khi `Content-Length` không hợp lệ, project hiện trả length `0` thay vì trực tiếp trả `400`. Đây là hành vi hiện tại của source, không nhất thiết là HTTP server production nên làm.

### Content-Type

`Content-Type` nói body đang ở format gì:

```http
Content-Type: application/json
```

hoặc:

```http
Content-Type: application/x-www-form-urlencoded
```

Trong 3 file stage này, `Content-Type` chủ yếu được giữ trong `Request.headers`. Việc parse body theo JSON hay form nằm ở application layer, ví dụ `apps/sampleapp.py:parse_body()`.

Ở response side, `Content-Type` cũng rất quan trọng để browser biết cách hiểu response body:

- HTML: `text/html; charset=utf-8`
- CSS: `text/css; charset=utf-8`
- PNG: `image/png`
- JSON: `application/json; charset=utf-8`

Trong project, `Response` set response `Content-Type` khi build static file hoặc JSON route response.

### Cookies

Cookie nằm trong HTTP headers, không nằm trong request body:

```http
Cookie: session_id=abc123; theme=dark
```

Server trả cookie mới bằng response header:

```http
Set-Cookie: session_id=abc123; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax
```

Trong project:

- Request cookie được parse ở `Request.prepare_cookies()`.
- `Request.prepare()` gọi `self.prepare_cookies(self.headers.get("Cookie", ""))`.
- Route handler như `apps/sampleapp.py` đọc `request.cookies`.
- Response `Set-Cookie` được truyền qua route result headers, rồi `Response.build_route_response()` đưa vào response headers.

### HTTP response status line

Response bắt đầu bằng status line:

```http
HTTP/1.1 200 OK
```

Nó có:

- HTTP version
- status code
- reason phrase

Trong project, `Response._format()` tạo status line:

```python
"HTTP/1.1 {} {}\r\n".format(status_code, reason)
```

`reason` lấy từ `Response.STATUS_REASONS`.

### Status code

Status code cho client biết kết quả:

- `200 OK`: thành công.
- `400 Bad Request`: request malformed.
- `401 Unauthorized`: thiếu/invalid auth.
- `403 Forbidden`: bị cấm.
- `404 Not Found`: không có route/file.
- `405 Method Not Allowed`: method không support.
- `408 Request Timeout`: đọc request quá lâu.
- `410 Gone`: endpoint deprecated.
- `413 Payload Too Large`: body quá lớn.
- `500 Internal Server Error`: lỗi server không xử lý được.

Trong project, status code được tạo ở `Response.build_error()`, `Response.build_notfound()`, `Response.build_json_response()`, hoặc route envelope từ `apps/sampleapp.py`.

### Response headers

Response headers là metadata server gửi về:

```http
Date: ...
Server: AsynapRous/1.0
Content-Length: 123
Connection: close
Content-Type: application/json; charset=utf-8
Set-Cookie: session_id=...
```

Trong project, `Response._format()` luôn tạo base headers:

- `Date`
- `Server`
- `Content-Length`
- `Connection`

Sau đó merge thêm headers được truyền vào, ví dụ `Content-Type`, `Set-Cookie`.

### Response body

Body là payload sau blank line của response. Nó có thể là:

- HTML bytes của `www/chat.html`.
- CSS/JS/image bytes.
- JSON bytes từ API.
- Text error như `404 Not Found`.

Trong project, `_format()` trả về:

```text
status line + headers + blank line + content bytes
```

### MIME type

MIME type là giá trị của `Content-Type` để mô tả loại file/body.

Ví dụ:

- `.html` -> `text/html`
- `.css` -> `text/css`
- `.js` -> thường là `text/javascript` hoặc `application/javascript` tùy hệ thống
- `.png` -> `image/png`

Trong project, `Response.get_mime_type()` dùng `mimetypes.guess_type(path)`. Nếu không biết, fallback `application/octet-stream`.

Nếu MIME bắt đầu bằng `text/`, project thêm `charset=utf-8`.

### Static file serving

Static file serving nghĩa là request path được map đến file trong filesystem.

Ví dụ:

```text
GET /chat.html -> www/chat.html
GET /static/js/chat.js -> static/js/chat.js
GET /css/chat.css -> static/css/chat.css
GET / -> www/index.html
```

Trong project:

- `HttpAdapter._dispatch_route_async()` nếu không có route và method là `GET`, gọi `resp.build_response(req)`.
- `Response.build_response()` gọi `_normalise_static_path(request.path)`.
- `Response.build_content()` mở file bằng `open(filepath, "rb")`.
- Nếu file không tồn tại, trả `404`.

`_normalise_static_path()` cũng chặn path traversal bằng `os.path.commonpath(...)`.

### JSON response

API route thường trả JSON. Trong project, route handler thường trả envelope:

```python
{
    "status": 200,
    "headers": {},
    "body": {"message": "ok"},
    "content_type": "application/json; charset=utf-8",
}
```

`Response.build_route_response()` nhận envelope này, encode body bằng `json.dumps(...)`, set `Content-Type`, rồi gọi `_format()`.

Nếu route trả dict thường không có keys `status`, `body`, `headers`, `content_type`, project cũng xem nó như JSON và gọi `build_json_response()`.

## 3. Where this concept appears in the assignment requirement

Trong assignment Computer Networks, HTTP request/response lifecycle là phần nền để hiểu backend tự viết không dùng Flask/FastAPI/Django.

Mapping sang project:

- TCP socket server: `daemon/backend.py` tạo server, còn `daemon/httpadapter.py` xử lý connection cụ thể.
- HTTP request parser: `daemon/request.py`.
- HTTP response builder: `daemon/response.py`.
- Static file server: `daemon/response.py`.
- REST-like route dispatcher: `daemon/httpadapter.py` kết hợp với route table từ `AsynapRous`.
- Cookie/session support: cookie được parse trong `daemon/request.py`, session logic nằm ngoài stage này ở `apps/sampleapp.py`.

Cần kiểm tra thêm: đề bài chính thức có thể yêu cầu chi tiết khác về HTTP/1.1, keep-alive hoặc persistent connection. Source hiện tại luôn set `Connection: close` và đóng connection sau mỗi response.

## 4. Related files in the project

- `daemon/httpadapter.py`: nơi HTTP bytes được đọc từ socket/stream, route được dispatch, response được ghi ngược lại client.
- `daemon/request.py`: nơi raw request text được parse thành `Request`.
- `daemon/response.py`: nơi response bytes được xây dựng.
- `daemon/backend.py`: tạo TCP/asyncio server và gọi `HttpAdapter`, nhưng không phải trọng tâm stage này.
- `apps/sampleapp.py`: route handlers trả JSON envelope; hữu ích để thấy `Response.build_route_response()` được dùng thế nào.
- `www/` và `static/`: nơi static files được load khi browser request HTML/CSS/JS/images.

## 5. Detailed source-code reading notes

### 5.1 `HttpAdapter`: điểm giao giữa TCP và HTTP

`HttpAdapter` được tạo cho một client connection. Nó có:

```python
self.request = Request()
self.response = Response()
```

Nó không phải parser chi tiết và cũng không phải application handler. Nó là adapter ở giữa:

```text
TCP stream
  -> read complete HTTP message
  -> Request.prepare()
  -> route/static dispatch
  -> Response.build_response()
  -> write bytes back
```

Các constant quan trọng:

- `SUPPORTED_METHODS = {"GET", "POST", "PUT", "DELETE"}`
- `BUFFER_SIZE = 4096`
- `READ_TIMEOUT = 15`
- `MAX_BODY_BYTES = 1024 * 1024`

### 5.2 Where request bytes are received

Trong synchronous path:

```python
def _read_http_message(self, conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(self.BUFFER_SIZE)
```

Bytes được nhận bằng `conn.recv(...)`.

Trong async path:

```python
header_bytes = await reader.readuntil(b"\r\n\r\n")
body = await reader.readexactly(content_length)
```

Bytes được nhận từ `StreamReader`.

Source hiện tại mặc định backend chạy async, nên đường quan trọng hơn là:

```text
handle_client_coroutine()
  -> _read_http_message_async(reader)
```

### 5.3 How headers and body are read from TCP

`_read_http_message_async()` đọc headers trước:

```python
header_bytes = await reader.readuntil(b"\r\n\r\n")
```

Sau đó decode headers:

```python
header_text = header_bytes.decode("iso-8859-1", errors="replace")
```

Rồi tìm body length:

```python
content_length = self._content_length_from_headers(header_text)
```

Nếu có body:

```python
body = await reader.readexactly(content_length)
```

Cuối cùng ghép lại thành raw HTTP message string:

```python
return (
    header_bytes.rstrip(b"\r\n")
    + b"\r\n\r\n"
    + body
).decode("utf-8", errors="replace")
```

Điểm tinh tế: headers được decode bằng `iso-8859-1`, nhưng message cuối decode bằng `utf-8`. Với body JSON UTF-8 thì hợp lý, nhưng với binary body upload thì thiết kế này chưa đầy đủ.

Cần kiểm tra thêm: project hiện không có upload binary body trong route API, nên hạn chế này chưa ảnh hưởng demo hiện tại.

### 5.4 Where Content-Length is parsed

`HttpAdapter._content_length_from_headers(header_text)`:

```python
for line in header_text.split("\r\n")[1:]:
    if line.lower().startswith("content-length:"):
        content_length = int(line.split(":", 1)[1].strip())
```

Nó bỏ qua request line bằng `[1:]`, tìm header tên `Content-Length`, parse số integer.

Nếu body quá lớn:

```python
if content_length > self.MAX_BODY_BYTES:
    raise ValueError("request body too large")
```

`handle_client_coroutine()` bắt `ValueError` và dùng `_request_error_response()`:

- `"request body too large"` -> `413 Payload Too Large`
- lỗi khác -> `400 Bad Request`

### 5.5 `Request`: raw HTTP text thành object

Sau khi adapter có raw HTTP message text, nó gọi:

```python
req.prepare(msg, self.routes)
```

Trong `Request.prepare()`:

1. `fetch_headers_body(request)` split message thành `_raw_headers` và `_raw_body`.
2. `extract_request_line(self._raw_headers)` parse method, target, version.
3. `prepare_query_params(target)` tách path và query.
4. `prepare_headers(self._raw_headers)` parse headers.
5. `prepare_cookies(self.headers.get("Cookie", ""))` parse cookies.
6. `self.hook = routes.get((self.method, self.path))` tìm route handler.

Sau bước này, adapter không cần xử lý chuỗi raw nữa; nó làm việc với object.

### 5.6 Where request line is parsed

`Request.extract_request_line(header_text)`:

```python
lines = header_text.splitlines()
parts = lines[0].split()
if len(parts) != 3:
    raise ValueError(...)
method, target, version = parts
```

Ví dụ:

```http
POST /login HTTP/1.1
```

trở thành:

```text
method = "POST"
target = "/login"
version = "HTTP/1.1"
```

Method được upper-case:

```python
return method.upper(), target, version
```

### 5.7 Where URL/path is parsed

`Request.prepare_query_params(target)`:

```python
parsed = urlsplit(target)
self.url = target
self.path = parsed.path or "/"
self.query_params = parse_qs(parsed.query, keep_blank_values=True)
```

Ví dụ:

```text
/get-list?channel=general&include_inactive=true
```

trở thành:

```python
self.path = "/get-list"
self.query_params = {
    "channel": ["general"],
    "include_inactive": ["true"],
}
```

Route lookup chỉ dùng `self.path`, nên query string không làm route bị lệch.

### 5.8 Where headers are parsed

`Request.prepare_headers(header_text)`:

```python
for line in header_text.split("\r\n")[1:]:
    if ":" not in line:
        LOGGER.warning(...)
        continue
    key, value = line.split(":", 1)
    headers[key.strip()] = value.strip()
```

Dòng đầu tiên là request line nên bị bỏ qua. Mỗi header line được split ở dấu `:` đầu tiên.

Headers được lưu vào `CaseInsensitiveDict`, nên các lookup như:

```python
self.headers.get("Cookie", "")
```

vẫn ổn kể cả client gửi `cookie:` hoặc `COOKIE:`.

### 5.9 Where body is parsed

Trong stage này cần phân biệt:

- `HttpAdapter` đọc đủ body bytes từ TCP dựa trên `Content-Length`.
- `Request.fetch_headers_body()` tách body text khỏi raw request.
- `Request.prepare()` lưu body text vào `self.body`.
- Parse semantic JSON/form không nằm trong `Request`; nó nằm ở application layer.

Code tách headers/body:

```python
parts = request.split("\r\n\r\n", 1)
header_text = parts[0]
body = parts[1] if len(parts) > 1 else ""
```

Vì split dùng `1`, body vẫn có thể chứa chuỗi `\r\n\r\n` bên trong mà không bị split thêm.

### 5.10 Where cookies should be parsed

Cookies được parse trong `Request.prepare_cookies(cookie_header)`:

```python
parsed = cookies.SimpleCookie()
parsed.load(cookie_header or "")
return {key: morsel.value for key, morsel in parsed.items()}
```

Và được gọi trong `Request.prepare()`:

```python
self.cookies = self.prepare_cookies(self.headers.get("Cookie", ""))
```

Vì cookie là request header, thứ tự đúng là:

```text
parse headers -> read Cookie header -> parse cookies
```

Sau đó route handler nhận `request` object và có thể dùng:

```python
request.cookies.get("session_id")
```

### 5.11 Route dispatch

Sau khi `Request.prepare()` set `req.hook`, adapter dispatch:

```python
response = await self._dispatch_route_async(req, resp)
```

Logic:

1. Nếu method không support -> `405`.
2. Nếu không có route và method là `GET` -> thử static file.
3. Nếu không có route và không phải `GET` -> `404`.
4. Nếu có route -> gọi route handler.
5. Build response từ route result.

Code async route call:

```python
result = await self._call_route_async(req)
return resp.build_response(req, envelop_content=result)
```

`_call_route_async()` hỗ trợ cả sync function và async function:

- Nếu route là coroutine function, `await req.hook(*args)`.
- Nếu route là sync function, chạy bằng `asyncio.to_thread(...)`.

### 5.12 How route arguments are chosen

`_route_arguments(req)` inspect signature của route handler:

```python
if len(positional) >= 3:
    return req.headers, req.body, req
return req.headers, req.body
```

Điều này giữ compatibility với route cũ chỉ nhận `(headers, body)`, đồng thời route mới có thể nhận thêm `request`.

Ví dụ:

- `hello(headers, body)` nhận 2 args.
- `login(headers, body, request)` nhận 3 args để đọc cookies/connection/query nếu cần.

### 5.13 Where response headers are built

`Response._format(status_code, content, headers=None)` là trung tâm build response.

Nó tạo base headers:

```python
response_headers = {
    "Date": self._http_date(),
    "Server": "AsynapRous/1.0",
    "Content-Length": str(len(content)),
    "Connection": "close",
}
response_headers.update(headers or {})
```

Sau đó tạo status line:

```python
status_line = "HTTP/1.1 {} {}\r\n".format(status_code, reason)
```

Và header lines:

```python
header_lines = [
    "{}: {}\r\n".format(key, value)
    for key, value in response_headers.items()
]
```

Cuối cùng:

```python
self._header = (status_line + "".join(header_lines) + "\r\n").encode("iso-8859-1")
return self._header + self._content
```

Đây là nơi response object thật sự trở thành bytes hợp lệ để gửi qua TCP.

### 5.14 Where static files are loaded

Static serving bắt đầu từ `Response.build_response()` khi không có `envelop_content`.

```python
filepath = self._normalise_static_path(request.path)
length, content = self.build_content(filepath, base_dir="")
```

`_normalise_static_path()` map URL path sang local file:

- `/` -> `/index.html` trong root `www`.
- `/static/...` -> `static/...`.
- `/css/...`, `/images/...` -> `static/css/...`, `static/images/...`.
- `/favicon.ico` -> `static/images/favicon.ico`.
- path khác -> `www/...`.

Nó dùng absolute path và `os.path.commonpath(...)` để chặn path traversal như:

```text
/../../secret.txt
```

`build_content()` mở file dạng binary:

```python
with open(filepath, "rb") as file_obj:
    content = file_obj.read()
```

Nếu không có file, trả `-1, b""`, rồi `build_response()` chuyển thành `404`.

### 5.15 Where MIME type is decided

Sau khi static file được đọc, `Response.build_response()` gọi:

```python
mime_type = self.get_mime_type(filepath)
```

`get_mime_type()` dùng:

```python
mimetypes.guess_type(path)
```

Nếu là text:

```python
if mime_type.startswith("text/"):
    mime_type = "{}; charset=utf-8".format(mime_type)
```

Sau đó `_format()` nhận:

```python
{"Content-Type": mime_type}
```

Browser dựa vào header này để render HTML, apply CSS, execute JS, hoặc hiển thị image đúng cách.

### 5.16 Where JSON responses are built

Có 2 đường JSON:

Đường 1, route trả dict thường:

```python
return {"message": "ok"}
```

`build_route_response()` thấy không phải envelope, gọi:

```python
return self.build_json_response(result)
```

Đường 2, route trả envelope:

```python
{
    "status": 200,
    "headers": {"Set-Cookie": "..."},
    "body": {"username": "alice"},
    "content_type": "application/json; charset=utf-8",
}
```

`build_route_response()`:

- lấy `status_code`
- lấy `body`
- lấy `headers`
- lấy `content_type`
- nếu content type là JSON, encode bằng `json.dumps(body).encode("utf-8")`
- gọi `_format(status_code, content, response_headers)`

Đây là đường dùng nhiều trong `apps/sampleapp.py` thông qua helper `json_response()`.

### 5.17 Where response bytes are sent

Trong synchronous path:

```python
conn.sendall(response)
conn.shutdown(2)
conn.close()
```

Trong async path:

```python
writer.write(response)
await writer.drain()
writer.close()
await writer.wait_closed()
```

Vì response đã là bytes từ `Response._format()`, writer chỉ cần gửi bytes đó qua TCP connection.

Project luôn đóng connection sau response (`Connection: close`), nên không có request thứ hai trên cùng connection trong lifecycle hiện tại.

## 6. Execution/data flow explanation

### Example 1: Browser requests a static page

Request:

```http
GET /chat.html HTTP/1.1
Host: 127.0.0.1:2026
Cookie: session_id=abc

```

Flow:

```text
1. Browser opens TCP connection to 127.0.0.1:2026.
2. daemon.backend accepts connection and gives StreamReader/StreamWriter to HttpAdapter.
3. HttpAdapter._read_http_message_async() reads headers until \r\n\r\n.
4. Content-Length is absent, so body length is 0.
5. Request.prepare() parses:
   method = GET
   path = /chat.html
   headers["Host"] = 127.0.0.1:2026
   cookies["session_id"] = abc
   body = ""
6. routes.get(("GET", "/chat.html")) returns None.
7. _dispatch_route_async() sees no route + GET, so calls Response.build_response(req).
8. Response._normalise_static_path("/chat.html") maps to www/chat.html.
9. Response.build_content() reads file bytes.
10. Response.get_mime_type() returns text/html, then adds charset.
11. Response._format() builds HTTP/1.1 200 OK + headers + HTML body.
12. HttpAdapter writes response bytes and closes connection.
```

### Example 2: Peer/browser posts JSON to `/login`

Request:

```http
POST /login HTTP/1.1
Host: 127.0.0.1:2026
Content-Type: application/json
Content-Length: 44

{"username":"alice","password":"wonderland"}
```

Flow:

```text
1. HttpAdapter reads headers until blank line.
2. _content_length_from_headers() returns 44.
3. _read_http_message_async() reads exactly 44 body bytes.
4. Request.prepare() parses method/path/headers/body.
5. Request.hook = routes.get(("POST", "/login")).
6. _dispatch_route_async() calls route handler.
7. apps/sampleapp.py parses JSON body at application layer.
8. Route returns JSON envelope with body and Set-Cookie header.
9. Response.build_route_response() JSON-encodes body.
10. Response._format() adds Date, Server, Content-Length, Connection, Content-Type, Set-Cookie.
11. HttpAdapter writes response bytes.
```

Response shape:

```http
HTTP/1.1 200 OK
Date: ...
Server: AsynapRous/1.0
Content-Length: ...
Connection: close
Content-Type: application/json; charset=utf-8
Set-Cookie: session_id=...; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax

{"username": "alice", "role": "user"}
```

### Example 3: POST route missing

Request:

```http
POST /not-exist HTTP/1.1
Host: 127.0.0.1:2026
Content-Length: 0

```

Flow:

```text
1. Request parses successfully.
2. req.hook is None.
3. Method is POST, not static GET.
4. _dispatch_route_async() returns Response.build_notfound().
5. Response is 404 text/plain.
```

### Example 4: Oversized body

If `Content-Length` lớn hơn `MAX_BODY_BYTES`, adapter raise `ValueError("request body too large")`.

Flow:

```text
_content_length_from_headers()
  -> ValueError
handle_client_coroutine()
  -> _request_error_response()
  -> Response.build_error(413, "413 Payload Too Large")
```

## 7. Important functions/classes and their role

| Function/class | File | Role |
|---|---|---|
| `HttpAdapter` | `daemon/httpadapter.py` | Điều phối lifecycle của một HTTP connection |
| `_read_http_message()` | `daemon/httpadapter.py` | Đọc request từ blocking socket |
| `_read_http_message_async()` | `daemon/httpadapter.py` | Đọc request từ asyncio `StreamReader` |
| `_content_length_from_headers()` | `daemon/httpadapter.py` | Tìm và validate `Content-Length` |
| `handle_client_coroutine()` | `daemon/httpadapter.py` | Async connection handler chính |
| `_dispatch_route_async()` | `daemon/httpadapter.py` | Chọn route/static/error response |
| `_call_route_async()` | `daemon/httpadapter.py` | Gọi sync/async route handler |
| `_route_arguments()` | `daemon/httpadapter.py` | Quyết định route nhận `(headers, body)` hay `(headers, body, request)` |
| `Request` | `daemon/request.py` | Object biểu diễn HTTP request đã parse |
| `fetch_headers_body()` | `daemon/request.py` | Split raw HTTP text thành headers và body |
| `extract_request_line()` | `daemon/request.py` | Parse method, target, version |
| `prepare_headers()` | `daemon/request.py` | Parse HTTP headers |
| `prepare_query_params()` | `daemon/request.py` | Tách path và query string |
| `prepare_cookies()` | `daemon/request.py` | Parse `Cookie` header |
| `prepare()` | `daemon/request.py` | Pipeline parse hoàn chỉnh |
| `Response` | `daemon/response.py` | Object build HTTP response bytes |
| `_format()` | `daemon/response.py` | Build status line, headers, blank line, body |
| `build_response()` | `daemon/response.py` | Build static file response hoặc route response |
| `build_route_response()` | `daemon/response.py` | Convert route result thành HTTP response |
| `build_json_response()` | `daemon/response.py` | Build JSON response đơn giản |
| `_normalise_static_path()` | `daemon/response.py` | Map URL path sang file path an toàn |
| `build_content()` | `daemon/response.py` | Load static file bytes |
| `get_mime_type()` | `daemon/response.py` | Suy ra `Content-Type` từ file extension |

## 8. Common mistakes/misunderstandings

- Nghĩ TCP packet tương đương HTTP request. TCP chỉ là byte stream; server phải đọc theo HTTP framing.
- Nghĩ `Request.fetch_headers_body()` tự đọc body từ network. Không đúng: adapter đọc từ network, request parser chỉ split string đã có.
- Quên `Content-Length`, dẫn đến POST body bị thiếu hoặc server chờ sai.
- Nghĩ `Content-Type` quyết định server đọc bao nhiêu bytes. Không đúng: `Content-Length` quyết định độ dài; `Content-Type` quyết định cách hiểu body.
- Nghĩ cookies nằm trong body. Cookie nằm trong request header `Cookie`.
- Nhầm `Set-Cookie` với `Cookie`: `Set-Cookie` là response header từ server; `Cookie` là request header từ client.
- Nghĩ path gồm cả query string. Trong route matching của project, path là `/get-list`, query nằm riêng trong `query_params`.
- Nghĩ mọi `GET` đều là static file. Nếu route `GET` tồn tại, adapter gọi route; nếu không có route mới fallback sang static file.
- Nghĩ response là object Python gửi thẳng cho browser. Thực tế phải serialize thành bytes theo format HTTP/1.1.
- Nghĩ MIME type chỉ là phụ. Browser cần `Content-Type` để render/interpret response đúng.
- Bỏ qua `Connection: close`. Project hiện đóng mỗi TCP connection sau một response, không giữ persistent connection.
- Nghĩ `Request` parse JSON body. Source hiện không làm vậy; JSON parse nằm ở application code như `apps/sampleapp.py`.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] I can identify request line, headers, and body in a raw HTTP request.
- [ ] I can explain how Content-Length affects body parsing.
- [ ] I can explain where cookies appear in HTTP.
- [ ] I can explain how response headers and body are constructed.
- [ ] I can map HTTP theory to request.py, response.py, and httpadapter.py.
- [ ] Tôi phân biệt được TCP connection và HTTP message.
- [ ] Tôi biết `_read_http_message_async()` đọc headers trước rồi đọc body theo `Content-Length`.
- [ ] Tôi biết `Request.extract_request_line()` parse method/path/version.
- [ ] Tôi biết `Request.prepare_headers()` parse headers vào `CaseInsensitiveDict`.
- [ ] Tôi biết `Request.prepare_cookies()` parse header `Cookie`.
- [ ] Tôi biết route lookup dùng `(method, path)`, không dùng query string.
- [ ] Tôi biết `Response._format()` là nơi status line, response headers và body được ghép thành bytes.
- [ ] Tôi biết static file serving đi qua `_normalise_static_path()`, `build_content()`, `get_mime_type()`.
- [ ] Tôi biết JSON response đi qua `build_route_response()` hoặc `build_json_response()`.

## 10. Suggested test commands or observation commands if applicable

Chạy tracker để quan sát HTTP lifecycle:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Quan sát static file response headers:

```powershell
curl.exe -i http://127.0.0.1:2026/chat.html
```

Quan sát JSON response và `Set-Cookie`:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Quan sát cookie đi trong request header:

```powershell
curl.exe -i http://127.0.0.1:2026/me -H "Cookie: session_id=<value-from-login>"
```

Quan sát protected endpoint khi thiếu cookie:

```powershell
curl.exe -i http://127.0.0.1:2026/me
```

Quan sát static file MIME type:

```powershell
curl.exe -i http://127.0.0.1:2026/static/js/chat.js
curl.exe -i http://127.0.0.1:2026/css/chat.css
```

Kiểm tra Python syntax không đổi:

```powershell
python -m compileall daemon
```

Gợi ý quan sát bằng source:

```powershell
rg -n "readuntil|readexactly|Content-Length|prepare\\(|_format|build_route_response|build_content" daemon/request.py daemon/response.py daemon/httpadapter.py
```

## 11. Suggested commit message

Suggested commit message:

```text
docs: add stage 02 http request response explanation
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-02-http-request-response.md
git commit -m "docs: add stage 02 http request response explanation" -- docs/learning/stage-02-http-request-response.md
```
