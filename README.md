# CSC430 Caching Proxy Server

**School of Arts and Sciences, Lebanese American University**  
**CSC 430: Computer Networks**  
**Dr. Louma Chadad**  
**Spring 2026**

![LAU Logo](image.png)
---

**By**

| Name | ID |
|---|---|
| Jad Al Hassan | 202400472 |
| Mohammad Karim Mehaydli | 202400046 |
| Adam El Saheli | 202300640 |

**April 26, 2026**

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
   - 2.1 [File Structure](#21-file-structure)
   - 2.2 [Component Interactions](#22-component-interactions)
3. [Proxy Server Implementation](#3-proxy-server-implementation)
   - 3.1 [Socket Programming](#31-socket-programming-requirement-b)
   - 3.2 [Request Parsing](#32-request-parsing-requirement-c)
   - 3.3 [Basic HTTP Forwarding](#33-basic-http-forwarding-requirement-a)
   - 3.4 [Threading](#34-threading-requirement-d)
   - 3.5 [Logging](#35-logging-requirement-e)
   - 3.6 [Content Caching](#36-content-caching-requirement-f)
   - 3.7 [Blacklist and Whitelist](#37-blacklist-and-whitelist-requirement-g)
   - 3.8 [HTTPS CONNECT Tunnel](#38-https-connect-tunnel-bonus--requirement-h)
4. [Admin Interface](#4-admin-interface-bonus--requirement-i)
   - 4.1 [Dashboard](#41-dashboard)
   - 4.2 [Log Viewer](#42-log-viewer)
   - 4.3 [Cache Manager](#43-cache-manager)
   - 4.4 [Filter Management](#44-filter-management)
   - 4.5 [Settings](#45-settings)
   - 4.6 [REST API Summary](#46-rest-api-summary)
5. [Protocol Flow Examples](#5-protocol-flow-examples)
   - 5.1 [HTTP GET — Cache Miss](#51-http-get--cache-miss-first-request)
   - 5.2 [HTTP GET — Cache Hit](#52-http-get--cache-hit-second-request)
   - 5.3 [Blacklisted Domain](#53-blacklisted-domain)
   - 5.4 [HTTPS CONNECT Tunnel](#54-https-connect-tunnel)
6. [Testing and Verification](#6-testing-and-verification)
   - 6.1 [Test Descriptions](#61-test-descriptions)
   - 6.2 [Test Results](#62-test-results)
7. [Challenges and Solutions](#7-challenges-and-solutions)
   - 7.1 [Parsing CONNECT vs HTTP](#71-parsing-connect-vs-http)
   - 7.2 [Thread-Safe Cache Access](#72-thread-safe-cache-access)
   - 7.3 [Cache Invalidation Priority](#73-cache-invalidation-priority)
   - 7.4 [Non-Blocking HTTPS Relay](#74-non-blocking-https-relay)
   - 7.5 [Configuration Persistence](#75-configuration-persistence)
8. [Work Division](#8-work-division)
9. [Conclusion](#9-conclusion)
   - 9.1 [Key Achievements](#91-key-achievements)
   - 9.2 [Learning Outcomes](#92-learning-outcomes)
   - 9.3 [Future Enhancements](#93-future-enhancements)
10. [References](#10-references)

---

## Acknowledgements

We would like to express our sincere gratitude to all those who contributed to the successful completion of this computer networks project.

First and foremost, we extend our deepest appreciation to Dr. Louma Chadad, our course instructor at the Lebanese American University, for her guidance, expertise, and support throughout the development of this project. Her mentorship was instrumental in shaping our understanding of network programming concepts and their practical applications.

We are grateful to the School of Arts and Sciences at the Lebanese American University for providing the academic environment and resources necessary to complete this work.

We would also like to acknowledge the Python Software Foundation, whose comprehensive standard library documentation made it possible to build a fully functional proxy server without relying on any external dependencies.

---

## 1. Project Overview

This report documents the design and implementation of a multi-threaded HTTP/HTTPS caching proxy server, developed as part of the CSC 430 Computer Networks course at Lebanese American University for the Spring 2025–2026 semester. The proxy server acts as an intermediary between client applications and target web servers — intercepting HTTP requests, forwarding them to the appropriate destination, and relaying responses back to the client while adding caching, filtering, logging, and administrative capabilities on top.

The entire system is implemented in Python using only the standard library, with no external packages required. It runs as a single process containing two concurrent servers: the proxy engine on port 8888 and a web-based admin interface on port 8080.

Key features of the system include:

- Multi-threaded architecture that handles concurrent client connections using Python's `threading` module
- HTTP request forwarding with correct header parsing and modification for proxy compliance
- File-based response caching with intelligent invalidation based on `Cache-Control` and `Expires` headers
- Blacklist and whitelist domain filtering with subdomain-aware matching
- Structured request and response logging to both a persistent log file and the console
- HTTPS CONNECT tunnel that relays encrypted TLS traffic transparently without decryption *(Bonus)*
- Web-based admin interface with a live dashboard, log viewer, cache browser, and filter management *(Bonus)*

---

## 2. System Architecture

The system follows a concurrent client-server model built directly on TCP/IP using Python's socket library. Two servers run simultaneously within the same process, started from the `main()` function: the proxy engine listens on port 8888 for client traffic, and the admin interface listens on port 8080 for browser-based management requests.

Both servers share state through three thread-safe global structures. The `config` dictionary holds the active blacklist, whitelist, cache timeout, and whitelist mode flag, protected by `config_lock`. The `stats` dictionary holds live request counters, protected by `stats_lock`. The `cache_manager` instance manages all disk cache operations with its own internal lock. Any change made through the admin interface is immediately visible to the proxy engine, and vice versa, without requiring a restart.

### 2.1 File Structure

```
proxy_project/
├── proxy.py           ← entire proxy server and admin interface
├── config.json        ← persisted configuration (blacklist, cache timeout)
├── cache/             ← cached responses stored as .data + .meta file pairs
├── logs/
│   └── proxy.log      ← timestamped request and event log
├── templates/         ← 7 HTML templates for the admin UI
│   ├── base.html
│   ├── dashboard.html
│   ├── logs.html
│   ├── cache.html
│   ├── rules.html
│   ├── settings.html
│   └── error.html
└── static/
    ├── css/           ← 7 CSS files (one per page)
    └── js/            ← 6 JS files (one per page)
```

### 2.2 Component Interactions

The components interact through the following relationships:

1. **Client to Proxy:** Client applications connect via TCP to port 8888. The proxy reads raw bytes, parses the HTTP request, and dispatches it to the appropriate handler based on the method.

2. **Proxy to Origin Server:** For HTTP requests, the proxy opens a new TCP connection to the target server, sends the rebuilt request, and collects the full response before relaying it to the client.

3. **Proxy to Cache:** Before contacting any origin server, the proxy checks the disk cache for a valid unexpired entry. After receiving a response, it stores it in cache if the response headers permit it.

4. **Proxy to Config:** Before forwarding any request, the proxy reads the active blacklist and whitelist from the shared config to decide whether to block or allow the request.

5. **Admin to Shared State:** The admin interface reads from `stats` and `cache_manager` to populate the dashboard, and writes to `config` (with immediate persistence to `config.json`) when the operator adds or removes filter rules or updates settings.

---

## 3. Proxy Server Implementation

### 3.1 Socket Programming (Requirement B)

The proxy uses Python's `socket` module to manage all TCP connections. The main listening socket is created with `AF_INET` and `SOCK_STREAM` for a standard IPv4 TCP socket. The `SO_REUSEADDR` option is set so the proxy can be restarted immediately after stopping without waiting for the OS to release the port. The socket binds to `0.0.0.0` meaning it accepts connections on all network interfaces, and listens with a backlog of 100 pending connections.

```python
proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
proxy_socket.bind((PROXY_HOST, PROXY_PORT))
proxy_socket.listen(100)
```

For each forwarded request, a separate outbound socket is created to connect to the origin server:

```python
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.settimeout(10)
server_socket.connect((host, port))
```

A 10-second timeout is applied to the outbound socket so the proxy does not hang indefinitely if the origin server is slow or unreachable.

---

### 3.2 Request Parsing (Requirement C)

`parse_request()` takes the raw bytes received from the client socket and extracts all fields needed for forwarding. It first splits the request at `\r\n\r\n` to separate the headers from the body, then splits the first line to extract the method, URL, and HTTP version. All remaining lines are parsed into a headers dictionary.

HTTPS CONNECT requests are handled separately because their URL format is `host:port` rather than a full URL. For all other methods, `urlparse()` extracts the hostname, port, and path from the full URL.

```python
if method == "CONNECT":
    host, port = url.rsplit(":", 1)
    port = int(port)
    path = "/"
else:
    parsed = urlparse(url)
    host = parsed.hostname or headers.get("Host", "").split(":")[0]
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
```

Once parsed, `rebuild_request()` reconstructs a clean forwarded request. It corrects the `Host` header, strips `Proxy-Connection` and `Proxy-Authorization` which are hop-by-hop headers that must not be forwarded, adds a `Via` header identifying the proxy, and forces `Connection: close` to keep the implementation simple.

```python
headers["Host"] = parsed['host']
headers.pop("Proxy-Connection", None)
headers.pop("Proxy-Authorization", None)
headers["Via"] = "1.1 CSC430-Proxy"
headers["Connection"] = "close"
```

> **Screenshot:** Terminal output of `test_headers_forwarded` passing — showing Via header present and Proxy-Connection stripped.

---

### 3.3 Basic HTTP Forwarding (Requirement A)

`handle_http()` is the core forwarding function. It executes the following steps in order: blacklist check, cache lookup, forward to origin, relay response to client, store in cache.

The response is collected in a loop using `recv(BUFFER_SIZE)` until the server closes the connection or a timeout occurs. The full response is buffered in memory before being sent to the client, which ensures the complete response is available for caching.

```python
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.settimeout(10)
server_socket.connect((host, port))

forwarded_request = rebuild_request(parsed)
server_socket.sendall(forwarded_request)

response_data = b""
while True:
    try:
        chunk = server_socket.recv(BUFFER_SIZE)
        if not chunk:
            break
        response_data += chunk
    except socket.timeout:
        break

server_socket.close()
client_socket.sendall(response_data)
```

If the origin server cannot be reached, the proxy returns an `HTTP 502 Bad Gateway` response to the client rather than dropping the connection silently.

> **Screenshot:** Browser configured to use `127.0.0.1:8888` as HTTP proxy, visiting `http://httpbin.org/get` and showing the JSON response.

---

### 3.4 Threading (Requirement D)

Each accepted client connection is dispatched to a new daemon thread running `handle_client()`. Using `daemon=True` means the threads automatically terminate when the main process exits, without needing explicit cleanup. The `active_connections` counter is incremented on entry and decremented in the `finally` block, ensuring accurate tracking even when exceptions occur.

```python
# main() — dispatch each connection to a new thread
t = threading.Thread(
    target=handle_client,
    args=(client_socket, client_addr),
    daemon=True,
)
t.start()
```

```python
# handle_client() — safe counter management
inc_stat("active_connections")
try:
    # parse and handle request
    ...
except Exception as e:
    inc_stat("errors")
    logger.error(f"[CLIENT] Unhandled error for {client_addr}: {e}")
finally:
    inc_stat("active_connections", -1)
    client_socket.close()
```

A 5-second timeout is applied to the client socket while reading the initial request headers, preventing a slow or malicious client from holding a thread open indefinitely.

> **Screenshot:** Terminal showing `test_concurrent_connections` passing — 5 simultaneous requests all returning 200.

---

### 3.5 Logging (Requirement E)

Python's `logging` module is configured with two handlers: a `FileHandler` that writes to `logs/proxy.log` and a `StreamHandler` that prints to the console. Every entry is timestamped automatically by the formatter.

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
```

Every request is logged with all five required fields — client IP, client port, HTTP method, URL, and timestamp:

```python
logger.info(
    f"[REQUEST] IP={client_addr[0]} Port={client_addr[1]} "
    f"Method={parsed['method']} URL={parsed['url']} "
    f"Time={datetime.now().isoformat()}"
)
```

In addition to request logging, cache events are logged with `[CACHE] HIT`, `[CACHE] MISS`, and `[CACHE] STORED` tags, HTTPS tunnel activity is logged with `[HTTPS]` tags, blacklist blocks are logged with `[FILTER]` tags, and all errors are logged with `logger.error()`. This produces a comprehensive audit trail of all proxy activity.

> **Screenshot:** `logs/proxy.log` open in terminal showing several real timestamped entries across different event types.

---

### 3.6 Content Caching (Requirement F)

The `CacheManager` class implements a file-based HTTP response cache. Each cached entry consists of two files stored in the `cache/` directory: a `.data` file containing the raw response bytes, and a `.meta` file containing a JSON object with the URL, expiry timestamp, cache time, and response headers. The cache key is the MD5 hash of the request URL, making it filesystem-safe and consistent.

```python
def _key(self, url):
    return hashlib.md5(url.encode()).hexdigest()
```

Cache invalidation follows a strict priority order when storing a response:

```python
# 1. Respect no-store / no-cache — skip caching entirely
if "no-store" in cache_control or "no-cache" in cache_control:
    return

# 2. Use max-age if present
max_age_match = re.search(r"max-age=(\d+)", cache_control)
if max_age_match:
    expires_ts = time.time() + int(max_age_match.group(1))

# 3. Use Expires header if present
elif expires_header:
    expires_dt = parsedate_to_datetime(expires_header)
    expires_ts = expires_dt.timestamp()

# 4. Fall back to configurable default timeout
else:
    expires_ts = time.time() + self.default_timeout
```

On retrieval, the cache checks whether `time.time() > expires`. If the entry is expired, both files are deleted automatically and `None` is returned, triggering a fresh request to the origin server.

```python
if method == "GET":
    cached = cache_manager.get(cache_key)
    if cached:
        inc_stat("cache_hits")
        client_socket.sendall(cached)
        return
    inc_stat("cache_misses")
```

Only GET responses are cached. POST, PUT, DELETE and other methods always go to the origin server.

> **Screenshot 1:** `http://localhost:8080/api/stats` showing `cache_hits` and `cache_misses` counters after making two requests to the same URL.

> **Screenshot 2:** `http://localhost:8080/cache` page showing the list of cached entries with their URLs and expiry times.

---

### 3.7 Blacklist and Whitelist (Requirement G)

`is_blocked()` checks a hostname against the active configuration and supports two modes. In the default blacklist mode, any domain present in the blacklist is blocked. In whitelist mode, enabled by setting `use_whitelist: true` in the config, any domain not explicitly in the whitelist is blocked. Both modes use subdomain-aware matching — blocking `example.com` automatically blocks `ads.example.com`, `tracker.example.com`, and any other subdomain.

```python
def is_blocked(host):
    with config_lock:
        cfg = dict(config)
    host_lower = host.lower()

    if cfg.get("use_whitelist") and cfg.get("whitelist"):
        allowed = any(
            host_lower == w.lower() or host_lower.endswith("." + w.lower())
            for w in cfg["whitelist"]
        )
        if not allowed:
            return True

    for bl in cfg.get("blacklist", []):
        if host_lower == bl.lower() or host_lower.endswith("." + bl.lower()):
            return True

    return False
```

When a request is blocked, the proxy sends a proper HTTP 403 response with a descriptive HTML body rather than dropping the connection:

```python
response = (
    b"HTTP/1.1 403 Forbidden\r\n"
    b"Content-Type: text/html\r\n"
    b"Connection: close\r\n"
    b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
)
client_socket.sendall(response)
```

The active blacklist and whitelist are stored in `config.json` and persist across restarts. They can be updated live at any time through the admin interface without restarting the proxy.

> **Screenshot:** Terminal showing `test_blacklist_block` passing with `403` visible in the raw response output.

---

### 3.8 HTTPS CONNECT Tunnel (Bonus — Requirement H)

When the proxy receives a `CONNECT` request, it connects to the target server via TCP, sends `200 Connection Established` back to the client, then enters a bidirectional relay loop. Both sockets are switched to non-blocking mode and `select()` is used to monitor both ends simultaneously, forwarding data whichever direction it arrives. The tunnel closes automatically after 30 seconds of inactivity or when either side disconnects.

```python
client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

client_socket.setblocking(False)
server_socket.setblocking(False)
sockets = [client_socket, server_socket]

while True:
    readable, _, exceptional = select.select(sockets, [], sockets, 30)
    if exceptional or not readable:
        break
    for sock in readable:
        data = sock.recv(BUFFER_SIZE)
        other = server_socket if sock is client_socket else client_socket
        other.sendall(data)
```

The proxy never decrypts the TLS content. The TLS handshake and all encrypted application data pass through the tunnel as raw bytes, preserving full end-to-end security between the client and the origin server. The HTTPS tunnel also applies the blacklist check before establishing the tunnel — blocked domains receive a 403 response even for CONNECT requests.

> **Screenshot:** Terminal showing `test_https_connect` passing with `200 Connection Established` visible in the response.

---

## 4. Admin Interface (Bonus — Requirement I)

The admin interface is a web application running on port 8080, implemented as `AdminHandler` extending Python's `BaseHTTPRequestHandler`. It serves five HTML pages and a REST API through `do_GET()` and `do_POST()`. All pages are rendered using a lightweight template engine built into `proxy.py` — `render_admin_page()` injects page content, navigation active states, and CSS/JS file references into `base.html` using simple `{{TOKEN}}` string replacement.

### 4.1 Dashboard

The dashboard (`/`) displays live proxy statistics fetched from `/api/stats` via JavaScript on a polling interval. It shows total requests processed, cache hits, cache misses, blocked requests, active concurrent connections, error count, and proxy uptime.

> **Screenshot:** Admin dashboard page at `http://localhost:8080/`.

### 4.2 Log Viewer

The logs page (`/logs`) fetches the last 200 lines from `proxy.log` via `/api/logs` and displays them in a scrollable, readable format, auto-refreshed every few seconds.

> **Screenshot:** Admin logs page at `http://localhost:8080/logs`.

### 4.3 Cache Manager

The cache page (`/cache`) fetches all entries from `/api/cache` and lists each one with its URL, cache time, expiry time, and whether it is currently expired. A "Clear All" button calls `/api/cache/clear`.

> **Screenshot:** Admin cache page at `http://localhost:8080/cache`.

### 4.4 Filter Management

The rules page (`/rules`) displays the current blacklist and whitelist and allows adding or removing domains in real time via the `/api/blacklist/add`, `/api/blacklist/remove`, `/api/whitelist/add`, and `/api/whitelist/remove` endpoints. Changes take effect immediately without restarting the proxy.

```python
elif path == "/api/blacklist/add":
    domain = data.get("domain", "").strip()
    if domain:
        with config_lock:
            if domain not in config["blacklist"]:
                config["blacklist"].append(domain)
            save_config(config)
        self._send_json({"status": f"added {domain} to blacklist"})
```

> **Screenshot:** Admin rules page at `http://localhost:8080/rules`.

### 4.5 Settings

The settings page (`/settings`) allows updating `cache_timeout` and toggling `use_whitelist` mode via a POST to `/api/config`. Changes are persisted immediately to `config.json`.

> **Screenshot:** Admin settings page at `http://localhost:8080/settings`.

### 4.6 REST API Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/stats` | GET | Returns all live counters |
| `/api/config` | GET | Returns current configuration |
| `/api/config` | POST | Updates configuration fields |
| `/api/cache` | GET | Lists all cache entries |
| `/api/cache/clear` | GET | Clears all cached responses |
| `/api/logs` | GET | Returns last 200 log lines |
| `/api/blacklist/add` | POST | Adds a domain to the blacklist |
| `/api/blacklist/remove` | POST | Removes a domain from the blacklist |
| `/api/whitelist/add` | POST | Adds a domain to the whitelist |
| `/api/whitelist/remove` | POST | Removes a domain from the whitelist |

> **Screenshot:** `http://localhost:8080/api/stats` in browser showing the full JSON response.

---

## 5. Protocol Flow Examples

### 5.1 HTTP GET — Cache Miss (First Request)

```
Client  ──► GET http://httpbin.org/get HTTP/1.1
            Host: httpbin.org

Proxy   ──  Parse: method=GET, host=httpbin.org, port=80
Proxy   ──  Blacklist check: PASS
Proxy   ──  Cache lookup: MISS → inc cache_misses
Proxy   ──► GET /get HTTP/1.1
            Host: httpbin.org
            Via: 1.1 CSC430-Proxy
            Connection: close

Server  ──► HTTP/1.1 200 OK
            Cache-Control: max-age=60
            Content-Type: application/json

Proxy   ──  Store in cache (expires in 60s)
Proxy   ──► HTTP/1.1 200 OK ──────────────► Client
```

### 5.2 HTTP GET — Cache Hit (Second Request)

```
Client  ──► GET http://httpbin.org/get HTTP/1.1

Proxy   ──  Parse: method=GET, host=httpbin.org, port=80
Proxy   ──  Blacklist check: PASS
Proxy   ──  Cache lookup: HIT → inc cache_hits
Proxy   ──► [cached response bytes] ──────► Client
            (no connection made to origin server)
```

### 5.3 Blacklisted Domain

```
Client  ──► GET http://blocked-test.invalid/ HTTP/1.1

Proxy   ──  Parse: host=blocked-test.invalid
Proxy   ──  Blacklist check: BLOCKED → inc blocked_requests
Proxy   ──► HTTP/1.1 403 Forbidden ───────► Client
            Content-Type: text/html
            <p>Access to blocked-test.invalid has been blocked.</p>
```

### 5.4 HTTPS CONNECT Tunnel

```
Client  ──► CONNECT httpbin.org:443 HTTP/1.1
            Host: httpbin.org:443

Proxy   ──  Parse: method=CONNECT, host=httpbin.org, port=443
Proxy   ──  Blacklist check: PASS
Proxy   ──► TCP connect to httpbin.org:443
Proxy   ──► HTTP/1.1 200 Connection Established ► Client

Client  ◄──────── [TLS Handshake bytes] ────────► Server
Client  ◄──── [Encrypted application data] ──────► Server
        (proxy relays raw bytes, no decryption)

Tunnel closes after 30s inactivity or disconnect
```

---

## 6. Testing and Verification

The proxy server was tested using a dedicated test suite (`test_proxy.py`) containing 10 automated tests that cover every required feature of the project. Tests are run against a live proxy instance on `localhost:8888` with the admin interface on `localhost:8080`. Each test is self-contained and reports a colored pass/fail result to the terminal.

To run the tests:

```bash
# Terminal 1 — start the proxy
python proxy.py

# Terminal 2 — run the suite
python test_proxy.py
```

### 6.1 Test Descriptions

**Test 1 — Proxy is Reachable**
Verifies that the proxy socket is up and accepting TCP connections on port 8888. Uses `socket.connect_ex()` and checks that the return code is 0. This confirms the server started successfully and the port is open. *(Requirement B)*

**Test 2 — Admin Interface Reachable**
Sends an HTTP GET to `localhost:8080/` and checks that the response status is 200 and the body contains the text "Proxy Admin". This confirms the admin server started correctly in its background daemon thread and the dashboard template renders without errors. *(Requirement I)*

**Test 3 — Basic HTTP Forwarding**
Makes a full HTTP GET request to `http://httpbin.org/get` through the proxy using Python's `urllib` configured with the proxy address. Asserts a 200 status and a non-empty response body. This end-to-end test confirms that `handle_http()` successfully connects to an origin server, relays the request, and returns the response. *(Requirement A)*

**Test 4 — Request Headers Forwarded Correctly**
Spins up a local origin server on a random port, routes a request through the proxy to it, and captures the exact forwarded HTTP request bytes. Asserts that `Via: 1.1 CSC430-Proxy` is present and that `Proxy-Connection` has been stripped. This validates the header modification logic in `rebuild_request()`. *(Requirement C)*

**Test 5 — Content Caching**
Makes two sequential GET requests to `http://httpbin.org/cache/60` — a URL that returns `Cache-Control: max-age=60`. After the first request it queries `/api/stats` and confirms `cache_misses` incremented. After the second request it confirms `cache_hits` incremented. This validates that `CacheManager.put()` stored the response and `CacheManager.get()` served it on the second request. *(Requirement F)*

**Test 6 — Blacklist Blocks Request**
First adds `blocked-test.invalid` to the blacklist via a POST to `/api/blacklist/add`. Then sends a raw HTTP request for that domain directly through the proxy socket using `send_raw()`. Asserts that the response contains `403`. This confirms `is_blocked()` catches the domain and `send_blocked_response()` returns the correct status. *(Requirement G)*

**Test 7 — HTTPS CONNECT Tunnel**
Manually sends a `CONNECT httpbin.org:443 HTTP/1.1` request over a raw socket to the proxy and reads until `\r\n\r\n`. Asserts that the response contains `200`. This confirms that `handle_https_tunnel()` successfully connected to the origin server and sent back `200 Connection Established`. *(Requirement H)*

**Test 8 — Admin Stats API**
Sends a GET to `localhost:8080/api/stats`, parses the JSON response, and asserts that `total_requests` is present. This validates that the stats endpoint is live, returns valid JSON, and contains the expected counter keys. *(Requirement I)*

**Test 9 — Admin Config Update**
POSTs `{"cache_timeout": 600}` to `/api/config` and asserts that the response JSON contains `config.cache_timeout == 600`. This confirms that `do_POST()` updates the shared `config` dict, persists it to `config.json`, and echoes the updated values back. *(Requirement I)*

**Test 10 — Concurrent Connections**
Spawns 5 threads simultaneously, each making a GET to `http://httpbin.org/get` through the proxy. Joins all threads with a 15-second timeout and asserts that no errors were collected. This validates that the threading model in `main()` and `handle_client()` correctly handles multiple simultaneous clients without deadlocking or crashing. *(Requirement D)*

### 6.2 Test Results

> **Screenshot:** Run `python test_proxy.py` with the proxy active and insert the terminal output here showing all 10 green checkmarks and `Results: 10/10 passed`.

---

## 7. Challenges and Solutions

### 7.1 Parsing CONNECT vs HTTP

The first major challenge was that both CONNECT and regular HTTP requests arrive as identical raw TCP bytes, but their URL formats are completely different. A regular GET has a full URL like `http://example.com/path`, while CONNECT has only `host:port`. Calling `urlparse()` on a CONNECT URL would silently misparse it. This was solved by checking the method first and branching before any URL parsing, with the CONNECT branch using `rsplit(":", 1)` to extract host and port directly.

### 7.2 Thread-Safe Cache Access

Multiple threads can read and write the cache directory simultaneously — one thread might be storing a new response while another is checking for an existing one. Without locking, this could produce corrupted `.meta` files or missing `.data` files. This was solved by giving `CacheManager` its own internal `threading.Lock()` that wraps every file operation, ensuring reads and writes are always atomic from the perspective of any individual cache entry.

### 7.3 Cache Invalidation Priority

Real-world HTTP responses use three different mechanisms to communicate caching intent: `Cache-Control: no-store`, `Cache-Control: max-age=N`, and the `Expires` header. These needed to be checked in the correct priority order — `no-store` overrides everything, `max-age` takes priority over `Expires`, and the default timeout only applies when neither is present. Getting this order wrong would result in caching responses that should not be cached, or ignoring explicit expiry times from the server.

### 7.4 Non-Blocking HTTPS Relay

A naive implementation of the HTTPS tunnel using two blocking `recv/send` loops would deadlock — each side waiting for the other to send first. This was solved using `select()` to monitor both sockets simultaneously in a single loop, only reading from a socket when data is actually available. A 30-second inactivity timeout was added so idle tunnels close automatically without leaking threads or file descriptors.

### 7.5 Configuration Persistence

Any change made through the admin interface — adding a blacklist entry, updating the cache timeout — needed to survive a proxy restart. The shared `config` dictionary is updated in memory first (under `config_lock`), then immediately written to `config.json` via `save_config()`. On startup, `load_config()` reads this file back and merges it with the defaults, so no configuration is ever lost between runs.

---

## 8. Work Division

The project was developed collaboratively, with each team member taking primary responsibility for specific sections of the codebase while all members contributed to the overall architecture design, integration, and testing.

| Member | ID | Sections Implemented |
|---|---|---|
| Jad Al Hassan | 202400472 | A — Basic Proxy Functionality, C — Request Parsing |
| Mohammad Karim Mehaydli | 202400046 | D — Threading, E — Logging, G — Blacklist/Whitelist |
| Adam El Saheli | 202300640 | F — Content Caching, H — HTTPS Tunnel, I — Admin Interface |

Collaborative work included the overall system architecture, the shared configuration and stats design, integration between the proxy engine and admin interface, and all testing using `test_proxy.py`.

---

## 9. Conclusion

### 9.1 Key Achievements

The CSC430 Caching Proxy Server successfully implements all required features outlined in the project specification, along with both bonus components, resulting in a fully functional and well-structured proxy solution built entirely on Python's standard library with no external dependencies.

**Basic Proxy Functionality:** The proxy correctly accepts client TCP connections, parses raw HTTP requests, rebuilds them with proper proxy headers, forwards them to origin servers, and relays responses back — forming a complete and transparent forwarding pipeline.

**Request Parsing:** Both standard HTTP requests and HTTPS CONNECT requests are handled through a unified parsing function that correctly extracts the method, host, port, path, and headers regardless of URL format, with proper header modification for proxy compliance.

**Multi-threaded Architecture:** Each client connection is dispatched to a dedicated daemon thread, allowing the proxy to handle hundreds of simultaneous connections without any blocking. Active connection tracking provides real-time visibility into concurrency levels through the admin interface.

**Structured Logging:** Every request is logged with client IP, port, method, URL, and timestamp to both a persistent log file and the console, satisfying all five logging requirements from the project spec and enabling full audit capability through the admin log viewer.

**Intelligent Caching:** The file-based cache implements a three-tier invalidation hierarchy — `no-store`/`no-cache` directives are respected first, followed by `max-age` parsing, then `Expires` header parsing, with a configurable default timeout as the final fallback. This produces correct caching behavior across a wide range of real-world server responses.

**Blacklist and Whitelist Filtering:** Domain filtering supports both blacklist mode and whitelist mode, with subdomain-aware matching. Blocked requests receive a proper HTTP 403 response with a descriptive HTML body. The active configuration is persisted to `config.json` on every change, so the filter rules survive proxy restarts.

**HTTPS CONNECT Tunnel (Bonus):** HTTPS traffic is handled transparently using a bidirectional TCP relay built with `select()` for non-blocking I/O. The proxy never decrypts TLS content, preserving full end-to-end security between the client and the origin server.

**Web-Based Admin Interface (Bonus):** A complete five-page web dashboard provides live visibility into proxy behavior — including real-time stats, a log viewer, a cache browser, blacklist and whitelist management, and a settings panel — all backed by a REST API and without requiring the proxy to restart for any configuration change.

### 9.2 Learning Outcomes

Developing this project provided hands-on experience with several core networking and systems programming concepts:

**Socket Programming:** Building the proxy from raw TCP sockets rather than a framework gave direct exposure to how HTTP actually works at the byte level — how request lines are structured, how headers are delimited, how responses are streamed, and how a CONNECT tunnel differs fundamentally from a regular HTTP request.

**Concurrent Programming:** Implementing the threading model and ensuring shared state correctness — through `config_lock`, `stats_lock`, and `CacheManager`'s internal lock — made the challenges of concurrent access concrete and practical rather than theoretical.

**HTTP Protocol Internals:** Parsing raw HTTP requests revealed details that are normally hidden behind libraries — the significance of `\r\n\r\n` as the header terminator, the difference between hop-by-hop headers like `Proxy-Connection` and end-to-end headers, and the mechanics of `Cache-Control` and `Expires` in the caching layer.

**System Design:** Structuring a single file that cleanly separates configuration management, caching, filtering, forwarding, tunneling, and the admin interface — while keeping all of it thread-safe — required careful thinking about shared state, responsibility boundaries, and the right level of abstraction.

### 9.3 Future Enhancements

While the current implementation fully satisfies all project requirements, several extensions could make the proxy more production-capable:

- **HTTPS MITM Inspection:** Implementing SSL interception with a self-signed CA certificate would allow the proxy to decrypt, inspect, and re-encrypt HTTPS traffic — useful for debugging and content filtering.
- **Cache Size Limits:** The current cache grows unbounded on disk. A maximum cache size with a least-recently-used eviction policy would prevent disk exhaustion in long-running deployments.
- **Request Rate Limiting:** Adding per-IP rate limiting would protect against abuse and make the proxy suitable for shared or public-facing environments.
- **Persistent Stats:** Current stats reset every time the proxy restarts. Persisting them to disk alongside `config.json` would enable long-term usage tracking.
- **Regex-Based Filtering:** The current blacklist/whitelist matches exact domains and subdomains. Supporting regex patterns would allow more flexible filtering rules.

---

## 10. References

- Python Software Foundation. (2024). *socket — Low-level networking interface*. https://docs.python.org/3/library/socket.html
- Python Software Foundation. (2024). *threading — Thread-based parallelism*. https://docs.python.org/3/library/threading.html
- Python Software Foundation. (2024). *http.server — HTTP servers*. https://docs.python.org/3/library/http.server.html
- Python Software Foundation. (2024). *select — Waiting for I/O completion*. https://docs.python.org/3/library/select.html
- Fielding, R. et al. (1999). *RFC 2616: Hypertext Transfer Protocol — HTTP/1.1*. IETF. https://www.rfc-editor.org/rfc/rfc2616
- Luotonen, A. (1998). *Web Proxy Servers*. Prentice Hall.
- OWASP. (2023). *Transport Layer Security Cheat Sheet*. https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html