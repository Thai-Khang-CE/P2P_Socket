# Stage 04 - Proxy server và reverse proxy

## 1. Stage objective

Mục tiêu của stage này là hiểu proxy server trong project:

> How does a browser request reach the correct backend through this proxy?

Sau stage này, bạn cần nắm được:

- Proxy là gì và reverse proxy khác gì forward proxy.
- Vì sao đặt reverse proxy trước backend servers.
- `Host` header được dùng để chọn backend như thế nào.
- `proxy_pass` trong `config/proxy.conf` nghĩa là gì.
- Round-robin load balancing hoạt động ra sao.
- Nếu backend down thì proxy trả gì cho browser/client.
- `start_proxy.py`, `config/proxy.conf`, `daemon/proxy.py` phối hợp với nhau như thế nào.

Luồng lớn:

```text
Browser/client
  -> connects to proxy, e.g. 127.0.0.1:8080
  -> sends HTTP request with Host header
  -> proxy reads Host
  -> proxy selects backend from config/proxy.conf
  -> proxy opens TCP connection to backend
  -> proxy forwards raw HTTP request
  -> backend returns raw HTTP response
  -> proxy sends that response back to browser/client
```

Proxy trong stage này là phần HTTP reverse proxy độc lập. Nó không phải tracker P2P và không gửi direct chat message giữa peers.

## 2. Theory needed before understanding this stage

### What a proxy server is

Proxy server là server trung gian đứng giữa client và server đích.

Client không nói chuyện trực tiếp với server đích. Client gửi request đến proxy. Proxy thay mặt client gửi tiếp request đến server đích, nhận response, rồi trả lại cho client.

Mô hình tổng quát:

```text
Client -> Proxy -> Destination server
Client <- Proxy <- Destination server
```

Proxy có thể dùng để:

- Ẩn server thật.
- Kiểm soát access.
- Log traffic.
- Cache response.
- Route request đến nhiều backend.
- Load balance.
- Terminate TLS.

Project này chỉ làm một reverse proxy đơn giản: route theo `Host`, forward raw HTTP request, hỗ trợ round-robin.

### What a reverse proxy is

Forward proxy thường đại diện cho client. Ví dụ trong công ty, browser gửi request qua proxy để ra Internet.

Reverse proxy thường đại diện cho server/backend. Client tưởng đang nói chuyện với một server duy nhất, nhưng phía sau có thể có nhiều backend.

```text
Browser
  -> reverse proxy
      -> backend A
      -> backend B
      -> backend C
```

Trong project:

- Browser/client connect đến proxy port, mặc định `8080`.
- Proxy đọc `Host`.
- Proxy chọn backend như `127.0.0.1:9000`, `127.0.0.1:9001`, `127.0.0.1:9002`, `127.0.0.1:9003`.

### Why proxy is placed in front of backend servers

Reverse proxy thường được đặt trước backend vì:

- Client chỉ cần biết một địa chỉ proxy.
- Có thể route nhiều domain/host về nhiều app khác nhau.
- Có thể phân phối tải giữa nhiều backend cùng chức năng.
- Có thể thay backend mà không đổi client.
- Có thể xử lý lỗi backend tập trung.
- Có thể mở rộng sau này: TLS, compression, rate limit, logging.

Trong project, proxy giúp minh họa network concept:

```text
Host: app1.local -> backend 127.0.0.1:9001
Host: app2.local -> backend 127.0.0.1:9002 hoặc 9003
```

### Host-based routing

HTTP/1.1 request thường có `Host` header:

```http
GET / HTTP/1.1
Host: app2.local
```

`Host` cho biết client muốn truy cập virtual host nào. Nhiều website có thể cùng chạy sau một IP/port proxy, và proxy dùng `Host` để quyết định request đi đâu.

Ví dụ:

```text
Host: app1.local -> backend 9001
Host: app2.local -> backend 9002/9003
```

Trong project, `_extract_host(request_bytes)` lấy giá trị `Host` từ raw HTTP request.

### proxy_pass

`proxy_pass` là directive thường thấy trong reverse proxy như Nginx. Nó chỉ backend target mà request sẽ được chuyển tiếp đến.

Trong `config/proxy.conf`:

```text
host "app1.local" {
    proxy_pass http://127.0.0.1:9001;
}
```

Nghĩa là:

```text
Nếu Host header là app1.local,
forward request đến backend 127.0.0.1:9001.
```

Project tự parse directive này trong `parse_proxy_config()`.

### Load balancing

Load balancing là phân phối request đến nhiều backend để:

- giảm tải cho từng backend;
- tăng khả năng phục vụ nhiều request;
- tránh một backend duy nhất thành bottleneck;
- có thể mở rộng số backend.

Ví dụ:

```text
app2.local
  -> backend 9002
  -> backend 9003
```

Nếu có 4 request, proxy có thể gửi:

```text
request 1 -> 9002
request 2 -> 9003
request 3 -> 9002
request 4 -> 9003
```

### Round-robin distribution

Round-robin là load balancing policy đơn giản: chọn backend theo vòng tròn.

Nếu backend list là:

```python
[("127.0.0.1", 9002), ("127.0.0.1", 9003)]
```

thì index tăng dần:

```text
index 0 -> 9002
index 1 -> 9003
index 2 -> 9002
index 3 -> 9003
```

Trong project, round-robin state nằm ở:

```python
_ROUND_ROBIN_INDEX = {}
_ROUND_ROBIN_LOCK = threading.Lock()
```

Lock cần vì proxy dùng thread cho từng client connection. Nhiều thread có thể cùng chọn backend, nên cần tránh race condition khi tăng index.

### What happens when backend is down

Nếu backend down, proxy không connect được đến backend. Reverse proxy nên trả lỗi cho client, thường là:

```http
502 Bad Gateway
```

Ý nghĩa: proxy còn sống, nhưng upstream/backend phía sau lỗi hoặc không reachable.

Trong project:

- `socket.timeout` -> `502 Bad Gateway: backend timeout`
- `OSError` khi connect/send/recv -> `502 Bad Gateway: backend unavailable`
- Backend trả response rỗng -> `502 Bad Gateway: empty backend response`

## 3. Where this concept appears in the assignment requirement

Trong project CO3094 này, proxy thể hiện phần network backend/proxy:

- chạy một server trung gian bằng socket;
- đọc HTTP request từ client;
- parse `Host` header;
- chọn backend từ file config;
- forward raw request;
- trả raw response về client;
- hỗ trợ nhiều backend bằng round-robin.

Các file liên quan trực tiếp:

- `start_proxy.py`: entry point chạy proxy.
- `config/proxy.conf`: cấu hình host routing và `proxy_pass`.
- `daemon/proxy.py`: implementation của reverse proxy.

Cần kiểm tra thêm: source hiện tại parse được `proxy_set_header Host $host;` trong file config? Không. `parse_proxy_config()` chỉ xử lý `host`, `proxy_pass`, `dist_policy`. Dòng `proxy_set_header Host $host;` trong `config/proxy.conf` hiện bị bỏ qua.

## 4. Related files in the project

- `start_proxy.py`: parse `--server-ip`, `--server-port`, đọc `config/proxy.conf`, gọi `create_proxy(...)`.
- `config/proxy.conf`: khai báo mapping từ host name sang backend servers.
- `daemon/proxy.py`: parse config, listen socket, accept client, extract Host, resolve backend, forward request, return response.
- `daemon/backend.py`: backend server có thể được proxy forward đến, nhưng không phải nội dung chính stage này.
- `start_backend.py` hoặc `start_sampleapp.py`: có thể chạy backend phía sau proxy để test.

## 5. Detailed source-code reading notes

### 5.1 `start_proxy.py`: proxy entry point

`start_proxy.py` là launcher.

Nó định nghĩa port mặc định:

```python
PROXY_PORT = 8080
```

Parse command:

```python
parser.add_argument('--server-ip', default='0.0.0.0')
parser.add_argument('--server-port', type=int, default=PROXY_PORT)
```

Sau đó đọc config:

```python
routes = parse_proxy_config("config/proxy.conf")
```

Rồi chạy proxy:

```python
create_proxy(ip, port, routes)
```

Tóm lại:

```text
start_proxy.py
  -> parse CLI
  -> parse config/proxy.conf
  -> create_proxy(ip, port, routes)
```

### 5.2 `config/proxy.conf`: host routing config

File config hiện tại:

```text
host "127.0.0.1:8080" {
    proxy_pass http://127.0.0.1:9000;
}

host "app1.local" {
    proxy_pass http://127.0.0.1:9001;
}

host "app2.local" {
    proxy_set_header Host $host;

    proxy_pass http://127.0.0.1:9002;
    proxy_pass http://127.0.0.1:9003;

    dist_policy round-robin;
}
```

Ý nghĩa:

- Request có `Host: 127.0.0.1:8080` sẽ đến backend `127.0.0.1:9000`.
- Request có `Host: app1.local` sẽ đến backend `127.0.0.1:9001`.
- Request có `Host: app2.local` sẽ được phân phối giữa backend `127.0.0.1:9002` và `127.0.0.1:9003` theo round-robin.

Cần kiểm tra thêm: để browser thật resolve `app1.local` hoặc `app2.local`, máy cần cấu hình hosts file/DNS. Nếu không, có thể test bằng curl với header:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
```

### 5.3 `parse_proxy_config(config_file)`: config text thành route table

Trong `daemon/proxy.py`, `parse_proxy_config()` đọc file text:

```python
with open(config_file, "r", encoding="utf-8") as file_obj:
    config_text = file_obj.read()
```

Sau đó tìm các block:

```python
host_blocks = re.findall(
    r'host\s+"([^"]+)"\s*\{(.*?)\}',
    config_text,
    re.DOTALL,
)
```

Mỗi block có:

```text
hostname
block content
```

Ví dụ với:

```text
host "app2.local" {
    proxy_pass http://127.0.0.1:9002;
    proxy_pass http://127.0.0.1:9003;
    dist_policy round-robin;
}
```

Regex lấy:

```python
hostname = "app2.local"
block = """
    proxy_pass http://127.0.0.1:9002;
    proxy_pass http://127.0.0.1:9003;
    dist_policy round-robin;
"""
```

### 5.4 How `proxy_pass` is parsed

Trong mỗi host block:

```python
for raw_backend in re.findall(r"proxy_pass\s+([^;\s]+)\s*;", block):
```

Với:

```text
proxy_pass http://127.0.0.1:9002;
```

`raw_backend` là:

```text
http://127.0.0.1:9002
```

Sau đó:

```python
parsed = urlparse(raw_backend)
```

Nếu có scheme:

```python
backend_host = parsed.hostname
backend_port = parsed.port
```

Kết quả:

```python
("127.0.0.1", 9002)
```

Các backend được append vào list:

```python
backends.append((backend_host, int(backend_port)))
```

### 5.5 Output của `parse_proxy_config()`

Với config hiện tại, output route table gần như:

```python
{
    "127.0.0.1:8080": {
        "backends": [("127.0.0.1", 9000)],
        "policy": "round-robin",
    },
    "app1.local": {
        "backends": [("127.0.0.1", 9001)],
        "policy": "round-robin",
    },
    "app2.local": {
        "backends": [("127.0.0.1", 9002), ("127.0.0.1", 9003)],
        "policy": "round-robin",
    },
}
```

Policy default là `"round-robin"` nếu không khai báo:

```python
policy = policy_match.group(1) if policy_match else "round-robin"
```

Với host chỉ có một backend, policy gần như không quan trọng vì `resolve_routing_policy()` trả backend duy nhất.

### 5.6 `create_proxy()` và `run_proxy()`

`create_proxy(ip, port, routes)` chỉ gọi:

```python
run_proxy(ip, port, routes or {})
```

`run_proxy()`:

1. Cấu hình logging.
2. Tạo TCP socket.
3. Set `SO_REUSEADDR`.
4. Bind IP/port.
5. Listen.
6. Loop `accept()`.
7. Mỗi client connection tạo một thread gọi `handle_client(...)`.

Code chính:

```python
proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
proxy.bind((ip, port))
proxy.listen(50)

while True:
    conn, addr = proxy.accept()
    client_thread = threading.Thread(
        target=handle_client,
        args=(ip, port, conn, addr, routes),
    )
    client_thread.daemon = True
    client_thread.start()
```

Proxy ở đây là synchronous/threaded, không dùng asyncio.

### 5.7 `handle_client()`: request vào proxy được xử lý ở đâu

`handle_client()` là lifecycle của một client request qua proxy:

```python
request = _read_http_message(conn)
hostname = _extract_host(request)
resolved_host, resolved_port = resolve_routing_policy(hostname, routes)
response = forward_request(resolved_host, resolved_port, request)
conn.sendall(response)
```

Luồng:

```text
client socket
  -> read raw HTTP request
  -> extract Host
  -> select backend
  -> forward raw request to backend
  -> receive raw backend response
  -> send raw response back to client
```

Proxy không parse route path như `/login` hay `/chat.html`. Nó chỉ cần biết `Host` để chọn backend.

### 5.8 `_read_http_message(conn)`: proxy đọc request bytes

Proxy đọc raw HTTP request tương tự HTTP adapter:

```python
while b"\r\n\r\n" not in data:
    chunk = conn.recv(BUFFER_SIZE)
    ...
```

Sau khi có headers, nó đọc body theo `Content-Length`:

```python
content_length = _content_length_from_headers(header_bytes)
while len(body) < content_length:
    chunk = conn.recv(BUFFER_SIZE)
    body += chunk
```

Output là raw request bytes:

```python
return header_bytes + b"\r\n\r\n" + body
```

Điểm quan trọng: proxy không biến request thành `Request` object của framework. Nó giữ request ở dạng bytes để forward nguyên vẹn sang backend.

### 5.9 `_extract_host(request_bytes)`: Host header được dùng thế nào

`_extract_host()` chỉ đọc phần headers:

```python
header_text = request_bytes.split(b"\r\n\r\n", 1)[0].decode(...)
```

Validate request line có 3 phần:

```python
request_line = header_text.split("\r\n", 1)[0]
if len(request_line.split()) != 3:
    raise ValueError("malformed request line")
```

Tìm header:

```python
for line in header_text.split("\r\n")[1:]:
    if line.lower().startswith("host:"):
        return line.split(":", 1)[1].strip().lower()
```

Nếu thiếu `Host`, raise:

```python
ValueError("missing Host header")
```

Nếu Host là:

```http
Host: app2.local
```

output:

```python
"app2.local"
```

Nếu Host là:

```http
Host: 127.0.0.1:8080
```

output:

```python
"127.0.0.1:8080"
```

### 5.10 `resolve_routing_policy(hostname, routes)`: chọn backend

Input:

```python
hostname = "app2.local"
routes = {
    "app2.local": {
        "backends": [("127.0.0.1", 9002), ("127.0.0.1", 9003)],
        "policy": "round-robin",
    }
}
```

Đầu tiên tìm route:

```python
route = routes.get(hostname)
```

Nếu không thấy và hostname có port, bỏ port:

```python
if not route and ":" in hostname:
    route = routes.get(hostname.rsplit(":", 1)[0])
```

Điều này cho phép:

```text
Host: app1.local:8080
```

fallback tìm:

```text
app1.local
```

Nếu không có route:

```python
return None, None
```

Nếu có một backend:

```python
return backends[0]
```

Nếu có nhiều backend, dùng round-robin:

```python
with _ROUND_ROBIN_LOCK:
    index = _ROUND_ROBIN_INDEX.get(hostname, 0)
    backend = backends[index % len(backends)]
    _ROUND_ROBIN_INDEX[hostname] = index + 1
return backend
```

Ví dụ:

```text
_ROUND_ROBIN_INDEX["app2.local"] = 0 -> 9002
_ROUND_ROBIN_INDEX["app2.local"] = 1 -> 9003
_ROUND_ROBIN_INDEX["app2.local"] = 2 -> 9002
```

### 5.11 `forward_request(host, port, request)`: proxy_pass thực thi thật

Đây là nơi proxy mở connection đến backend:

```python
with socket.create_connection((host, port), timeout=BACKEND_TIMEOUT) as backend:
    backend.sendall(request)
    response = b""
    while True:
        chunk = backend.recv(BUFFER_SIZE)
        if not chunk:
            break
        response += chunk
    return response
```

Input:

```python
host = "127.0.0.1"
port = 9002
request = b"GET / HTTP/1.1\r\nHost: app2.local\r\n\r\n"
```

Output:

```python
response = b"HTTP/1.1 200 OK\r\n...\r\n\r\n..."
```

Proxy không tự build response thành HTML/JSON khi backend khỏe. Nó trả nguyên raw response của backend cho client.

### 5.12 Backend down thì proxy làm gì

Trong `forward_request()`:

Nếu backend timeout:

```python
except socket.timeout:
    return bad_gateway("502 Bad Gateway: backend timeout")
```

Nếu backend unavailable:

```python
except OSError:
    return bad_gateway("502 Bad Gateway: backend unavailable")
```

Nếu backend response rỗng:

```python
if not response:
    return bad_gateway("502 Bad Gateway: empty backend response")
```

`bad_gateway()` tạo HTTP response text/plain:

```http
HTTP/1.1 502 Bad Gateway
Content-Type: text/plain; charset=utf-8
Content-Length: ...
Connection: close

502 Bad Gateway: backend unavailable
```

Nghĩa là browser vẫn nhận được HTTP response hợp lệ từ proxy, dù backend bị lỗi.

### 5.13 Proxy gửi response về client

Sau khi `response` được lấy từ backend hoặc được proxy tự tạo lỗi:

```python
conn.sendall(response)
```

Rồi đóng connection trong `finally`:

```python
conn.shutdown(socket.SHUT_RDWR)
conn.close()
```

Proxy không inspect hoặc sửa body response. Nó chỉ log status:

```python
status = _extract_response_status(response)
LOGGER.info("Forwarded response status=%s host=%s", status, hostname)
```

### 5.14 Multiple backend servers support

Một host có thể có nhiều `proxy_pass`:

```text
host "app2.local" {
    proxy_pass http://127.0.0.1:9002;
    proxy_pass http://127.0.0.1:9003;
    dist_policy round-robin;
}
```

`parse_proxy_config()` lưu thành list:

```python
"backends": [("127.0.0.1", 9002), ("127.0.0.1", 9003)]
```

`resolve_routing_policy()` chọn một backend từ list.

Hiện tại chỉ có round-robin. Nếu config ghi policy khác:

```python
if policy != "round-robin":
    LOGGER.warning(...)
```

và vẫn fallback sang round-robin.

Cần kiểm tra thêm: source hiện tại không có health check chủ động. Nếu một backend trong round-robin bị down, proxy vẫn có thể chọn backend đó, request đó sẽ nhận `502`. Request sau có thể đi sang backend khác theo vòng.

## 6. Execution/data flow explanation

### 6.1 Start proxy flow

```text
python start_proxy.py --server-ip 127.0.0.1 --server-port 8080

start_proxy.py
  -> parse_proxy_config("config/proxy.conf")
  -> create_proxy("127.0.0.1", 8080, routes)
  -> run_proxy(...)
  -> bind/listen/accept
```

### 6.2 Request to default local host

Client:

```powershell
curl.exe -i http://127.0.0.1:8080/
```

HTTP request likely contains:

```http
GET / HTTP/1.1
Host: 127.0.0.1:8080
```

Proxy:

```text
_extract_host -> "127.0.0.1:8080"
resolve_routing_policy -> ("127.0.0.1", 9000)
forward_request -> backend 9000
conn.sendall(response) -> client
```

Backend needed:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9000
```

### 6.3 Request to `app1.local`

Client can test with explicit Host:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: app1.local"
```

Proxy:

```text
Host app1.local
  -> config route app1.local
  -> proxy_pass 127.0.0.1:9001
```

Backend needed:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9001
```

### 6.4 Request to `app2.local` with round-robin

Client:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
```

Proxy selection:

```text
request 1 -> 127.0.0.1:9002
request 2 -> 127.0.0.1:9003
request 3 -> 127.0.0.1:9002
```

Backend needed:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9002
python start_backend.py --server-ip 127.0.0.1 --server-port 9003
```

### 6.5 Unknown Host

Client:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: unknown.local"
```

Proxy:

```text
_extract_host -> unknown.local
resolve_routing_policy -> (None, None)
response -> 404 Not Found: invalid proxy route
```

### 6.6 Backend down

If config says:

```text
Host: app1.local -> 127.0.0.1:9001
```

but no backend listens on port `9001`, then:

```text
socket.create_connection(("127.0.0.1", 9001))
  -> OSError / connection refused
  -> bad_gateway("502 Bad Gateway: backend unavailable")
  -> proxy sends 502 to client
```

## 7. Important functions/classes and their role

| Function/constant | File | Role |
|---|---|---|
| `PROXY_PORT` | `start_proxy.py` | Default proxy port `8080` |
| `parse_proxy_config()` | `daemon/proxy.py` | Parse `config/proxy.conf` into route table |
| `create_proxy()` | `daemon/proxy.py` | Entry point to launch proxy |
| `run_proxy()` | `daemon/proxy.py` | Create listening socket, accept clients, spawn threads |
| `handle_client()` | `daemon/proxy.py` | Main lifecycle for one proxied client request |
| `_read_http_message()` | `daemon/proxy.py` | Read full HTTP request from client socket |
| `_content_length_from_headers()` | `daemon/proxy.py` | Read request body length |
| `_extract_host()` | `daemon/proxy.py` | Extract Host header for routing |
| `resolve_routing_policy()` | `daemon/proxy.py` | Select backend by host and load-balancing policy |
| `forward_request()` | `daemon/proxy.py` | Open backend connection, send raw request, receive raw response |
| `_http_response()` | `daemon/proxy.py` | Build proxy-generated error response |
| `bad_request()` | `daemon/proxy.py` | Return 400 for malformed client request |
| `not_found()` | `daemon/proxy.py` | Return 404 for unknown proxy route |
| `bad_gateway()` | `daemon/proxy.py` | Return 502 when backend is bad/unreachable |
| `_ROUND_ROBIN_INDEX` | `daemon/proxy.py` | Per-host round-robin counter |
| `_ROUND_ROBIN_LOCK` | `daemon/proxy.py` | Protect round-robin counter across threads |

## 8. Common mistakes/misunderstandings

- Nhầm proxy với backend. Proxy chỉ forward request; backend mới xử lý application logic/static files.
- Nghĩ proxy route theo URL path. Source hiện tại route theo `Host` header, không theo `/path`.
- Nghĩ `proxy_pass` là redirect. Không đúng: proxy server-side forward request; browser không nhất thiết biết backend thật.
- Nghĩ round-robin kiểm tra backend khỏe trước khi chọn. Source hiện tại không health-check.
- Nghĩ backend down thì browser không nhận gì. Thực tế proxy trả `502 Bad Gateway` nếu nó bắt được lỗi.
- Nghĩ `proxy_set_header Host $host;` đang có tác dụng. Source hiện tại không parse directive này.
- Nghĩ proxy hiểu JSON/HTML body. Proxy forward raw bytes, không parse application body.
- Nghĩ nhiều backend chỉ cần config, không cần chạy backend process. Nếu backend port không có server listen, request sẽ `502`.
- Nghĩ `app1.local` tự hoạt động trong browser. Cần DNS/hosts file hoặc dùng curl `-H "Host: app1.local"`.
- Nghĩ proxy dùng asyncio như backend hiện tại. Source proxy dùng blocking socket + thread.

## 9. Checklist: what I must understand before moving to the next stage

- [ ] I can explain proxy vs backend.
- [ ] I can explain Host-based routing.
- [ ] I can explain proxy_pass.
- [ ] I can explain round-robin.
- [ ] I know where proxy routing is implemented in this project.
- [ ] I know what should happen if backend is unreachable.
- [ ] Tôi biết `start_proxy.py` đọc `config/proxy.conf` trước khi gọi `create_proxy`.
- [ ] Tôi biết `parse_proxy_config()` tạo route table có `backends` và `policy`.
- [ ] Tôi biết `_extract_host()` lấy `Host` header từ raw HTTP request.
- [ ] Tôi biết `resolve_routing_policy()` chọn backend từ route table.
- [ ] Tôi biết `forward_request()` gửi raw HTTP request sang backend.
- [ ] Tôi biết proxy trả raw backend response về client bằng `conn.sendall(response)`.

## 10. Suggested test commands or observation commands if applicable

Chạy backend cho default route:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9000
```

Chạy proxy:

```powershell
python start_proxy.py --server-ip 127.0.0.1 --server-port 8080
```

Test route `127.0.0.1:8080 -> 127.0.0.1:9000`:

```powershell
curl.exe -i http://127.0.0.1:8080/
```

Chạy backend cho `app1.local`:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9001
```

Test `Host: app1.local`:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: app1.local"
```

Chạy hai backend cho `app2.local`:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9002
python start_backend.py --server-ip 127.0.0.1 --server-port 9003
```

Test round-robin:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
curl.exe -i http://127.0.0.1:8080/ -H "Host: app2.local"
```

Test unknown host:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: unknown.local"
```

Test backend down:

```powershell
curl.exe -i http://127.0.0.1:8080/ -H "Host: app1.local"
```

với điều kiện backend port `9001` chưa chạy. Kỳ vọng `502 Bad Gateway`.

Quan sát source:

```powershell
rg -n "parse_proxy_config|proxy_pass|_extract_host|resolve_routing_policy|forward_request|bad_gateway" daemon/proxy.py
```

Kiểm tra syntax:

```powershell
python -m compileall daemon start_proxy.py
```

## 11. Suggested commit message

Suggested commit message:

```text
docs: add stage 04 proxy server explanation
```

Git commands để add và commit **chỉ file này**:

```powershell
git add docs/learning/stage-04-proxy-server.md
git commit -m "docs: add stage 04 proxy server explanation" -- docs/learning/stage-04-proxy-server.md
```
