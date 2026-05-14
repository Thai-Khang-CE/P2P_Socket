# Stage 06 - Non-blocking networking, concurrency và asyncio backend

## 1. Stage objective

Mục tiêu của stage này là trả lời rõ:

> What exactly makes this server non-blocking, and how can I prove it in demo?

Sau stage này, bạn cần hiểu:

- Blocking socket là gì.
- Vì sao `recv()` và `send()` có thể block.
- Vì sao một client chậm có thể làm server đứng nếu server chỉ có một luồng xử lý.
- Thread-per-client model giải quyết gì và đánh đổi gì.
- Callback/event-driven model và `selectors` module hoạt động ở mức ý tưởng.
- Coroutine model và `asyncio` event loop hoạt động ra sao.
- `StreamReader` và `StreamWriter` trong asyncio đại diện cho gì.
- Concurrency khác parallelism như thế nào.
- Những lỗi network phổ biến: partial read, partial write, disconnect, timeout, broken pipe.
- Trong project này, non-blocking nằm chủ yếu ở `daemon/backend.py` và `daemon/httpadapter.py`.

Kết luận ngắn của project:

```text
Backend HTTP hiện tại non-blocking theo hướng asyncio coroutine:
  daemon/backend.py
    mode_async = "coroutine"
    asyncio.run(async_server(...))
    asyncio.start_server(...)

  daemon/httpadapter.py
    handle_client_coroutine(...)
    await reader.readuntil(...)
    await reader.readexactly(...)
    writer.write(...)
    await writer.drain()
```

Proxy thì khác:

```text
daemon/proxy.py = blocking socket + thread-per-client
```

Nó có concurrency nhờ nhiều thread, nhưng không phải asyncio non-blocking server.

## 2. Theory needed before understanding this stage

### Blocking socket

Blocking socket là socket mà các lời gọi I/O có thể làm chương trình dừng lại tại dòng đó cho đến khi có kết quả.

Ví dụ:

```python
data = conn.recv(4096)
```

Nếu client chưa gửi data, thread đang chạy dòng này sẽ chờ. Trong lúc chờ, thread đó không làm việc khác.

Tương tự:

```python
conn.sendall(response)
```

có thể block nếu buffer gửi đầy hoặc client đọc chậm.

Blocking không phải luôn xấu. Nó đơn giản và dễ hiểu. Nhưng nếu server chỉ có một thread, một client chậm có thể làm server không nhận/xử lý client khác.

### Non-blocking socket

Non-blocking socket là socket mà operation như read/write không chờ vô hạn. Nếu chưa có data, nó trả ngay với trạng thái kiểu "not ready yet".

Ý tưởng:

```text
Không chờ một socket đến khi có data.
Hỏi hệ điều hành socket nào đang ready.
Xử lý socket ready.
Quay lại event loop.
```

Trong Python low-level, có thể dùng:

```python
sock.setblocking(False)
```

và bắt các trạng thái như `BlockingIOError`.

Trong code hiện tại, backend không gọi trực tiếp `setblocking(False)`. Thay vào đó, `asyncio.start_server()` và event loop quản lý cơ chế non-blocking bên dưới.

### Why `recv()` can block

`recv()` đọc bytes từ receive buffer của socket.

Nó có thể block khi:

- client đã connect nhưng chưa gửi bytes;
- client gửi headers rất chậm;
- client gửi headers xong nhưng body chưa đủ `Content-Length`;
- network delay;
- packet chưa tới;
- client treo nhưng chưa đóng connection.

Ví dụ HTTP POST:

```http
POST /login HTTP/1.1
Content-Length: 100

```

Nếu server đã đọc headers và thấy `Content-Length: 100`, nó phải đọc tiếp 100 bytes body. Nếu client mới gửi 20 bytes rồi dừng, blocking `recv()` có thể chờ tiếp.

### Why `send()` can block

`send()`/`sendall()` ghi bytes vào send buffer của OS.

Nó có thể block khi:

- client đọc response chậm;
- TCP flow control làm send buffer đầy;
- network nghẽn;
- response lớn;
- peer disconnect giữa chừng, dẫn đến `BrokenPipeError`, `ConnectionResetError`, hoặc `OSError`.

Trong project:

- sync path dùng `conn.sendall(response)`.
- async path dùng `writer.write(response)` rồi `await writer.drain()`.

`await writer.drain()` chính là điểm nhường control cho event loop nếu buffer cần thời gian flush.

### Why one blocking client can freeze a server

Nếu server single-thread blocking:

```text
while True:
    conn, addr = server.accept()
    handle_client(conn)
```

và `handle_client(conn)` gọi blocking `recv()`, thì flow có thể thành:

```text
Client A connects
server enters handle_client(A)
A sends request very slowly
server waits in recv()
Client B connects
server cannot accept/process B yet
```

Đây là vấn đề kinh điển của blocking server.

### Thread-per-client model

Thread-per-client giải quyết bằng cách mỗi client connection chạy trong một thread riêng:

```text
main thread:
  accept client
  start new thread for client
  immediately go back to accept

client thread:
  recv/read/process/send for that one client
```

Ưu điểm:

- Dễ hiểu.
- Blocking trong một thread không block toàn server.
- Phù hợp demo nhỏ.

Nhược điểm:

- Nhiều thread tốn memory/context switching.
- Khó scale với hàng chục nghìn connection.
- Cần lock nếu chia sẻ state.
- Race condition dễ xuất hiện.

Trong project:

- Backend fallback mode dùng thread-per-client khi `mode_async` không phải `"coroutine"` hoặc `"callback"`.
- Proxy luôn dùng thread-per-client.

### Callback/event-driven model

Callback/event-driven model dùng một event loop để theo dõi nhiều socket. Khi socket nào ready, event loop gọi callback tương ứng.

Ý tưởng:

```text
register socket A -> callback handle_A
register socket B -> callback handle_B

event loop:
  wait until some socket ready
  call matching callback
```

Callback style thường khó đọc hơn coroutine vì flow bị tách nhỏ thành nhiều callback.

Trong `daemon/backend.py` có function tên `handle_client_callback(...)`, nhưng source hiện tại không có event loop callback/selectors thật. Nó chỉ gọi:

```python
daemon.handle_client(conn, addr, routes)
```

ngay trong accept loop. Vì vậy tên `"callback"` trong source hiện tại nên hiểu là compatibility placeholder, không phải event-driven non-blocking implementation hoàn chỉnh.

Cần kiểm tra thêm: nếu assignment yêu cầu callback/selectors cụ thể, source hiện tại chưa thể hiện rõ selectors-based server.

### `selectors` module

`selectors` là module chuẩn của Python giúp viết event-driven I/O portable.

Ý tưởng cơ bản:

```python
selector = selectors.DefaultSelector()
selector.register(server_socket, selectors.EVENT_READ, accept_callback)
selector.register(client_socket, selectors.EVENT_READ, read_callback)

while True:
    events = selector.select(timeout=None)
    for key, mask in events:
        callback = key.data
        callback(key.fileobj, mask)
```

`selectors` hỏi OS:

```text
Socket nào ready để read/write?
```

Sau đó app xử lý socket ready mà không block trên socket chưa ready.

Trong project hiện tại:

- Không thấy import `selectors`.
- Không có selector register/select loop.
- Non-blocking backend chính dùng `asyncio`, không dùng selectors trực tiếp.

Lưu ý: bên dưới, `asyncio` trên nhiều nền tảng cũng dùng cơ chế selector/proactor của OS. Nhưng source project không tự viết selectors loop.

### Coroutine model

Coroutine model cho phép viết async code nhìn giống tuần tự:

```python
async def handle_client(reader, writer):
    data = await reader.readuntil(b"\r\n\r\n")
    writer.write(response)
    await writer.drain()
```

Khi coroutine gặp `await`, nó nhường control cho event loop. Event loop có thể chạy coroutine khác trong lúc chờ I/O.

Điểm quan trọng:

```text
await không có nghĩa là block toàn process.
await nghĩa là coroutine này tạm dừng, event loop đi làm việc khác.
```

Trong project, backend hiện tại dùng coroutine model.

### asyncio event loop

`asyncio` event loop là vòng lặp quản lý nhiều coroutine/task.

Nó làm các việc:

- accept connection mới;
- chờ socket readable/writable;
- resume coroutine khi I/O ready;
- chạy timer/timeout;
- quản lý task cancellation;
- schedule `asyncio.to_thread(...)` cho blocking code.

Trong project:

```python
asyncio.run(async_server(ip, port, routes))
```

tạo và chạy event loop cho backend.

`asyncio.start_server(...)` tạo async TCP server. Với mỗi client connection, nó gọi coroutine handler:

```python
handle_client_coroutine(reader, writer, routes)
```

### StreamReader and StreamWriter

`StreamReader` và `StreamWriter` là high-level asyncio wrapper quanh socket.

`StreamReader` dùng để đọc:

```python
await reader.readuntil(b"\r\n\r\n")
await reader.readexactly(content_length)
```

`StreamWriter` dùng để ghi:

```python
writer.write(response)
await writer.drain()
writer.close()
await writer.wait_closed()
```

Trong project:

- `daemon/backend.py` nhận `reader`, `writer` từ `asyncio.start_server`.
- `daemon/httpadapter.py` dùng chúng trong `handle_client_coroutine()`.

### Difference between concurrency and parallelism

Concurrency là nhiều công việc cùng tiến triển trong cùng một khoảng thời gian.

Parallelism là nhiều công việc chạy thật sự cùng lúc trên nhiều CPU/core.

Ví dụ:

```text
asyncio single-thread:
  concurrency: có
  parallelism CPU-bound: không nhất thiết

thread-per-client:
  concurrency: có
  parallelism: có thể có, nhưng Python GIL giới hạn CPU-bound Python code

multi-process:
  concurrency: có
  parallelism CPU-bound: có
```

Networking chủ yếu là I/O-bound, nên asyncio rất phù hợp: trong lúc một connection chờ network, event loop xử lý connection khác.

### Common problems: partial read

TCP là stream. Một `recv()` không đảm bảo nhận đủ HTTP request.

Vấn đề:

```text
Client gửi 1000 bytes.
Server recv(4096) có thể nhận 200 bytes trước.
Phần còn lại tới sau.
```

Project xử lý bằng cách:

- đọc headers đến `\r\n\r\n`;
- đọc body tiếp theo `Content-Length`.

Sync path:

```python
while b"\r\n\r\n" not in data:
    chunk = conn.recv(...)
...
while len(body) < content_length:
    chunk = conn.recv(...)
```

Async path:

```python
header_bytes = await reader.readuntil(b"\r\n\r\n")
body = await reader.readexactly(content_length)
```

### Common problems: partial write

Socket write có thể không gửi hết bytes ngay. `sendall()` cố gửi hết trong blocking mode. Trong asyncio, `writer.write()` buffer data, còn `await writer.drain()` chờ buffer flush khi cần.

Project:

```python
writer.write(response)
await writer.drain()
```

Đây là cách đúng hơn so với chỉ gọi `writer.write()` rồi đóng ngay.

### Common problems: disconnect

Client có thể đóng connection giữa chừng:

- trước khi gửi đủ request;
- trước khi đọc response;
- trong lúc server đang write.

Project bắt một số lỗi:

```python
except asyncio.IncompleteReadError
except (ConnectionError, OSError)
except OSError
```

### Common problems: timeout

Timeout bảo vệ server khỏi client quá chậm hoặc treo.

Project async backend:

```python
msg = await asyncio.wait_for(
    self._read_http_message_async(reader),
    timeout=self.READ_TIMEOUT,
)
```

Nếu quá `READ_TIMEOUT = 15` giây:

```python
response = resp.build_error(408, "408 Request Timeout")
```

Proxy cũng set timeout:

```python
conn.settimeout(BACKEND_TIMEOUT)
socket.create_connection(..., timeout=BACKEND_TIMEOUT)
```

### Common problems: broken pipe

Broken pipe xảy ra khi server ghi vào socket mà client đã đóng.

Trong Python thường biểu hiện dưới `BrokenPipeError` hoặc `OSError`.

Project xử lý tổng quát:

```python
except (ConnectionError, OSError):
    LOGGER.warning("Async client disconnected before response: %s", addr)
```

và sync:

```python
except OSError:
    LOGGER.warning("Client disconnected before response was sent: %s", addr)
```

## 3. Where this concept appears in the assignment requirement

Assignment AsynapRous yêu cầu tự xây HTTP server/networking mechanism thay vì dùng framework ngoài. Non-blocking/concurrency là phần quan trọng vì server phải xử lý nhiều client.

Mapping requirement sang project:

- `daemon/backend.py`: quyết định concurrency model của backend.
- `daemon/httpadapter.py`: xử lý từng connection theo sync hoặc asyncio path.
- `daemon/proxy.py`: proxy dùng thread-per-client, có timeout và forward request.
- `tools/stress_test.py`: có thể dùng để chứng minh nhiều request concurrent.

Source hiện tại có 3 ý tưởng mode:

```python
mode_async = "coroutine"
```

- `"coroutine"`: asyncio backend, đang là mặc định.
- `"callback"`: có nhánh tên callback, nhưng hiện không phải selectors/event-driven thật.
- else: thread-per-client fallback.

Cần kiểm tra thêm: nếu rubric yêu cầu selectors/callback cụ thể, source hiện tại chưa có implementation `selectors` module. Nhưng source có asyncio non-blocking backend, là cơ chế non-blocking rõ ràng.

## 4. Related files in the project

- `daemon/backend.py`: server lifecycle, `mode_async`, asyncio server, thread fallback.
- `daemon/httpadapter.py`: sync handler và async coroutine handler, partial read, timeout, write/drain.
- `daemon/proxy.py`: reverse proxy dùng blocking sockets + threads + timeout.
- `tools/stress_test.py`: async stress client để bắn nhiều concurrent requests.
- `start_backend.py`: entry point cho backend static server.
- `start_sampleapp.py`: entry point cho AsynapRous sample app/tracker.
- `start_proxy.py`: entry point cho threaded proxy.

## 5. Detailed source-code reading notes

### 5.1 `daemon/backend.py`: file quyết định backend concurrency

`daemon/backend.py` là nơi backend server được tạo và chạy.

Nó import cả:

```python
import asyncio
import socket
import threading
```

Điều này phản ánh project có nhiều model:

- asyncio coroutine;
- blocking socket;
- thread-per-client fallback.

Biến quan trọng:

```python
mode_async = "coroutine"
```

Vì giá trị mặc định là `"coroutine"`, backend hiện tại ưu tiên asyncio.

### 5.2 What `mode_async` means

Trong `run_backend()`:

```python
global mode_async
...
if mode_async == "coroutine":
    asyncio.run(async_server(ip, port, routes))
    return
```

Nếu `mode_async == "coroutine"`, server không đi vào loop `socket.accept()` thủ công. Nó chạy:

```text
asyncio.run(async_server(...))
```

Nếu không phải `"coroutine"`, code mới tạo blocking socket:

```python
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((ip, port))
server.listen(50)
```

Sau đó:

```python
conn, addr = server.accept()
```

Nếu `mode_async == "callback"`:

```python
handle_client_callback(...)
```

Ngược lại:

```python
threading.Thread(target=handle_client, ...)
```

Tóm tắt:

```text
mode_async == "coroutine"
  -> asyncio server

mode_async == "callback"
  -> function named callback, but still using blocking accept/handle path

other values
  -> thread-per-client
```

### 5.3 Coroutine/asyncio backend in `async_server()`

`async_server()`:

```python
server = await asyncio.start_server(
    lambda reader, writer: handle_client_coroutine(reader, writer, routes),
    ip,
    port,
    reuse_address=True,
)
```

`asyncio.start_server()`:

- creates listening server;
- accepts clients asynchronously;
- for each client, creates `StreamReader` and `StreamWriter`;
- calls the provided coroutine callback.

Then:

```python
async with server:
    await server.serve_forever()
```

`serve_forever()` keeps event loop accepting/serving connections.

Điểm non-blocking: khi một coroutine đang `await reader.readuntil(...)`, event loop có thể xử lý connection khác.

### 5.4 Coroutine connection entry: `handle_client_coroutine()` in backend

In `daemon/backend.py`:

```python
async def handle_client_coroutine(reader, writer, routes=None):
    addr = writer.get_extra_info("peername")
    daemon = HttpAdapter(None, None, None, addr, routes or {})
    await daemon.handle_client_coroutine(reader, writer)
```

Function này là bridge:

```text
asyncio server
  -> backend.handle_client_coroutine(reader, writer)
  -> HttpAdapter.handle_client_coroutine(reader, writer)
```

`backend.py` không parse HTTP. Nó chỉ tạo `HttpAdapter` và giao connection cho adapter.

### 5.5 `HttpAdapter.handle_client_coroutine()`: async request lifecycle

Trong `daemon/httpadapter.py`:

```python
async def handle_client_coroutine(self, reader, writer):
    addr = writer.get_extra_info("peername")
    req = Request()
    resp = Response()
```

Nó đọc request với timeout:

```python
msg = await asyncio.wait_for(
    self._read_http_message_async(reader),
    timeout=self.READ_TIMEOUT,
)
```

Sau đó parse:

```python
req.prepare(msg, self.routes)
req.connaddr = addr
```

Dispatch:

```python
response = await self._dispatch_route_async(req, resp)
```

Write:

```python
writer.write(response)
await writer.drain()
```

Close:

```python
writer.close()
await writer.wait_closed()
```

Đây là full async lifecycle của một HTTP client.

### 5.6 `_read_http_message_async()`: non-blocking read

Async read:

```python
header_bytes = await reader.readuntil(b"\r\n\r\n")
```

Điều này đọc đến hết headers. Nếu data chưa đủ, coroutine tạm dừng. Event loop có thể chạy client khác.

Sau đó:

```python
content_length = self._content_length_from_headers(header_text)
```

Nếu có body:

```python
body = await reader.readexactly(content_length)
```

Nếu client gửi thiếu body:

```python
except asyncio.IncompleteReadError as exc:
    raise ValueError("incomplete request body") from exc
```

So với blocking `recv()`, async read vẫn chờ I/O, nhưng không giữ toàn bộ server đứng.

### 5.7 `_dispatch_route_async()`: async dispatch and sync route compatibility

```python
result = await self._call_route_async(req)
return resp.build_response(req, envelop_content=result)
```

`_call_route_async()` hỗ trợ:

```python
if inspect.iscoroutinefunction(req.hook):
    return await req.hook(*args)

result = await asyncio.to_thread(req.hook, *args)
```

Điểm quan trọng: đa số route trong `apps/sampleapp.py` là function thường `def`, không phải `async def`. Nếu gọi trực tiếp trong event loop, route sync có thể block event loop. Project dùng `asyncio.to_thread(...)` để chạy sync route trong thread phụ.

Nghĩa là async backend vừa:

- xử lý socket bằng event loop;
- hỗ trợ route sync bằng thread offload.

### 5.8 Async write and partial write handling

Trong async path:

```python
writer.write(response)
await writer.drain()
```

`writer.write()` không nhất thiết gửi hết bytes ngay. Nó đưa bytes vào buffer.

`await writer.drain()` chờ buffer được flush nếu buffer đầy. Trong lúc chờ, event loop có thể xử lý connection khác.

Nếu client disconnect:

```python
except (ConnectionError, OSError):
    LOGGER.warning(...)
```

### 5.9 Timeout handling in async backend

`READ_TIMEOUT = 15`.

```python
msg = await asyncio.wait_for(
    self._read_http_message_async(reader),
    timeout=self.READ_TIMEOUT,
)
```

Nếu client không gửi request hoàn chỉnh trong 15 giây:

```python
except asyncio.TimeoutError:
    response = resp.build_error(408, "408 Request Timeout")
```

Đây là bằng chứng server không để một slow client giữ connection mãi.

### 5.10 Blocking sync path in `HttpAdapter`

Sync handler:

```python
def handle_client(self, conn, addr, routes):
    msg = self._read_http_message(conn)
    req.prepare(msg, self.routes)
    response = self._dispatch_route(req, resp)
    conn.sendall(response)
```

`_read_http_message(conn)` dùng blocking:

```python
chunk = conn.recv(self.BUFFER_SIZE)
```

Nếu path này chạy trong thread riêng, blocking chỉ block thread đó. Nếu chạy trực tiếp trong accept loop, một slow client có thể block server.

### 5.11 Thread-per-client backend fallback

Trong `run_backend()` fallback:

```python
client_thread = threading.Thread(
    target=handle_client,
    args=(ip, port, conn, addr, routes),
)
client_thread.daemon = True
client_thread.start()
```

Mỗi client có một thread. `handle_client()` tạo `HttpAdapter` và gọi sync handler:

```python
daemon.handle_client(conn, addr, routes)
```

Concurrency có được nhờ nhiều thread, không nhờ non-blocking socket.

### 5.12 Callback mode in source

Source có:

```python
if mode_async == "callback":
    handle_client_callback(server, ip, port, conn, addr, routes)
```

`handle_client_callback()`:

```python
daemon = HttpAdapter(ip, port, conn, addr, routes)
daemon.handle_client(conn, addr, routes)
```

Điều này vẫn gọi sync `handle_client()` trực tiếp. Nó không dùng selector, không đăng ký event callback, không tránh blocking read.

Vì vậy:

```text
Tên mode là callback
nhưng implementation hiện tại không phải callback/event-driven non-blocking server hoàn chỉnh.
```

Nếu demo non-blocking, nên demo `"coroutine"` mode hiện tại thay vì nói callback mode là non-blocking.

### 5.13 Proxy concurrency in `daemon/proxy.py`

Proxy dùng blocking socket + threads:

```python
conn, addr = proxy.accept()
client_thread = threading.Thread(
    target=handle_client,
    args=(ip, port, conn, addr, routes),
)
client_thread.daemon = True
client_thread.start()
```

Trong `handle_client()`:

```python
conn.settimeout(BACKEND_TIMEOUT)
request = _read_http_message(conn)
...
response = forward_request(...)
conn.sendall(response)
```

`forward_request()` cũng blocking:

```python
with socket.create_connection((host, port), timeout=BACKEND_TIMEOUT) as backend:
    backend.sendall(request)
    chunk = backend.recv(BUFFER_SIZE)
```

Vậy proxy có concurrency nhờ thread-per-client, không phải asyncio.

### 5.14 What parts are threading-based

Threading-based:

- backend fallback branch in `daemon/backend.py`;
- proxy server in `daemon/proxy.py`;
- route offload in `HttpAdapter._call_route_async()` via `asyncio.to_thread(...)`;
- static response build fallback in `_dispatch_route_async()` via `asyncio.to_thread(resp.build_response, req)`.

### 5.15 What parts are callback/selectors-based

In current source:

- No `selectors` import.
- No `selector.register(...)`.
- No `selector.select(...)`.

There is `handle_client_callback(...)`, but it is not true selectors/callback non-blocking I/O.

Therefore, for demo:

```text
Do not claim selectors are implemented unless you add/source-prove it.
Explain selectors as theory only.
```

### 5.16 What parts are coroutine/asyncio-based

Coroutine/asyncio-based:

- `daemon/backend.py:async_server()`
- `daemon/backend.py:handle_client_coroutine()`
- `daemon/httpadapter.py:handle_client_coroutine()`
- `daemon/httpadapter.py:_read_http_message_async()`
- `daemon/httpadapter.py:_dispatch_route_async()`
- `daemon/httpadapter.py:_call_route_async()`

Also outside this stage, `peer.py` uses asyncio heavily for direct P2P sockets.

### 5.17 How `HttpAdapter` is used in each mode

Coroutine mode:

```text
asyncio.start_server
  -> backend.handle_client_coroutine(reader, writer)
  -> HttpAdapter.handle_client_coroutine(reader, writer)
```

Thread mode:

```text
server.accept()
  -> start thread
  -> backend.handle_client(...)
  -> HttpAdapter.handle_client(conn, addr, routes)
```

Callback mode as currently written:

```text
server.accept()
  -> handle_client_callback(...)
  -> HttpAdapter.handle_client(conn, addr, routes)
```

So `HttpAdapter` has both:

- sync handler for socket object;
- async handler for stream reader/writer.

### 5.18 Why assignment gives points for non-blocking mechanism

Non-blocking/concurrent networking is important because a server must handle many clients. If a single slow client can freeze the server, the server is not robust.

A good demo should show:

```text
Client A is slow or waiting.
Client B still gets response.
```

Or:

```text
Many concurrent clients receive successful responses.
```

This proves the server is not single-client blocking.

## 6. Execution/data flow explanation

### 6.1 Async backend startup flow

```text
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026

start_sampleapp.py
  -> create_sampleapp(...)
  -> app.run()
  -> create_backend(ip, port, routes)
  -> run_backend(...)
  -> mode_async == "coroutine"
  -> asyncio.run(async_server(...))
  -> asyncio.start_server(...)
```

### 6.2 Async request handling flow

```text
Client connects
  -> asyncio accepts connection
  -> creates StreamReader/StreamWriter
  -> handle_client_coroutine(reader, writer)
  -> HttpAdapter.handle_client_coroutine(reader, writer)
  -> await read headers/body
  -> parse Request
  -> dispatch route/static
  -> write response
  -> await drain
  -> close writer
```

### 6.3 What happens when one client is slow

If client A sends headers slowly:

```text
Client A coroutine:
  await reader.readuntil(b"\r\n\r\n")
  suspended until enough data arrives
```

Event loop can still serve client B:

```text
Client B connects
  -> another coroutine runs
  -> B can get response
```

This is the core non-blocking behavior.

### 6.4 Threaded proxy flow

```text
Proxy accepts client A
  -> thread A handles blocking reads/forwarding

Proxy accepts client B
  -> thread B handles blocking reads/forwarding
```

Slow A blocks thread A, but not thread B or accept loop.

## 7. Important functions/classes and their role

| Function/class/constant | File | Role |
|---|---|---|
| `mode_async` | `daemon/backend.py` | Selects backend concurrency mode; default is `"coroutine"` |
| `run_backend()` | `daemon/backend.py` | Chooses asyncio vs callback/thread fallback |
| `async_server()` | `daemon/backend.py` | Starts asyncio server with `asyncio.start_server` |
| `handle_client_coroutine()` | `daemon/backend.py` | Bridges asyncio connection to `HttpAdapter` |
| `handle_client()` | `daemon/backend.py` | Thread fallback entry for one blocking client |
| `handle_client_callback()` | `daemon/backend.py` | Callback-named compatibility path, currently sync handling |
| `HttpAdapter.handle_client_coroutine()` | `daemon/httpadapter.py` | Async HTTP lifecycle for one connection |
| `HttpAdapter._read_http_message_async()` | `daemon/httpadapter.py` | Non-blocking HTTP header/body read |
| `HttpAdapter._dispatch_route_async()` | `daemon/httpadapter.py` | Async route/static dispatch |
| `HttpAdapter._call_route_async()` | `daemon/httpadapter.py` | Calls async route or offloads sync route to thread |
| `HttpAdapter.handle_client()` | `daemon/httpadapter.py` | Blocking socket HTTP lifecycle |
| `HttpAdapter._read_http_message()` | `daemon/httpadapter.py` | Blocking HTTP header/body read |
| `run_proxy()` | `daemon/proxy.py` | Thread-per-client proxy accept loop |
| `forward_request()` | `daemon/proxy.py` | Blocking upstream backend request with timeout |
| `BACKEND_TIMEOUT` | `daemon/proxy.py` | Timeout for proxy client/backend operations |
| `READ_TIMEOUT` | `daemon/httpadapter.py` | Timeout for async HTTP request read |

## 8. Common mistakes/misunderstandings

- Nghĩ `await` là block toàn server. Không đúng: `await` suspend coroutine, event loop chạy việc khác.
- Nghĩ cứ có thread là non-blocking. Thread-per-client là concurrent model, nhưng từng socket operation vẫn blocking trong thread đó.
- Nghĩ callback mode trong source là selectors. Source hiện tại không dùng `selectors`.
- Nghĩ một lần `recv()` đọc đủ request. TCP là stream; cần handle partial read.
- Nghĩ `writer.write()` gửi xong ngay. Cần `await writer.drain()`.
- Nghĩ proxy cũng asyncio. Proxy hiện tại là blocking socket + thread.
- Nghĩ concurrency và parallelism giống nhau. Asyncio concurrent, không nhất thiết parallel CPU-bound.
- Nghĩ timeout chỉ là tiện ích phụ. Timeout bảo vệ server khỏi slow/stuck clients.
- Nghĩ broken pipe là lỗi logic route. Thường là client đã đóng connection khi server write.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] I can explain blocking socket behavior.
- [ ] I can explain thread-per-client.
- [ ] I can explain selectors at a high level.
- [ ] I can explain asyncio event loop.
- [ ] I know where non-blocking should be implemented in this project.
- [ ] I know what tests can prove concurrency.
- [ ] Tôi biết `mode_async = "coroutine"` làm backend dùng asyncio.
- [ ] Tôi biết `asyncio.start_server()` tạo `StreamReader`/`StreamWriter`.
- [ ] Tôi biết `await reader.readuntil(...)` không freeze toàn server.
- [ ] Tôi biết sync route handlers được chạy bằng `asyncio.to_thread(...)`.
- [ ] Tôi biết proxy dùng thread, không dùng asyncio.
- [ ] Tôi biết callback/selectors chưa được implement rõ trong source hiện tại.

## 10. Suggested test commands or observation commands if applicable

Chạy tracker/backend:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

Chạy stress test nhiều request concurrent:

```powershell
python tools/stress_test.py --url http://127.0.0.1:2026/ --clients 50 --requests 200
```

Cần kiểm tra thêm: tham số thật của `tools/stress_test.py` nên xem bằng:

```powershell
python tools/stress_test.py --help
```

Quan sát code asyncio backend:

```powershell
rg -n "mode_async|asyncio.run|asyncio.start_server|serve_forever|handle_client_coroutine" daemon/backend.py daemon/httpadapter.py
```

Quan sát blocking path:

```powershell
rg -n "recv|sendall|threading.Thread|handle_client\\(" daemon/backend.py daemon/httpadapter.py daemon/proxy.py
```

Quan sát timeout/disconnect handling:

```powershell
rg -n "wait_for|Timeout|IncompleteRead|OSError|drain|wait_closed" daemon/httpadapter.py daemon/proxy.py
```

Manual concurrency observation:

1. Start server.
2. Run stress test with many concurrent clients.
3. Open browser/curl during stress test.
4. If browser/curl still gets response, server is handling concurrent clients.

Slow-client style test idea:

```text
Open one client that connects but sends request very slowly.
While it is connected, send normal curl request from another terminal.
If normal request still succeeds, server is not frozen by slow client.
```

You can explain this demo even if you do not build a special slow-client script.

## 11. Suggested commit message

Suggested commit message:

```text
docs: add stage 06 non blocking networking explanation
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-06-non-blocking-networking.md
git commit -m "docs: add stage 06 non blocking networking explanation" -- docs/learning/stage-06-non-blocking-networking.md
```
