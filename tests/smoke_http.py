"""Smoke test for the HTTP tracker using only the standard library.

Run the tracker first::

    python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026

Then run this script::

    python tests/smoke_http.py
"""

import http.client
import json
import sys
from http.cookies import SimpleCookie

TRACKER_HOST = "127.0.0.1"
TRACKER_PORT = 2026

passed = 0
failed = 0


def request(method, path, payload=None, cookie=""):
    """Send one HTTP request and return (status, headers, parsed JSON)."""
    body = b""
    headers = {"Host": "{}:{}".format(TRACKER_HOST, TRACKER_PORT)}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    if cookie:
        headers["Cookie"] = cookie

    conn = http.client.HTTPConnection(TRACKER_HOST, TRACKER_PORT, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        resp_headers = resp.getheaders()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        return resp.status, resp_headers, data
    finally:
        conn.close()


def extract_cookie(headers):
    """Extract session_id cookie value from response headers."""
    for name, value in headers:
        if name.lower() == "set-cookie":
            sc = SimpleCookie()
            sc.load(value)
            if "session_id" in sc:
                return "session_id={}".format(sc["session_id"].value)
    return ""


def check(label, condition):
    """Print PASS or FAIL for one check."""
    global passed, failed
    if condition:
        passed += 1
        print("  PASS  {}".format(label))
    else:
        failed += 1
        print("  FAIL  {}".format(label))


def main():
    """Run all smoke checks against a running tracker."""
    print("smoke test against {}:{}".format(TRACKER_HOST, TRACKER_PORT))
    print()

    # 1. Login
    print("[login]")
    status, headers, data = request(
        "POST", "/login",
        {"username": "alice", "password": "wonderland"},
    )
    cookie = extract_cookie(headers)
    check("login returns 200", status == 200)
    check("login returns username", data.get("username") == "alice")
    check("login sets session cookie", bool(cookie))
    print()

    # 2. /me without cookie
    print("[/me without cookie]")
    status, _, data = request("GET", "/me")
    check("/me without cookie returns 401", status == 401)
    print()

    # 3. /me with cookie
    print("[/me with cookie]")
    status, _, data = request("GET", "/me", cookie=cookie)
    check("/me returns 200", status == 200)
    check("/me returns alice", data.get("username") == "alice")
    print()

    # 4. Submit peer info
    print("[submit-info]")
    status, _, data = request(
        "POST", "/submit-info",
        {"peer_ip": "127.0.0.1", "peer_port": 19001, "status": "online"},
        cookie=cookie,
    )
    check("/submit-info returns 200", status == 200)
    check("/submit-info returns peer list", isinstance(data.get("peers"), list))
    print()

    # 5. /submit-info without cookie
    print("[submit-info without cookie]")
    status, _, _ = request(
        "POST", "/submit-info",
        {"peer_ip": "127.0.0.1", "peer_port": 19001},
    )
    check("/submit-info without cookie returns 401", status == 401)
    print()

    # 6. Get list
    print("[get-list]")
    status, _, data = request("GET", "/get-list", cookie=cookie)
    check("/get-list returns 200", status == 200)
    peers = data.get("peers", [])
    check("/get-list contains alice", any(
        p.get("username") == "alice" for p in peers
    ))
    print()

    # 7. Heartbeat
    print("[heartbeat]")
    status, _, data = request(
        "POST", "/heartbeat",
        {"peer_ip": "127.0.0.1", "peer_port": 19001, "status": "online"},
        cookie=cookie,
    )
    check("/heartbeat returns 200", status == 200)
    check("/heartbeat refreshed >= 1", data.get("refreshed", 0) >= 1)
    print()

    # 8. Tracker state
    print("[tracker-state]")
    status, _, data = request("GET", "/tracker-state", cookie=cookie)
    check("/tracker-state returns 200", status == 200)
    check("/tracker-state has user", "user" in data)
    check("/tracker-state has peers", "peers" in data)
    print()

    # 9. Connect-peer (informational discovery, not server forwarding)
    print("[connect-peer]")
    # Login bob in a separate session and register his peer endpoint.
    bob_status, bob_headers, _ = request(
        "POST", "/login",
        {"username": "bob", "password": "wonderland"},
    )
    bob_cookie = extract_cookie(bob_headers)
    check("bob login returns 200", bob_status == 200)
    check("bob login sets cookie", bool(bob_cookie))

    bob_port = 19002
    status, _, _ = request(
        "POST", "/submit-info",
        {"peer_ip": "127.0.0.1", "peer_port": bob_port, "status": "online"},
        cookie=bob_cookie,
    )
    check("bob /submit-info returns 200", status == 200)

    status, _, data = request(
        "POST", "/connect-peer",
        {"username": "bob"},
        cookie=cookie,
    )
    check("/connect-peer returns 200", status == 200)
    check("/connect-peer returns bob", data.get("username") == "bob")
    check("/connect-peer returns peer_ip 127.0.0.1",
          data.get("peer_ip") == "127.0.0.1")
    check("/connect-peer returns expected peer_port",
          data.get("peer_port") == bob_port)

    status, _, _ = request("POST", "/connect-peer", {}, cookie=cookie)
    check("/connect-peer with empty body returns 400", status == 400)

    status, _, _ = request(
        "POST", "/connect-peer",
        {"username": "no_such_user"},
        cookie=cookie,
    )
    check("/connect-peer with unknown peer returns 404", status == 404)

    status, _, _ = request(
        "POST", "/connect-peer",
        {"username": "alice"},
        cookie=cookie,
    )
    check("/connect-peer to self returns 400", status == 400)

    status, _, _ = request("POST", "/connect-peer", {"username": "bob"})
    check("/connect-peer without cookie returns 401", status == 401)

    # Clean up bob peer record so the rest of the suite is unaffected.
    request(
        "POST", "/leave",
        {"peer_ip": "127.0.0.1", "peer_port": bob_port},
        cookie=bob_cookie,
    )
    print()

    # 10. Deprecated endpoints (must still be rejected)
    print("[deprecated endpoints]")
    for path in ("/send-peer", "/broadcast-peer"):
        status, _, data = request("POST", path)
        check("{} returns 410".format(path), status == 410)
    status, _, data = request("GET", "/peer-inbox")
    check("/peer-inbox returns 410", status == 410)
    print()

    # 11. Leave
    print("[leave]")
    status, _, data = request(
        "POST", "/leave",
        {"peer_ip": "127.0.0.1", "peer_port": 19001},
        cookie=cookie,
    )
    check("/leave returns 200", status == 200)
    print()

    # Summary
    total = passed + failed
    print("=" * 40)
    print("{}/{} checks passed".format(passed, total))
    if failed:
        print("{} FAILED".format(failed))
        sys.exit(1)
    else:
        print("ALL PASSED")


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError:
        print("ERROR: cannot connect to {}:{}".format(TRACKER_HOST, TRACKER_PORT))
        print("Start the tracker first:")
        print("  python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026")
        sys.exit(1)
