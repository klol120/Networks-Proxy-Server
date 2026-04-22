"""
CSC 430 — Proxy Server Test Suite
Tests all required features: basic forwarding, caching, blacklist, HTTPS tunnel.

Run with:  python test_proxy.py
The proxy must be running on localhost:8888 before running tests.
"""

import socket
import threading
import time
import json
import urllib.request
import http.client

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8888
ADMIN_URL = f"http://localhost:8080"

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✗\033[0m"

results = []

def test(name, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        results.append((name, True))
    except AssertionError as e:
        print(f"  {FAIL}  {name}: {e}")
        results.append((name, False))
    except Exception as e:
        print(f"  {FAIL}  {name}: {type(e).__name__}: {e}")
        results.append((name, False))

def send_raw(request_bytes, timeout=5):
    """Send raw bytes to proxy and return response."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((PROXY_HOST, PROXY_PORT))
    s.sendall(request_bytes)
    response = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            response += chunk
    except socket.timeout:
        pass
    s.close()
    return response

def get_via_proxy(url, timeout=10):
    """Make HTTP GET via proxy using urllib."""
    proxies = {
        "http": f"http://{PROXY_HOST}:{PROXY_PORT}",
        "https": f"http://{PROXY_HOST}:{PROXY_PORT}",
    }
    proxy_handler = urllib.request.ProxyHandler(proxies)
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url)
    with opener.open(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def capture_forwarded_request(path="/headers"):
    """Capture the exact HTTP request forwarded by the proxy to a local origin server."""
    captured = {}
    ready = threading.Event()

    def origin_server():
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(1)
        captured["port"] = server_socket.getsockname()[1]
        ready.set()

        client_socket, _ = server_socket.accept()
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            data += chunk

        captured["request"] = data.decode("utf-8", errors="replace")
        body = b'{"ok": true}'
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        client_socket.sendall(response)
        client_socket.close()
        server_socket.close()

    threading.Thread(target=origin_server, daemon=True).start()
    assert ready.wait(5), "Origin server did not start"

    url = f"http://127.0.0.1:{captured['port']}{path}"
    status, body = get_via_proxy(url)
    assert status == 200, f"Expected 200 from origin, got {status}"
    assert body == b'{"ok": true}', "Unexpected origin response body"
    return captured.get("request", "")

# ─── Test 1: Proxy is reachable ───────────────────────────────────────────────

def test_proxy_reachable():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    result = s.connect_ex((PROXY_HOST, PROXY_PORT))
    s.close()
    assert result == 0, f"Cannot connect to proxy on port {PROXY_PORT}"

# ─── Test 2: Admin interface reachable ────────────────────────────────────────

def test_admin_reachable():
    conn = http.client.HTTPConnection("localhost", 8080, timeout=3)
    conn.request("GET", "/")
    r = conn.getresponse()
    assert r.status == 200, f"Admin returned status {r.status}"
    body = r.read()
    assert b"Proxy Admin" in body, "Admin page missing expected content"

# ─── Test 3: Basic HTTP forwarding ────────────────────────────────────────────

def test_basic_http():
    status, body = get_via_proxy("http://httpbin.org/get")
    assert status == 200, f"Expected 200, got {status}"
    assert len(body) > 0, "Empty response body"

# ─── Test 4: Request headers forwarded correctly ──────────────────────────────

def test_headers_forwarded():
    request_text = capture_forwarded_request()
    assert "Via: 1.1 CSC430-Proxy" in request_text, "Via header not forwarded"
    assert "Proxy-Connection:" not in request_text, "Proxy-Connection header should be stripped"

# ─── Test 5: Cache — second request should be a hit ──────────────────────────

def test_caching():
    url = "http://httpbin.org/cache/60"  # server sets Cache-Control: max-age=60

    # First request — populates cache
    s1, b1 = get_via_proxy(url)
    assert s1 == 200

    # Check admin API for cache entry
    conn = http.client.HTTPConnection("localhost", 8080, timeout=3)
    conn.request("GET", "/api/stats")
    r = conn.getresponse()
    stats = json.loads(r.read())
    misses_after_first = stats.get("cache_misses", 0)
    assert misses_after_first >= 1, "Cache miss counter not incremented"

    # Second request — should be served from cache
    s2, b2 = get_via_proxy(url)
    assert s2 == 200

    conn2 = http.client.HTTPConnection("localhost", 8080, timeout=3)
    conn2.request("GET", "/api/stats")
    r2 = conn2.getresponse()
    stats2 = json.loads(r2.read())
    assert stats2.get("cache_hits", 0) >= 1, "Cache hit not recorded"

# ─── Test 6: Blacklist blocks request ─────────────────────────────────────────

def test_blacklist_block():
    # Add test domain to blacklist
    conn = http.client.HTTPConnection("localhost", 8080, timeout=3)
    payload = json.dumps({"domain": "blocked-test.invalid"}).encode()
    conn.request("POST", "/api/blacklist/add",
                 body=payload,
                 headers={"Content-Type": "application/json", "Content-Length": len(payload)})
    r = conn.getresponse()
    assert r.status == 200
    r.read()

    # Send request to blocked host
    raw = (
        b"GET http://blocked-test.invalid/ HTTP/1.1\r\n"
        b"Host: blocked-test.invalid\r\n"
        b"Connection: close\r\n\r\n"
    )
    response = send_raw(raw, timeout=3)
    assert b"403" in response, "Expected 403 Forbidden for blacklisted domain"

# ─── Test 7: HTTPS CONNECT tunnel ─────────────────────────────────────────────

def test_https_connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((PROXY_HOST, PROXY_PORT))
    s.sendall(b"CONNECT httpbin.org:443 HTTP/1.1\r\nHost: httpbin.org:443\r\n\r\n")
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = s.recv(1024)
        if not chunk:
            break
        response += chunk
    s.close()
    assert b"200" in response, f"Expected 200 Connection Established, got: {response[:200]}"

# ─── Test 8: Admin stats API ──────────────────────────────────────────────────

def test_admin_stats():
    conn = http.client.HTTPConnection("localhost", 8080, timeout=3)
    conn.request("GET", "/api/stats")
    r = conn.getresponse()
    assert r.status == 200
    data = json.loads(r.read())
    assert "total_requests" in data

# ─── Test 9: Admin config update ──────────────────────────────────────────────

def test_admin_config():
    conn = http.client.HTTPConnection("localhost", 8080, timeout=3)
    payload = json.dumps({"cache_timeout": 600}).encode()
    conn.request("POST", "/api/config",
                 body=payload,
                 headers={"Content-Type": "application/json", "Content-Length": len(payload)})
    r = conn.getresponse()
    assert r.status == 200
    data = json.loads(r.read())
    assert data.get("config", {}).get("cache_timeout") == 600

# ─── Test 10: Concurrent connections ─────────────────────────────────────────

def test_concurrent_connections():
    errors = []
    def make_request():
        try:
            s, b = get_via_proxy("http://httpbin.org/get")
            assert s == 200
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=make_request) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert len(errors) == 0, f"Concurrent errors: {errors}"


if __name__ == "__main__":
    print("\n╔══════════════════════════════════════╗")
    print("║  CSC430 Proxy Server — Test Suite    ║")
    print("╚══════════════════════════════════════╝\n")
    print(f"  Proxy: {PROXY_HOST}:{PROXY_PORT}")
    print(f"  Admin: http://localhost:8080\n")
    print("─" * 42)

    test("Proxy is reachable",            test_proxy_reachable)
    test("Admin interface reachable",     test_admin_reachable)
    test("Basic HTTP forwarding",         test_basic_http)
    test("Request headers forwarded",     test_headers_forwarded)
    test("Content caching",               test_caching)
    test("Blacklist blocks request",      test_blacklist_block)
    test("HTTPS CONNECT tunnel",          test_https_connect)
    test("Admin stats API",               test_admin_stats)
    test("Admin config update",           test_admin_config)
    test("Concurrent connections (x5)",   test_concurrent_connections)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print("─" * 42)
    print(f"\n  Results: {passed}/{total} passed\n")
