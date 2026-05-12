"""
Simple standard-library stress test client for the CO3094 backend.

Examples:
    python tools/stress_test.py --url http://127.0.0.1:2026/async-hello
    python tools/stress_test.py --url http://127.0.0.1:2026/chat-state?channel=general --requests 100 --concurrency 20
"""

import argparse
import asyncio
import time
from urllib.parse import urlparse


async def fetch(parsed_url, path, method="GET", body=b"", headers=None, timeout=10):
    headers = headers or {}
    port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(parsed_url.hostname, port),
        timeout=timeout,
    )
    request_headers = {
        "Host": parsed_url.netloc,
        "Connection": "close",
    }
    request_headers.update(headers)
    if body:
        request_headers["Content-Length"] = str(len(body))

    raw_request = "{} {} HTTP/1.1\r\n".format(method, path)
    raw_request += "".join(
        "{}: {}\r\n".format(key, value)
        for key, value in request_headers.items()
    )
    raw_request += "\r\n"

    started = time.perf_counter()
    writer.write(raw_request.encode("iso-8859-1") + body)
    await writer.drain()
    response = await asyncio.wait_for(reader.read(), timeout=timeout)
    writer.close()
    await writer.wait_closed()
    elapsed = time.perf_counter() - started

    status_line = response.split(b"\r\n", 1)[0].decode(
        "iso-8859-1",
        errors="replace",
    )
    parts = status_line.split()
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    return status, elapsed


async def worker(_name, queue, parsed_url, path, results, timeout):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        try:
            results.append(await fetch(parsed_url, path, timeout=timeout))
        except (asyncio.TimeoutError, OSError):
            results.append((0, 0))
        finally:
            queue.task_done()


async def run(args):
    parsed_url = urlparse(args.url)
    path = parsed_url.path or "/"
    if parsed_url.query:
        path += "?" + parsed_url.query

    queue = asyncio.Queue()
    results = []
    workers = [
        asyncio.create_task(
            worker(index, queue, parsed_url, path, results, args.timeout)
        )
        for index in range(args.concurrency)
    ]

    started = time.perf_counter()
    for index in range(args.requests):
        await queue.put(index)
    for _ in workers:
        await queue.put(None)
    await queue.join()
    await asyncio.gather(*workers)
    elapsed = time.perf_counter() - started

    ok = sum(1 for status, _ in results if 200 <= status < 400)
    failed = len(results) - ok
    latencies = [latency for _, latency in results if latency]
    avg_ms = (sum(latencies) / len(latencies) * 1000) if latencies else 0
    rate = len(results) / elapsed if elapsed else 0

    print("requests={}".format(len(results)))
    print("concurrency={}".format(args.concurrency))
    print("ok={}".format(ok))
    print("failed={}".format(failed))
    print("avg_latency_ms={:.2f}".format(avg_ms))
    print("requests_per_second={:.2f}".format(rate))


def main():
    parser = argparse.ArgumentParser(description="Async HTTP stress test")
    parser.add_argument("--url", required=True)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
