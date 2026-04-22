# CSC 430 – Caching Proxy Server

**Lebanese American University | Department of Computer Science and Mathematics**  
Spring 2025-2026

---

## Overview

A multi-threaded HTTP/HTTPS caching proxy server written in Python.  
It forwards client requests to target servers, caches responses, filters URLs,
and exposes a live web-based admin interface.

---

## Team Members & Contributions

| Member   | Sections Implemented                                      |
|----------|----------------------------------------------------------|
| Member 1 | A (Basic Proxy), C (Request Parsing)                     |
| Member 2 | D (Threading), E (Logging), G (Blacklist/Whitelist)      |
| Member 3 | F (Caching), H (HTTPS Tunnel), I (Admin Interface)       |

---

## Requirements

- Python 3.8+
- No external libraries required (uses only the standard library)

---

## Quick Start

```bash
# 1. Clone / unzip the project
cd proxy_project

# 2. Run the proxy
python proxy.py

# 3. Open the admin interface
#    → http://localhost:8080

# 4. Configure your browser to use the proxy
#    → HTTP Proxy: 127.0.0.1  Port: 8888
```

---

## Features

### A – Basic HTTP Proxy
Accepts client requests and forwards them to the target server using raw TCP
sockets. Relays the response back to the client.

### B – Socket Programming
Uses `socket.socket(AF_INET, SOCK_STREAM)` for all TCP connections.
The proxy listens on port **8888** by default. Each client gets a dedicated
server-side socket connection.

### C – Request Parsing
Parses the raw HTTP request line and headers to extract:
- Method (GET, POST, CONNECT, …)
- Target host and port
- Path and query string
- All headers

For proxy forwarding, the `Host` header is corrected, `Proxy-Connection` is
stripped, and a `Via: 1.1 CSC430-Proxy` header is added.

### D – Threading
Each incoming client connection is dispatched to a new `threading.Thread`.
This allows hundreds of simultaneous connections without blocking.

### E – Logging
All activity is logged to `logs/proxy.log` and to stdout:
- Client IP and port
- Target host and port
- HTTP method and URL
- Timestamp of request and response
- Byte counts
- Error messages

### F – Content Caching
- GET responses are cached to `cache/` as `.data` + `.meta` file pairs.
- Cache key = MD5 hash of the URL.
- **Cache invalidation** respects `Cache-Control: max-age=N`, `Cache-Control: no-store`,
  `Cache-Control: no-cache`, and `Expires` headers.
- Falls back to a configurable `cache_timeout` (default: 300 seconds).
- Admin interface shows all cache entries with their expiry time.

### G – Blacklist / Whitelist
- **Blacklist**: domains in this list always get a `403 Forbidden` response.
- **Whitelist** (optional): when enabled, only listed domains are allowed.
- Both lists can be managed live from the admin interface without restarting.
- Configuration is persisted to `config.json`.

### H – HTTPS Proxy (Tunnel) ⭐ Bonus
Handles `CONNECT` requests by establishing a raw TCP tunnel to the target server
(e.g., port 443). The proxy relays encrypted TLS bytes bidirectionally using
`select()` without decrypting the traffic. This preserves end-to-end security.

> For MITM/inspection (full SSL interception), see the comments in `proxy.py`
> Section H — requires a self-signed CA cert and is for educational use only.

### I – Admin Interface ⭐ Bonus
A web dashboard at **http://localhost:8080** provides:
- **Live stats**: total requests, cache hits/misses, blocked requests, errors, active connections
- **Log viewer**: last 200 log lines, auto-refreshed every 5 seconds
- **Cache manager**: view all entries (URL, expiry, status), clear all cache
- **Filter manager**: add/remove blacklist and whitelist entries in real time, toggle whitelist mode

The admin UI is split into separate templates and static assets for cleaner maintenance:
- `/` or `/dashboard` - overview dashboard
- `/logs` - log viewer
- `/cache` - cache manager
- `/rules` - blacklist/whitelist management
- `/settings` - configuration panel

---

## Configuration

`config.json` is auto-created on first run:

```json
{
  "blacklist": ["ads.example.com"],
  "whitelist": [],
  "cache_timeout": 300,
  "use_whitelist": false
}
```

Edit manually or use the admin interface.

---

## Testing

```bash
# Make sure proxy is running first
python proxy.py &

# Run the test suite
python test_proxy.py
```

Tests cover: connectivity, HTTP forwarding, header modification, caching,
blacklist blocking, HTTPS tunnel, admin API, and concurrent connections.

---

## File Structure

```
proxy_project/
├── proxy.py          ← Main proxy server (all sections)
├── test_proxy.py     ← Test suite
├── config.json       ← Auto-generated configuration
├── cache/            ← Cached responses (auto-created)
└── logs/
    └── proxy.log     ← Request/response log (auto-created)
├── templates/        ← HTML templates for the admin UI
│   ├── base.html
│   ├── dashboard.html
│   ├── logs.html
│   ├── cache.html
│   ├── rules.html
│   ├── settings.html
│   └── error.html
└── static/
  ├── css/
  │   ├── base.css
  │   ├── dashboard.css
  │   ├── logs.css
  │   ├── cache.css
  │   ├── rules.css
  │   ├── settings.css
  │   └── error.css
  └── js/
    ├── common.js
    ├── dashboard.js
    ├── logs.js
    ├── cache.js
    ├── rules.js
    └── settings.js
```

---

## Notes

- Tested with Python 3.10 on Ubuntu/macOS/Windows.
- The proxy does **not** modify HTTPS content — it tunnels it transparently.
- For browser configuration: set HTTP and HTTPS proxy to `127.0.0.1:8888`.
- Firefox: Settings → Network → Manual proxy → HTTP Proxy: 127.0.0.1, Port: 8888.
