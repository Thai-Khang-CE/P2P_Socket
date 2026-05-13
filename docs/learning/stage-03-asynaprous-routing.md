# Stage 03 - AsynapRous routing: tiny Flask without Flask

## 1. Stage objective

Mục tiêu của stage này là hiểu vì sao project có thể hoạt động giống một web framework nhỏ kiểu Flask nhưng không dùng Flask.

Câu hỏi cần trả lời được:

> How can this project behave like a tiny Flask without using Flask?

Ý chính:

- `daemon/asynaprous.py` cung cấp object `AsynapRous`, đóng vai trò mini-framework.
- `@app.route(...)` là decorator để đăng ký route.
- Route được lưu trong dictionary `app.routes`.
- Key của route là `(HTTP method, path)`, ví dụ `("POST", "/login")`.
- Value của route là Python function xử lý request, ví dụ `login`.
- `daemon/httpadapter.py` parse request xong sẽ tìm `req.hook`, rồi gọi handler đó.
- `apps/sampleapp.py` là application code: nơi người viết app định nghĩa API thật.
- `start_sampleapp.py` là entry point: parse IP/port rồi chạy app.

Sau stage này, bạn nên thấy rõ pipeline:

```text
@app.route("/login", methods=["POST"])
  -> app.routes[("POST", "/login")] = login

Browser POST /login
  -> Request.prepare()
  -> req.hook = routes.get(("POST", "/login"))
  -> HttpAdapter calls login(headers, body, request)
  -> Response builds HTTP response
```

## 2. Theory needed before understanding this stage

### What a web framework router is

Router là phần của web framework quyết định request nào sẽ đi vào function nào.

Một HTTP request có ít nhất:

```text
method + path
```

Ví dụ:

```http
POST /login HTTP/1.1
```

Router sẽ hỏi:

```text
Có handler nào cho ("POST", "/login") không?
```

Nếu có, gọi handler. Nếu không, trả `404 Not Found` hoặc fallback sang static file tùy framework.

Trong Flask thật, bạn viết:

```python
@app.route("/login", methods=["POST"])
def login():
    ...
```

Trong project này, cú pháp gần giống:

```python
@app.route("/login", methods=["POST"])
def login(headers, body, request):
    ...
```

Khác biệt là AsynapRous tự viết bằng standard library, đơn giản hơn Flask rất nhiều.

### What RESTful routing means

RESTful routing là cách thiết kế API quanh resource và HTTP methods.

Ví dụ cùng một path có thể có ý nghĩa khác nhau theo method:

```text
GET /get-list       -> đọc danh sách peer
POST /submit-info   -> đăng ký/update peer info
POST /heartbeat     -> báo peer còn sống
POST /leave         -> peer rời tracker
DELETE /leave       -> cũng biểu diễn hành động leave/remove
```

Trong RESTful style, path thường nói đến resource/action, method nói thao tác.

Project này không phải REST framework đầy đủ, nhưng có router theo method + path, đủ để viết REST-like API.

### What route decorators do

Decorator trong Python là function nhận một function khác và trả về function.

Ví dụ:

```python
@app.route("/hello", methods=["POST"])
def hello(headers, body):
    ...
```

tương đương gần như:

```python
def hello(headers, body):
    ...

hello = app.route("/hello", methods=["POST"])(hello)
```

Trong framework web, decorator thường có nhiệm vụ phụ quan trọng: đăng ký function vào route table.

Trong project:

```python
self.routes[(method.upper(), path)] = func
```

Đó là bản chất của `@app.route(...)`.

### What HTTP methods GET, POST, PUT, DELETE mean

Trong project này:

- `GET`: lấy dữ liệu hoặc static file. Ví dụ `/me`, `/get-list`, `/tracker-state`, `/chat.html`.
- `POST`: gửi body để thực hiện hành động. Ví dụ `/login`, `/submit-info`, `/heartbeat`.
- `PUT`: được `HttpAdapter` support, thường dùng cho update/replace resource. Source hiện tại ít dùng cho tracker chính.
- `DELETE`: biểu diễn xóa/rời khỏi resource. Ví dụ `/leave` support cả `POST` và `DELETE`.

`HttpAdapter.SUPPORTED_METHODS` chỉ chấp nhận:

```python
{"GET", "POST", "PUT", "DELETE"}
```

Method ngoài tập này sẽ bị trả `405 Method Not Allowed`.

### Difference between framework code and application code

Framework code là phần tái sử dụng để nhiều app có thể chạy:

- server lifecycle
- request parsing
- route registration
- route dispatch
- response formatting

Application code là logic nghiệp vụ cụ thể:

- login user nào
- session lưu thế nào
- peer registry lưu gì
- endpoint nào trả dữ liệu gì

Trong project:

```text
Framework code:
  daemon/asynaprous.py
  daemon/httpadapter.py
  daemon/request.py
  daemon/response.py
  daemon/backend.py

Application code:
  apps/sampleapp.py

Entry point:
  start_sampleapp.py
```

Nếu ví Flask:

```text
Flask framework     -> daemon/
Your Flask app      -> apps/sampleapp.py
flask run / script  -> start_sampleapp.py
```

## 3. Where this concept appears in the assignment requirement

Assignment yêu cầu không dùng external web framework như Flask, FastAPI, Django, aiohttp. Vì vậy project phải tự làm một phần nhỏ mà framework thường làm sẵn:

- route decorator
- route table
- request dispatch
- route handler call
- response build

`AsynapRous` chính là câu trả lời của project cho phần này. Nó không cố clone Flask đầy đủ. Nó chỉ cung cấp vừa đủ để:

- định nghĩa route bằng decorator;
- lưu route handlers;
- chạy backend server;
- để `HttpAdapter` gọi đúng handler khi request đến.

Mapping sang requirement:

- "RESTful TCP WebApp" -> route theo method + path.
- "No Flask/FastAPI/Django" -> tự viết `AsynapRous`.
- "User-defined APIs" -> viết trong `apps/sampleapp.py` bằng `@app.route`.
- "Chat APIs / tracker APIs" -> `/login`, `/submit-info`, `/get-list`, `/heartbeat`, `/leave`, `/tracker-state`.

Cần kiểm tra thêm: source hiện tại có cả deprecated server-side chat endpoints như `/send-peer`, `/broadcast-peer`, nhưng chúng trả `410 Gone`. Vì vậy "chat APIs" trong kiến trúc hiện tại chủ yếu là tracker/discovery API; direct chat thật nằm ở `peer.py`.

## 4. Related files in the project

- `daemon/asynaprous.py`: mini-framework object, route decorator, app runner.
- `daemon/httpadapter.py`: dispatch request tới route handler.
- `apps/sampleapp.py`: user-defined APIs bằng `@app.route(...)`.
- `start_sampleapp.py`: entry point để chạy sample app.
- `daemon/request.py`: parse HTTP request và gắn `req.hook` từ route table.
- `daemon/response.py`: convert route return value thành HTTP response.
- `daemon/backend.py`: chạy server và truyền `routes` vào `HttpAdapter`.

## 5. Detailed source-code reading notes

### 5.1 `start_sampleapp.py`: entry point của application

File `start_sampleapp.py` không định nghĩa route. Nó chỉ:

1. Parse command-line arguments.
2. Lấy `ip` và `port`.
3. Gọi `create_sampleapp(ip, port)`.

Code chính:

```python
from apps import create_sampleapp

parser.add_argument('--server-ip', default='0.0.0.0')
parser.add_argument('--server-port', type=int, default=PORT)

create_sampleapp(ip, port)
```

Nghĩa là:

```text
start_sampleapp.py = launcher
apps/sampleapp.py = app definition
daemon/ = framework/server implementation
```

### 5.2 `apps/sampleapp.py`: tạo app object

Ở đầu `apps/sampleapp.py`:

```python
from daemon import AsynapRous

app = AsynapRous()
```

`app` là object trung tâm giống `Flask(__name__)` trong Flask. Các route phía dưới đều gắn vào object này.

Ví dụ:

```python
@app.route("/login", methods=["POST"])
def login(headers, body, request):
    ...
```

Khi Python import file này, decorator chạy ngay. Vì vậy route table được populate trong lúc module load, trước khi server nhận request.

### 5.3 `create_sampleapp(ip, port)`: nối app với backend

Cuối `apps/sampleapp.py`:

```python
def create_sampleapp(ip, port):
    app.prepare_address(ip, port)
    app.run()
```

`prepare_address()` chỉ lưu IP/port vào object.

`run()` gọi backend server, truyền theo route table.

Flow:

```text
start_sampleapp.py
  -> apps.create_sampleapp(ip, port)
  -> app.prepare_address(ip, port)
  -> app.run()
  -> create_backend(ip, port, app.routes)
```

### 5.4 `AsynapRous.__init__()`: route table bắt đầu rỗng

Trong `daemon/asynaprous.py`:

```python
def __init__(self):
    self.routes = {}
    self.ip = None
    self.port = None
```

`routes` là dictionary quan trọng nhất của mini-framework.

Shape của nó:

```python
{
    ("POST", "/login"): login,
    ("GET", "/me"): me,
    ("POST", "/submit-info"): submit_info,
}
```

Đây là "routing table" của app.

### 5.5 `AsynapRous.route(path, methods)`: decorator factory

`route()` không trực tiếp nhận handler. Nó nhận config route trước:

```python
def route(self, path, methods=['GET']):
```

Ví dụ:

```python
@app.route("/login", methods=["POST"])
def login(...):
    ...
```

Khi Python đọc dòng decorator, nó gọi:

```python
app.route("/login", methods=["POST"])
```

Kết quả trả về là function `decorator(func)`.

Vì vậy `route()` là decorator factory: function tạo ra decorator.

### 5.6 `decorator(func)`: nơi route được đăng ký thật

Bên trong `route()`:

```python
def decorator(func):
    for method in methods:
        self.routes[(method.upper(), path)] = func
```

Đây là dòng lõi của router.

Ví dụ với:

```python
@app.route("/leave", methods=["POST", "DELETE"])
def leave(...):
    ...
```

Route table sẽ có 2 key trỏ tới cùng một function:

```python
app.routes[("POST", "/leave")] = leave
app.routes[("DELETE", "/leave")] = leave
```

Vì vậy cùng một path `/leave` có thể xử lý nhiều HTTP methods.

### 5.7 Route metadata trên function

Sau khi lưu vào route table, code gắn thêm metadata:

```python
func._route_path = path
func._route_methods = methods
```

Metadata này không phải phần bắt buộc để dispatch trong source hiện tại. Dispatch dùng `self.routes`, không dùng `_route_path`. Nhưng metadata có thể hữu ích cho debug, docs hoặc introspection sau này.

### 5.8 Wrapper sync/async trong decorator

`route()` tạo hai wrapper:

```python
def sync_wrapper(*args, **kwargs):
    print(...)
    result = func(*args, **kwargs)
    return result

async def async_wrapper(*args, **kwargs):
    print(...)
    result = await func(*args, **kwargs)
    return result
```

Nếu handler là coroutine function:

```python
if inspect.iscoroutinefunction(func):
   return async_wrapper
else:
   return sync_wrapper
```

Điểm tinh tế trong source hiện tại: route table lưu `func` gốc trước khi wrapper được return:

```python
self.routes[(method.upper(), path)] = func
```

Vì vậy `HttpAdapter` thường dispatch đến function gốc trong route table, không phải wrapper. Wrapper là tên được bind lại trong module sau decorator, nhưng route table đã giữ function gốc.

Hệ quả:

- Route vẫn chạy đúng.
- `HttpAdapter._call_route_async()` tự xử lý sync/async function.
- Các dòng print trong wrapper có thể không xuất hiện như bạn tưởng.

Cần kiểm tra thêm: nếu mục tiêu của framework là wrapper luôn chạy khi route dispatch, route table nên lưu wrapper thay vì `func`; source hiện tại không làm vậy.

### 5.9 `AsynapRous.run()`: chuyển routes sang backend

Trong `run()`:

```python
if not self.ip or not self.port:
    print("Rous app need to preapre address" ...)

create_backend(self.ip, self.port, self.routes)
```

Nghĩa là `AsynapRous` không tự accept TCP connection. Nó chỉ giữ route table rồi giao cho backend.

Ranh giới:

```text
AsynapRous:
  biết routes
  biết ip/port
  gọi create_backend

Backend/HttpAdapter:
  accept/read HTTP request
  parse request
  lookup route
  call handler
  send response
```

### 5.10 `Request.prepare()` gắn `req.hook`

Mặc dù Stage 03 tập trung vào router, điểm nối nằm ở `Request.prepare()` trong `daemon/request.py`:

```python
self.hook = routes.get((self.method, self.path))
```

`routes` chính là dictionary từ `AsynapRous`.

Nếu browser gửi:

```http
POST /login HTTP/1.1
```

và route table có:

```python
("POST", "/login"): login
```

thì:

```python
req.hook = login
```

Nếu không có key tương ứng:

```python
req.hook = None
```

### 5.11 `HttpAdapter._dispatch_route_async()`: quyết định gọi route hay static

Trong `daemon/httpadapter.py`:

```python
async def _dispatch_route_async(self, req, resp):
    if req.method not in self.SUPPORTED_METHODS:
        return resp.build_error(405, "405 Method Not Allowed")

    if not req.hook:
        if req.method == "GET":
            return await asyncio.to_thread(resp.build_response, req)
        return resp.build_notfound()

    result = await self._call_route_async(req)
    return resp.build_response(req, envelop_content=result)
```

Logic:

1. Method không support -> `405`.
2. Không có route, nhưng là `GET` -> thử serve static file.
3. Không có route, không phải `GET` -> `404`.
4. Có route -> gọi handler.
5. Kết quả handler -> build response.

Vì vậy route table không chỉ là nơi lưu function; nó quyết định request đi vào application code hay static file fallback.

### 5.12 `_call_route_async()`: gọi handler sync hoặc async

Code:

```python
args = self._route_arguments(req)
if inspect.iscoroutinefunction(req.hook):
    return await req.hook(*args)

result = await asyncio.to_thread(req.hook, *args)
if inspect.isawaitable(result):
    return await result
return result
```

Ý nghĩa:

- Nếu route handler là `async def`, await trực tiếp.
- Nếu route handler là function thường, chạy trong thread bằng `asyncio.to_thread(...)`.
- Nếu function thường trả về awaitable, await tiếp.

Source hiện tại có cả hai kiểu:

```python
def login(headers, body, request):
    ...

async def async_hello(headers, body, request):
    await asyncio.sleep(0.01)
    ...
```

### 5.13 `_route_arguments()`: handler nhận tham số gì

Không phải route nào trong project cũng nhận cùng số tham số.

Ví dụ:

```python
def hello(headers, body):
    ...
```

và:

```python
def login(headers, body, request):
    ...
```

`_route_arguments()` inspect chữ ký function:

```python
signature = inspect.signature(req.hook)
...
if len(positional) >= 3:
    return req.headers, req.body, req
return req.headers, req.body
```

Nghĩa là:

- Handler 2 tham số nhận `(headers, body)`.
- Handler 3 tham số nhận `(headers, body, request)`.

`request` cần thiết khi handler muốn đọc:

- `request.cookies`
- `request.query_params`
- `request.connaddr`
- `request.method`

### 5.14 `apps/sampleapp.py`: user-defined APIs

`apps/sampleapp.py` chứng minh cách người dùng framework định nghĩa API:

Authentication:

```python
@app.route("/login", methods=["POST"])
def login(headers, body, request):
    ...
```

Protected identity:

```python
@app.route("/me", methods=["GET"])
def me(headers, body, request):
    ...
```

Peer registration:

```python
@app.route("/submit-info", methods=["POST"])
def submit_info(headers, body, request):
    ...
```

Peer discovery:

```python
@app.route("/get-list", methods=["GET"])
def get_list(headers, body, request):
    ...
```

Heartbeat:

```python
@app.route("/heartbeat", methods=["POST"])
def heartbeat(headers, body, request):
    ...
```

Leave:

```python
@app.route("/leave", methods=["POST", "DELETE"])
def leave(headers, body, request):
    ...
```

Đây là application code, không phải framework code. Nếu thêm API mới sau này, vị trí tự nhiên là `apps/sampleapp.py` hoặc một app module tương tự.

### 5.15 Return value của route handler

Route trong `apps/sampleapp.py` thường trả về helper:

```python
return json_response(...)
```

`json_response()` trả dictionary envelope:

```python
{
    "status": status,
    "headers": headers or {},
    "body": body,
    "content_type": "application/json; charset=utf-8",
}
```

`HttpAdapter` không tự hiểu nghiệp vụ bên trong body. Nó chỉ đưa return value sang:

```python
resp.build_response(req, envelop_content=result)
```

Rồi `Response` build HTTP response thật.

### 5.16 How this will later support chat APIs

Trong kiến trúc hiện tại, tracker không forward chat messages. Nhưng routing mechanism vẫn là nền cho các API tracker/chat-related:

- `/login`: peer hoặc browser authenticate.
- `/submit-info`: peer publish endpoint.
- `/get-list`: peer discovery.
- `/heartbeat`: peer presence.
- `/leave`: peer offline.
- `/tracker-state`: dashboard state.

Nếu assignment yêu cầu thêm API mới, pattern sẽ là:

```python
@app.route("/new-api", methods=["POST"])
def new_api(headers, body, request):
    data = parse_body(body, headers)
    ...
    return json_response({...})
```

Sau đó AsynapRous tự thêm route vào `app.routes`, backend không cần biết trước API đó là gì.

Nhưng với source hiện tại, direct chat message vẫn nên nằm ở `peer.py` TCP socket, không phải thêm route để tracker relay chat, trừ khi requirement mới yêu cầu đổi kiến trúc.

## 6. Execution/data flow explanation

### 6.1 Route registration happens at import time

Khi Python import `apps/sampleapp.py`:

```text
app = AsynapRous()

@app.route("/login", methods=["POST"])
def login(...):
    ...
```

Decorator chạy ngay:

```text
app.route("/login", ["POST"])
  -> decorator(login)
  -> app.routes[("POST", "/login")] = login
```

Sau khi import xong, `app.routes` đã chứa các API.

### 6.2 Server startup flow

```text
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026

start_sampleapp.py
  -> create_sampleapp(ip, port)
  -> app.prepare_address(ip, port)
  -> app.run()
  -> create_backend(ip, port, app.routes)
  -> backend starts listening
```

`AsynapRous` không xử lý socket trực tiếp. Nó truyền route table xuống backend.

### 6.3 Request dispatch flow

Ví dụ browser/peer gửi:

```http
POST /login HTTP/1.1
Content-Type: application/json
Content-Length: ...

{"username":"alice","password":"wonderland"}
```

Flow:

```text
HttpAdapter reads request bytes
  -> Request.prepare(msg, routes)
  -> req.method = "POST"
  -> req.path = "/login"
  -> req.hook = routes.get(("POST", "/login"))
  -> req.hook is login
  -> _dispatch_route_async()
  -> _call_route_async()
  -> login(headers, body, request)
  -> json_response(...)
  -> Response.build_response(...)
  -> write HTTP response bytes
```

### 6.4 Static fallback flow

Nếu browser gửi:

```http
GET /chat.html HTTP/1.1
```

và không có route `("GET", "/chat.html")`, adapter xử lý:

```text
no req.hook
method is GET
  -> Response.build_response(req)
  -> static file lookup
```

Vì vậy cùng server vừa phục vụ API route, vừa phục vụ static files.

### 6.5 Missing route flow

Nếu client gửi:

```http
POST /unknown HTTP/1.1
```

và không có route:

```text
no req.hook
method is POST
  -> 404 Not Found
```

`POST` không fallback sang static file.

## 7. Important functions/classes and their role

| Function/class | File | Role |
|---|---|---|
| `AsynapRous` | `daemon/asynaprous.py` | Mini-framework object, giữ route table và server address |
| `AsynapRous.__init__()` | `daemon/asynaprous.py` | Khởi tạo `routes`, `ip`, `port` |
| `AsynapRous.prepare_address()` | `daemon/asynaprous.py` | Lưu IP/port để chạy backend |
| `AsynapRous.route()` | `daemon/asynaprous.py` | Decorator factory để đăng ký route |
| `decorator(func)` | `daemon/asynaprous.py` | Lưu `(method, path) -> func` vào `self.routes` |
| `AsynapRous.run()` | `daemon/asynaprous.py` | Gọi `create_backend(ip, port, routes)` |
| `HttpAdapter._dispatch_route_async()` | `daemon/httpadapter.py` | Chọn route handler, static file, hoặc error |
| `HttpAdapter._call_route_async()` | `daemon/httpadapter.py` | Gọi sync/async route handler |
| `HttpAdapter._route_arguments()` | `daemon/httpadapter.py` | Quyết định truyền `(headers, body)` hay `(headers, body, request)` |
| `create_sampleapp()` | `apps/sampleapp.py` | Nối app object với IP/port và chạy app |
| `json_response()` | `apps/sampleapp.py` | Chuẩn hóa return value của route thành response envelope |
| `parse_body()` | `apps/sampleapp.py` | Application-level body parser cho JSON/form |
| `login()` | `apps/sampleapp.py` | Ví dụ POST API có body và Set-Cookie |
| `me()` | `apps/sampleapp.py` | Ví dụ GET API cần cookie session |
| `submit_info()` | `apps/sampleapp.py` | Ví dụ POST API cho peer registration |
| `get_list()` | `apps/sampleapp.py` | Ví dụ GET API dùng query params |
| `leave()` | `apps/sampleapp.py` | Ví dụ route nhiều methods: POST và DELETE |
| `async_hello()` | `apps/sampleapp.py` | Ví dụ async route handler |
| `start_sampleapp.py` main block | `start_sampleapp.py` | CLI launcher cho sample app |

## 8. Common mistakes/misunderstandings

- Nghĩ `@app.route` chạy khi request đến. Không đúng: decorator chạy lúc module được import, trước khi server start.
- Nghĩ route table key chỉ là path. Không đúng: key là `(method, path)`, nên `GET /login` khác `POST /login`.
- Nghĩ `AsynapRous` tự đọc socket. Không đúng: nó gọi `create_backend`; `HttpAdapter` mới xử lý request/response.
- Nghĩ `apps/sampleapp.py` là framework. Không đúng: nó là application code dùng framework.
- Nghĩ thêm API phải sửa `HttpAdapter`. Thường không cần; chỉ cần thêm route handler trong app code, trừ khi cần đổi cơ chế dispatch.
- Nghĩ route decorator parse request body. Không đúng: decorator chỉ register handler.
- Nghĩ route handler luôn nhận object `request`. Không đúng: `_route_arguments()` truyền 2 hoặc 3 args tùy signature.
- Nghĩ wrapper trong `AsynapRous.route()` chắc chắn là function được dispatch. Source hiện tại lưu function gốc trong route table trước khi return wrapper.
- Nghĩ `GET` không có route luôn là 404. Trong project, `GET` không có route sẽ thử static file trước.
- Nghĩ external frameworks bị cấm nghĩa là không được có framework concept. Thực tế project tự viết một framework rất nhỏ để học nguyên lý.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] I can explain what @app.route does.
- [ ] I can explain how method + path maps to a handler.
- [ ] I know where user app routes should be added.
- [ ] I know how AsynapRous connects to backend server logic.
- [ ] I understand why external frameworks are forbidden.
- [ ] Tôi biết `app.routes` là dictionary có key `(method, path)`.
- [ ] Tôi biết decorator chạy lúc import module, không phải lúc request đến.
- [ ] Tôi biết `Request.prepare()` dùng route table để set `req.hook`.
- [ ] Tôi biết `HttpAdapter._dispatch_route_async()` gọi route handler nếu `req.hook` tồn tại.
- [ ] Tôi phân biệt được framework code trong `daemon/` và application code trong `apps/sampleapp.py`.
- [ ] Tôi biết route handler trả Python object/envelope, rồi `Response` mới biến nó thành HTTP response.

## 10. Suggested test commands or observation commands if applicable

Xem các route được định nghĩa trong sample app:

```powershell
rg -n "@app\.route" apps/sampleapp.py
```

Xem core router:

```powershell
rg -n "class AsynapRous|def route|self\.routes|create_backend" daemon/asynaprous.py
```

Xem dispatch trong adapter:

```powershell
rg -n "_dispatch_route_async|_call_route_async|_route_arguments|req\.hook" daemon/httpadapter.py daemon/request.py
```

Chạy tracker:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Gọi route API:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/login -H "Content-Type: application/json" -d "{\"username\":\"alice\",\"password\":\"wonderland\"}"
```

Gọi static file fallback:

```powershell
curl.exe -i http://127.0.0.1:2026/chat.html
```

Gọi missing POST route để thấy `404`:

```powershell
curl.exe -i -X POST http://127.0.0.1:2026/not-a-route
```

Gọi unsupported method để thấy `405` nếu client/tool cho phép:

```powershell
curl.exe -i -X PATCH http://127.0.0.1:2026/login
```

Kiểm tra syntax không đổi:

```powershell
python -m compileall daemon apps start_sampleapp.py
```

## 11. Suggested commit message

Suggested commit message:

```text
docs: add stage 03 asynaprous routing explanation
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-03-asynaprous-routing.md
git commit -m "docs: add stage 03 asynaprous routing explanation" -- docs/learning/stage-03-asynaprous-routing.md
```
