"""
CSC 430 - Computer Networks
Caching Proxy Server
Spring 2025-2026, Lebanese American University

Team Members:
  - Jad Al Hassan: Basic Proxy Functionality, Request Parsing (Sections A, C)
  - Mohammad Karim Mehaydli: Threading, Logging, Blacklist/Whitelist (Sections D, E, G)
  - Adam Saheli: Content Caching, HTTPS Proxy, Admin Interface (Sections F, H, I)

Description:
  A multi-threaded HTTP/HTTPS caching proxy server with logging, blacklist/whitelist
  filtering, and a web-based admin interface.
"""

import socket
import threading
import logging
import os
import json
import html
import mimetypes
import time
import hashlib
import ssl
import re
import select
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

PROXY_HOST = "0.0.0.0"
PROXY_PORT = 8888
ADMIN_PORT = 8080
BUFFER_SIZE = 4096
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "proxy.log")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_CACHE_TIMEOUT = 300  # seconds (5 minutes)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ─────────────────────────────────────────────
# SECTION E — LOGGING  (Mohammad Karim Mehaydli)
# Set up rotating log to file and console.
# ─────────────────────────────────────────────

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("ProxyServer")


# ─────────────────────────────────────────────
# CONFIG MANAGER — shared state for blacklist/whitelist/cache settings
# ─────────────────────────────────────────────

def load_config():
    """Load proxy configuration (blacklist, whitelist, cache timeout) from JSON."""
    defaults = {
        "blacklist": ["ads.example.com", "malware.example.com"],
        "whitelist": [],          # empty = allow all (except blacklist)
        "cache_timeout": DEFAULT_CACHE_TIMEOUT,
        "use_whitelist": False,   # if True, only whitelist domains are allowed
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            defaults.update(data)
    return defaults

def save_config(cfg):
    """Persist proxy configuration to JSON."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

config = load_config()
config_lock = threading.Lock()   # protect concurrent access to config


# ─────────────────────────────────────────────
# ADMIN TEMPLATE RENDERING
# ─────────────────────────────────────────────

def _read_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _replace_tokens(text, values):
    for key, value in values.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


def render_template(template_name, **context):
    template_path = TEMPLATES_DIR / template_name
    template_text = _read_text_file(template_path)
    return _replace_tokens(template_text, context)


def _asset_tags(file_names, folder, tag_name):
    tags = []
    for file_name in file_names:
        if tag_name == "link":
            tags.append(f'<link rel="stylesheet" href="/static/{folder}/{file_name}">')
        else:
            tags.append(f'<script defer src="/static/{folder}/{file_name}"></script>')
    return "\n  ".join(tags)


def render_admin_page(template_name, *, title, label, active_page, description="", css_files=None, js_files=None, **context):
    css_files = css_files or []
    js_files = js_files or []
    page_context = dict(context)
    page_context.setdefault("ERROR_TITLE", "")
    page_context.setdefault("ERROR_MESSAGE", "")
    content = render_template(template_name, **page_context)

    nav_state = {
        "ACTIVE_DASHBOARD": "active" if active_page == "dashboard" else "",
        "ACTIVE_LOGS": "active" if active_page == "logs" else "",
        "ACTIVE_CACHE": "active" if active_page == "cache" else "",
        "ACTIVE_RULES": "active" if active_page == "rules" else "",
        "ACTIVE_SETTINGS": "active" if active_page == "settings" else "",
    }

    return render_template(
        "base.html",
        PAGE_TITLE=html.escape(title),
        PAGE_LABEL=html.escape(label),
        PAGE_DESCRIPTION=html.escape(description or title),
        BODY_CLASS=f"page-{active_page}",
        EXTRA_CSS=_asset_tags(css_files, "css", "link"),
        EXTRA_JS=_asset_tags(js_files, "js", "script"),
        CONTENT=content,
        **nav_state,
    )


def render_error_page(status_code, title, message):
    return render_admin_page(
        "error.html",
        title=title,
        label="Proxy administration",
        active_page="dashboard",
        description=message,
        css_files=["error.css"],
        ERROR_TITLE=html.escape(title),
        ERROR_MESSAGE=html.escape(message),
    )


# ─────────────────────────────────────────────
# SECTION F — CONTENT CACHING  (Adam Saheli)
# Cache responses keyed by URL hash. Respects Cache-Control / Expires headers.
# ─────────────────────────────────────────────

class CacheManager:
    """
    File-based HTTP response cache.
    Each entry is stored as:
      <CACHE_DIR>/<url_hash>.data  — raw response bytes
      <CACHE_DIR>/<url_hash>.meta  — JSON metadata (url, expires, headers)
    """

    def __init__(self, cache_dir, default_timeout):
        self.cache_dir = cache_dir
        self.default_timeout = default_timeout
        self.lock = threading.Lock()

    def _key(self, url):
        """Return filesystem-safe key for a URL."""
        return hashlib.md5(url.encode()).hexdigest()

    def get(self, url):
        """
        Return cached response bytes if valid, else None.
        Checks Expires or cache timestamp against current time.
        """
        key = self._key(url)
        data_path = os.path.join(self.cache_dir, f"{key}.data")
        meta_path = os.path.join(self.cache_dir, f"{key}.meta")

        with self.lock:
            if not os.path.exists(data_path) or not os.path.exists(meta_path):
                return None
            with open(meta_path) as f:
                meta = json.load(f)
            # Check expiry
            expires = meta.get("expires", 0)
            if time.time() > expires:
                logger.info(f"[CACHE] Expired: {url}")
                os.remove(data_path)
                os.remove(meta_path)
                return None
            with open(data_path, "rb") as f:
                logger.info(f"[CACHE] HIT: {url}")
                return f.read()

    def put(self, url, response_bytes, response_headers):
        """
        Store response in cache. Parse Cache-Control / Expires headers
        to determine expiry; fall back to default_timeout.
        """
        key = self._key(url)
        data_path = os.path.join(self.cache_dir, f"{key}.data")
        meta_path = os.path.join(self.cache_dir, f"{key}.meta")

        # ── Cache invalidation rules based on response headers ──
        expires_ts = time.time() + self.default_timeout
        cache_control = response_headers.get("Cache-Control", "")
        expires_header = response_headers.get("Expires", "")

        if "no-store" in cache_control or "no-cache" in cache_control:
            logger.info(f"[CACHE] Not caching (no-store/no-cache): {url}")
            return  # respect server directive

        # max-age=N  →  expire in N seconds
        max_age_match = re.search(r"max-age=(\d+)", cache_control)
        if max_age_match:
            expires_ts = time.time() + int(max_age_match.group(1))
        elif expires_header:
            try:
                from email.utils import parsedate_to_datetime
                expires_dt = parsedate_to_datetime(expires_header)
                expires_ts = expires_dt.timestamp()
            except Exception:
                pass  # use default

        meta = {
            "url": url,
            "expires": expires_ts,
            "cached_at": time.time(),
            "headers": dict(response_headers),
        }

        with self.lock:
            with open(data_path, "wb") as f:
                f.write(response_bytes)
            with open(meta_path, "w") as f:
                json.dump(meta, f)
        logger.info(f"[CACHE] STORED: {url} (expires in {int(expires_ts - time.time())}s)")

    def list_entries(self):
        """Return list of cache metadata dicts for admin interface."""
        entries = []
        with self.lock:
            for fname in os.listdir(self.cache_dir):
                if fname.endswith(".meta"):
                    try:
                        with open(os.path.join(self.cache_dir, fname)) as f:
                            meta = json.load(f)
                            meta["expired"] = time.time() > meta.get("expires", 0)
                            meta["key"] = fname.replace(".meta", "")
                            entries.append(meta)
                    except Exception:
                        pass
        return entries

    def clear(self, key=None):
        """Clear all cache entries or a specific key."""
        with self.lock:
            if key:
                for ext in [".data", ".meta"]:
                    p = os.path.join(self.cache_dir, f"{key}{ext}")
                    if os.path.exists(p):
                        os.remove(p)
            else:
                for fname in os.listdir(self.cache_dir):
                    os.remove(os.path.join(self.cache_dir, fname))
        logger.info(f"[CACHE] Cleared {'key='+key if key else 'ALL'}")


cache_manager = CacheManager(CACHE_DIR, DEFAULT_CACHE_TIMEOUT)


# ─────────────────────────────────────────────
# STATS — in-memory counters for admin dashboard
# ─────────────────────────────────────────────

stats = {
    "total_requests": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "blocked_requests": 0,
    "active_connections": 0,
    "errors": 0,
    "start_time": datetime.now().isoformat(),
}
stats_lock = threading.Lock()

def inc_stat(key, amount=1):
    with stats_lock:
        stats[key] = stats.get(key, 0) + amount


# ─────────────────────────────────────────────
# SECTION C — REQUEST PARSING  (Jad Al Hassan)
# Extract host, port, method, path from raw HTTP request bytes.
# ─────────────────────────────────────────────

def parse_request(raw_request):
    """
    Parse a raw HTTP request to extract:
      - method (GET, POST, CONNECT, ...)
      - url / path
      - host and port
      - http_version
      - headers dict
      - body bytes
    Returns a dict or None on parse error.
    """
    try:
        # Split headers from body
        if b"\r\n\r\n" in raw_request:
            header_section, body = raw_request.split(b"\r\n\r\n", 1)
        else:
            header_section, body = raw_request, b""

        lines = header_section.decode("utf-8", errors="replace").split("\r\n")
        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            return None

        method = parts[0].upper()
        url = parts[1]
        http_version = parts[2] if len(parts) > 2 else "HTTP/1.1"

        # Parse headers into dict
        headers = {}
        for line in lines[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.strip()] = v.strip()

        # Extract host and port
        if method == "CONNECT":
            # HTTPS CONNECT: host:port
            host_port = url
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
                port = int(port)
            else:
                host, port = host_port, 443
            path = "/"
        else:
            parsed = urlparse(url)
            host = parsed.hostname or headers.get("Host", "").split(":")[0]
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query

        return {
            "method": method,
            "url": url,
            "path": path,
            "host": host,
            "port": int(port),
            "http_version": http_version,
            "headers": headers,
            "body": body,
        }
    except Exception as e:
        logger.error(f"[PARSE] Failed to parse request: {e}")
        return None


def rebuild_request(parsed):
    """
    Reconstruct a forwarded HTTP request from parsed components.
    Modifies headers for proper proxy forwarding:
      - Sets correct Host header
      - Strips Proxy-Connection (non-standard)
      - Adds Via header
    """
    method = parsed["method"]
    path = parsed["path"]
    http_version = parsed["http_version"]
    headers = dict(parsed["headers"])

    # ── Header modifications for proxy forwarding ──
    headers["Host"] = f"{parsed['host']}:{parsed['port']}" if parsed['port'] not in (80, 443) else parsed['host']
    headers.pop("Proxy-Connection", None)         # strip proxy-specific header
    headers.pop("Proxy-Authorization", None)
    headers["Via"] = "1.1 CSC430-Proxy"           # identify proxy in chain
    headers["Connection"] = "close"               # non-persistent for simplicity

    request_line = f"{method} {path} {http_version}\r\n"
    header_lines = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    rebuilt = (request_line + header_lines + "\r\n").encode()
    if parsed["body"]:
        rebuilt += parsed["body"]
    return rebuilt


# ─────────────────────────────────────────────
# SECTION G — BLACKLIST / WHITELIST  (Mohammad Karim Mehaydli)
# ─────────────────────────────────────────────

def is_blocked(host):
    """
    Return True if the host should be blocked.
    Logic:
      1. If whitelist mode is on, block anything NOT in whitelist.
      2. Block anything in blacklist.
    """
    with config_lock:
        cfg = dict(config)

    host_lower = host.lower()

    # Whitelist check
    if cfg.get("use_whitelist") and cfg.get("whitelist"):
        allowed = any(host_lower == w.lower() or host_lower.endswith("." + w.lower())
                      for w in cfg["whitelist"])
        if not allowed:
            logger.warning(f"[FILTER] Blocked (not in whitelist): {host}")
            return True

    # Blacklist check
    for bl in cfg.get("blacklist", []):
        if host_lower == bl.lower() or host_lower.endswith("." + bl.lower()):
            logger.warning(f"[FILTER] Blocked (blacklist): {host}")
            return True

    return False


def send_blocked_response(client_socket, host):
    """Send a custom 403 response when a request is blocked."""
    body = (
        f"<html><body><h1>403 Forbidden</h1>"
        f"<p>Access to <b>{host}</b> has been blocked by the proxy.</p>"
        f"</body></html>"
    ).encode()
    response = (
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Content-Type: text/html\r\n"
        b"Connection: close\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    try:
        client_socket.sendall(response)
    except Exception:
        pass


# ─────────────────────────────────────────────
# SECTION A — BASIC PROXY FUNCTIONALITY  (Jad Al Hassan)
# Forward HTTP requests; relay responses back to client.
# ─────────────────────────────────────────────

def handle_http(client_socket, parsed, client_addr, raw_request):
    """
    Handle a plain HTTP request:
      1. Check cache → serve if hit.
      2. Check blacklist → block if matched.
      3. Forward to target server.
      4. Relay response back to client and cache it.
    """
    url = parsed["url"]
    host = parsed["host"]
    port = parsed["port"]
    method = parsed["method"]

    inc_stat("total_requests")

    logger.info(
        f"[HTTP] {client_addr[0]}:{client_addr[1]} -> {method} {url}"
    )

    # ── Blacklist check ──
    if is_blocked(host):
        inc_stat("blocked_requests")
        send_blocked_response(client_socket, host)
        return

    # ── Cache lookup (GET only) ──
    cache_key = url
    if method == "GET":
        cached = cache_manager.get(cache_key)
        if cached:
            inc_stat("cache_hits")
            logger.info(f"[HTTP] Cache HIT for {url}")
            try:
                client_socket.sendall(cached)
            except Exception as e:
                logger.error(f"[HTTP] Error sending cached response: {e}")
            return
        inc_stat("cache_misses")

    # ── Forward to target server ──
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.settimeout(10)
        server_socket.connect((host, port))

        forwarded_request = rebuild_request(parsed)
        server_socket.sendall(forwarded_request)

        # Collect full response
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

        # Relay response to client
        client_socket.sendall(response_data)

        # ── Cache the response (GET only) ──
        if method == "GET" and response_data:
            resp_headers = parse_response_headers(response_data)
            cache_manager.put(cache_key, response_data, resp_headers)

        logger.info(
            f"[HTTP] {client_addr[0]}:{client_addr[1]} <- {len(response_data)} bytes from {host}"
        )

    except Exception as e:
        inc_stat("errors")
        logger.error(f"[HTTP] Error forwarding to {host}:{port} — {e}")
        error_response = (
            b"HTTP/1.1 502 Bad Gateway\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n\r\n"
            b"502 Bad Gateway: Proxy could not reach the target server.\r\n"
        )
        try:
            client_socket.sendall(error_response)
        except Exception:
            pass


def parse_response_headers(raw_response):
    """Extract response headers as a dict from raw HTTP response bytes."""
    headers = {}
    try:
        header_section = raw_response.split(b"\r\n\r\n", 1)[0]
        lines = header_section.decode("utf-8", errors="replace").split("\r\n")
        for line in lines[1:]:  # skip status line
            if ": " in line:
                k, v = line.split(": ", 1)
                headers[k.strip()] = v.strip()
    except Exception:
        pass
    return headers


# ─────────────────────────────────────────────
# SECTION H — HTTPS PROXY  (Adam Saheli)
# CONNECT tunnel: relay encrypted bytes without decryption.
# ─────────────────────────────────────────────

def handle_https_tunnel(client_socket, parsed, client_addr):
    """
    Handle HTTPS CONNECT requests by setting up a transparent TCP tunnel.
    The proxy does NOT decrypt SSL — it simply relays bytes bidirectionally.
    This preserves end-to-end encryption between client and server.

    Flow:
      Client → CONNECT host:443 → Proxy
      Proxy  → TCP connect to host:443
      Proxy  → 200 Connection Established → Client
      Client ↔ Proxy ↔ Server  (raw TLS bytes)
    """
    host = parsed["host"]
    port = parsed["port"]

    inc_stat("total_requests")
    logger.info(f"[HTTPS] CONNECT tunnel: {client_addr[0]}:{client_addr[1]} -> {host}:{port}")

    if is_blocked(host):
        inc_stat("blocked_requests")
        send_blocked_response(client_socket, host)
        return

    try:
        # Connect to target server
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.settimeout(10)
        server_socket.connect((host, port))

        # Notify client that tunnel is ready
        client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

        # ── Bidirectional relay using select ──
        client_socket.setblocking(False)
        server_socket.setblocking(False)

        sockets = [client_socket, server_socket]
        timeout = 30  # seconds of inactivity before closing tunnel
        total_bytes = 0

        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, timeout)
            if exceptional or not readable:
                break  # timeout or error

            for sock in readable:
                try:
                    data = sock.recv(BUFFER_SIZE)
                    if not data:
                        raise ConnectionResetError("Connection closed")
                    total_bytes += len(data)
                    # Route to the other end
                    other = server_socket if sock is client_socket else client_socket
                    other.sendall(data)
                except Exception:
                    readable = []  # stop loop
                    break

            if not readable:
                break

        server_socket.close()
        logger.info(f"[HTTPS] Tunnel closed: {host}:{port} ({total_bytes} bytes relayed)")

    except Exception as e:
        inc_stat("errors")
        logger.error(f"[HTTPS] Tunnel error for {host}:{port} — {e}")


# ─────────────────────────────────────────────
# SECTION D — THREADING  (Mohammad Karim Mehaydli)
# One thread per client connection for concurrent handling.
# ─────────────────────────────────────────────

def handle_client(client_socket, client_addr):
    """
    Entry point for each client thread.
    Reads the initial request, parses it, and dispatches to
    HTTP or HTTPS handler based on the method.
    """
    inc_stat("active_connections")
    try:
        # Read initial request data
        raw_request = b""
        client_socket.settimeout(5)
        try:
            while True:
                chunk = client_socket.recv(BUFFER_SIZE)
                if not chunk:
                    break
                raw_request += chunk
                # Stop reading at end of headers
                if b"\r\n\r\n" in raw_request:
                    break
        except socket.timeout:
            pass

        if not raw_request:
            return

        parsed = parse_request(raw_request)
        if not parsed:
            logger.warning(f"[CLIENT] Could not parse request from {client_addr}")
            return

        # Log request details (Section E requirement)
        logger.info(
            f"[REQUEST] IP={client_addr[0]} Port={client_addr[1]} "
            f"Method={parsed['method']} URL={parsed['url']} "
            f"Time={datetime.now().isoformat()}"
        )

        if parsed["method"] == "CONNECT":
            handle_https_tunnel(client_socket, parsed, client_addr)
        else:
            handle_http(client_socket, parsed, client_addr, raw_request)

    except Exception as e:
        inc_stat("errors")
        logger.error(f"[CLIENT] Unhandled error for {client_addr}: {e}")
    finally:
        inc_stat("active_connections", -1)
        try:
            client_socket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────
# SECTION I — ADMIN INTERFACE  (Adam Saheli)
# Web-based interface on ADMIN_PORT for stats, logs, cache, and config.
# ─────────────────────────────────────────────

class AdminHandler(BaseHTTPRequestHandler):
    """HTTP handler for the proxy admin web interface."""

    def log_message(self, format, *args):
        pass  # suppress default access logs

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _send_html(self, html, status=200):
        body = html.encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _send_file(self, file_path):
        if not file_path.exists() or not file_path.is_file():
            self._send_html(render_error_page(404, "Not Found", "The requested asset could not be found."), 404)
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or "application/octet-stream"

        with open(file_path, "rb") as f:
            body = f.read()

        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _read_log_tail(self, n=200):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as log_file:
                lines = log_file.readlines()
            return [line.rstrip() for line in lines[-n:]]
        except Exception:
            return []

    def _serve_static(self, request_path):
        relative_path = request_path[len("/static/"):]
        candidate = (STATIC_DIR / relative_path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._send_html(render_error_page(404, "Not Found", "The requested asset could not be found."), 404)
            return
        self._send_file(candidate)

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ("/", "/admin", "/dashboard"):
            self._send_html(
                render_admin_page(
                    "dashboard.html",
                    title="CSC430 Proxy Admin | Dashboard",
                    label="Proxy observability",
                    active_page="dashboard",
                    description="Live proxy dashboard for traffic, cache, and filtering status.",
                    css_files=["dashboard.css"],
                    js_files=["dashboard.js"],
                )
            )

        elif path == "/logs":
            self._send_html(
                render_admin_page(
                    "logs.html",
                    title="CSC430 Proxy Admin | Logs",
                    label="Request logging",
                    active_page="logs",
                    description="Readable log viewer for proxy activity.",
                    css_files=["logs.css"],
                    js_files=["logs.js"],
                )
            )

        elif path == "/cache":
            self._send_html(
                render_admin_page(
                    "cache.html",
                    title="CSC430 Proxy Admin | Cache",
                    label="Cache management",
                    active_page="cache",
                    description="Inspect cached responses and their expiry state.",
                    css_files=["cache.css"],
                    js_files=["cache.js"],
                )
            )

        elif path == "/rules":
            self._send_html(
                render_admin_page(
                    "rules.html",
                    title="CSC430 Proxy Admin | Rules",
                    label="Filtering controls",
                    active_page="rules",
                    description="Manage blacklist and whitelist domains.",
                    css_files=["rules.css"],
                    js_files=["rules.js"],
                )
            )

        elif path == "/settings":
            self._send_html(
                render_admin_page(
                    "settings.html",
                    title="CSC430 Proxy Admin | Settings",
                    label="Configuration",
                    active_page="settings",
                    description="Adjust proxy defaults and whitelist mode.",
                    css_files=["settings.css"],
                    js_files=["settings.js"],
                )
            )

        elif path.startswith("/static/"):
            self._serve_static(path)

        elif path == "/api/stats":
            with stats_lock:
                self._send_json(dict(stats))

        elif path == "/api/cache":
            self._send_json(cache_manager.list_entries())

        elif path == "/api/config":
            with config_lock:
                self._send_json(dict(config))

        elif path == "/api/logs":
            lines = self._read_log_tail(200)
            self._send_json({"lines": lines})

        elif path == "/api/cache/clear":
            cache_manager.clear()
            self._send_json({"status": "cache cleared"})

        else:
            self._send_html(
                render_error_page(
                    404,
                    "Page not found",
                    "The requested admin page does not exist.",
                ),
                404,
            )

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        path = self.path

        if path == "/api/config":
            with config_lock:
                config.update(data)
                save_config(config)
            self._send_json({"status": "config updated", "config": config})

        elif path == "/api/blacklist/add":
            domain = data.get("domain", "").strip()
            if domain:
                with config_lock:
                    if domain not in config["blacklist"]:
                        config["blacklist"].append(domain)
                    save_config(config)
                self._send_json({"status": f"added {domain} to blacklist"})
            else:
                self._send_json({"error": "domain required"}, 400)

        elif path == "/api/blacklist/remove":
            domain = data.get("domain", "").strip()
            with config_lock:
                if domain in config["blacklist"]:
                    config["blacklist"].remove(domain)
                save_config(config)
            self._send_json({"status": f"removed {domain} from blacklist"})

        elif path == "/api/whitelist/add":
            domain = data.get("domain", "").strip()
            if domain:
                with config_lock:
                    if domain not in config["whitelist"]:
                        config["whitelist"].append(domain)
                    save_config(config)
                self._send_json({"status": f"added {domain} to whitelist"})
            else:
                self._send_json({"error": "domain required"}, 400)

        elif path == "/api/whitelist/remove":
            domain = data.get("domain", "").strip()
            with config_lock:
                if domain in config["whitelist"]:
                    config["whitelist"].remove(domain)
                save_config(config)
            self._send_json({"status": f"removed {domain} from whitelist"})

        else:
            self._send_json({"error": "unknown endpoint"}, 404)


def start_admin_server():
    """Start admin HTTP server in a daemon thread."""
    server = HTTPServer((PROXY_HOST, ADMIN_PORT), AdminHandler)
    logger.info(f"[ADMIN] Admin interface running on http://localhost:{ADMIN_PORT}")
    server.serve_forever()


# ─────────────────────────────────────────────
# MAIN — Start proxy + admin servers
# ─────────────────────────────────────────────

def main():
    # Start admin interface in background thread
    admin_thread = threading.Thread(target=start_admin_server, daemon=True)
    admin_thread.start()

    # Create proxy listening socket
    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy_socket.bind((PROXY_HOST, PROXY_PORT))
    proxy_socket.listen(100)

    logger.info(f"[PROXY] CSC430 Caching Proxy listening on {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"[PROXY] Admin interface at http://localhost:{ADMIN_PORT}")

    try:
        while True:
            try:
                client_socket, client_addr = proxy_socket.accept()
                # Spawn a new thread for each client (Section D)
                t = threading.Thread(
                    target=handle_client,
                    args=(client_socket, client_addr),
                    daemon=True,
                )
                t.start()
                logger.debug(f"[PROXY] New connection from {client_addr[0]}:{client_addr[1]}")
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"[PROXY] Accept error: {e}")
    finally:
        proxy_socket.close()
        logger.info("[PROXY] Server shut down.")


if __name__ == "__main__":
    main()
