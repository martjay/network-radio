"""Proxy support.

Many international stations are unreachable without a proxy, so proxy handling
is a first-class part of the transport rather than an afterthought. The module
provides:

  * system proxy detection (environment variables, then the platform store),
  * a normalised `ProxyConfig` covering HTTP CONNECT and SOCKS5,
  * `open_tunnel()`, which returns a connected socket through the proxy,
  * `ProxiedHTTPConnection` / `ProxiedHTTPSConnection` for http.client.

SOCKS5 is implemented here directly so the application has no extra runtime
dependency; PySocks is used only if it happens to be installed.
"""
from __future__ import annotations

import base64
import os
import re
import socket
import ssl
import struct
import sys

MODE_SYSTEM = "system"
MODE_NONE = "none"
MODE_CUSTOM = "custom"

SCHEME_HTTP = "http"
SCHEME_SOCKS5 = "socks5"

MODE_LABELS = [
    (MODE_SYSTEM, "自动（使用系统代理）"),
    (MODE_NONE, "不使用代理"),
    (MODE_CUSTOM, "自定义代理"),
]
SCHEME_LABELS = [
    (SCHEME_HTTP, "HTTP / HTTPS"),
    (SCHEME_SOCKS5, "SOCKS5"),
]

# Hosts that must never be proxied: the audio engine talks to our own loopback
# relay, and routing that through a proxy would break playback.
BYPASS_PATTERNS = (
    "localhost", "127.0.0.1", "127.0.0.0/8", "::1", "0.0.0.0",
)


def _is_bypassed(host: str, extra: list[str] | None = None) -> bool:
    if not host:
        return True
    low = host.lower().strip("[]")
    if low in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return True
    if low.startswith("127."):
        return True
    for pat in (extra or []):
        p = pat.lower().strip().strip("*")
        if not p:
            continue
        if p.startswith("."):
            if low.endswith(p):
                return True
        elif low == p or low.endswith("." + p):
            return True
    return False


class ProxyConfig:
    """A resolved proxy setting."""

    def __init__(
        self,
        mode: str = MODE_SYSTEM,
        scheme: str = SCHEME_HTTP,
        host: str = "",
        port: int = 0,
        username: str = "",
        password: str = "",
        bypass: list[str] | None = None,
        source: str = "",
    ):
        self.mode = mode
        self.scheme = scheme if scheme in (SCHEME_HTTP, SCHEME_SOCKS5) else SCHEME_HTTP
        self.host = host
        self.port = int(port or 0)
        self.username = username
        self.password = password
        self.bypass = list(bypass or [])
        self.source = source          # where an automatic setting came from
        self.unresolved = ""          # non-empty when auto detection failed

    # -- state -------------------------------------------------------------
    @property
    def usable(self) -> bool:
        """True when this config can actually carry traffic."""
        return self.mode != MODE_NONE and bool(self.host) and self.port > 0

    def should_proxy(self, host: str) -> bool:
        if not self.usable:
            return False
        return not _is_bypassed(host, self.bypass)

    def route_key(self) -> tuple:
        """Identity of the actual traffic path (direct vs host:port)."""
        if not self.usable:
            return (self.mode, "", 0, "")
        return (self.mode, self.scheme, self.host, int(self.port or 0))

    # -- presentation ------------------------------------------------------
    def describe(self) -> str:
        if self.mode == MODE_NONE:
            return "不使用代理"
        if self.mode == MODE_SYSTEM and not self.usable:
            return self.unresolved or "未检测到系统代理"
        if not self.usable:
            return "未配置"
        auth = f"{self.username}@" if self.username else ""
        return f"{self.scheme.upper()} {auth}{self.host}:{self.port}"

    def endpoint(self) -> str:
        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password}@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    def copy(self) -> "ProxyConfig":
        return ProxyConfig(
            self.mode, self.scheme, self.host, self.port,
            self.username, self.password, list(self.bypass), self.source,
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "scheme": self.scheme, "host": self.host,
            "port": self.port, "username": self.username,
            "password": self.password,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProxyConfig":
        if not data:
            return cls(MODE_SYSTEM)
        return cls(
            mode=data.get("mode", MODE_SYSTEM),
            scheme=data.get("scheme", SCHEME_HTTP),
            host=data.get("host", ""),
            port=data.get("port", 0),
            username=data.get("username", ""),
            password=data.get("password", ""),
        )


# --------------------------------------------------------------------------- #
#  parsing
# --------------------------------------------------------------------------- #
_URL_RE = re.compile(
    r"^(?:(?P<scheme>[a-z0-9]+)://)?"
    r"(?:(?P<user>[^:@/]+)(?::(?P<pw>[^@/]*))?@)?"
    r"(?P<host>\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?::(?P<port>\d{1,5}))?/?$",
    re.I,
)


def parse_proxy(text: str, scheme: str = "") -> ProxyConfig | None:
    """Parse `host:port`, `http://user:pass@host:port` or `socks5://host:port`."""
    raw = (text or "").strip()
    if not raw or len(raw) > 512:
        return None
    m = _URL_RE.match(raw)
    if not m:
        return None
    host = (m.group("host") or "").strip("[]")
    if not host:
        return None
    # reject anything that cannot be a hostname or address
    if any(ch.isspace() for ch in host) or host.startswith(".") or ".." in host:
        return None
    scheme_name = (m.group("scheme") or scheme or SCHEME_HTTP).lower()
    if scheme_name in ("https", "http"):
        scheme_name = SCHEME_HTTP
    elif scheme_name in ("socks", "socks5", "socks5h"):
        scheme_name = SCHEME_SOCKS5
    else:
        scheme_name = SCHEME_HTTP
    port = m.group("port")
    if not port:
        port = "1080" if scheme_name == SCHEME_SOCKS5 else "8080"
    try:
        port_i = int(port)
    except ValueError:
        return None
    if not (0 < port_i < 65536):
        return None
    return ProxyConfig(
        mode=MODE_CUSTOM,
        scheme=scheme_name,
        host=host,
        port=port_i,
        username=m.group("user") or "",
        password=m.group("pw") or "",
    )


# --------------------------------------------------------------------------- #
#  system detection
# --------------------------------------------------------------------------- #
def _from_env() -> ProxyConfig | None:
    for key in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy",
                "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(key, "").strip()
        if not value:
            continue
        cfg = parse_proxy(value)
        if cfg is None:
            continue
        cfg.mode = MODE_SYSTEM
        cfg.source = f"环境变量 {key}"
        bypass = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
        cfg.bypass = [p.strip() for p in bypass.split(",") if p.strip()]
        return cfg
    return None


def _from_windows() -> ProxyConfig | None:
    try:
        import winreg
    except ImportError:
        return None
    try:
        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            def get(name):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except OSError:
                    return None

            pac = get("AutoConfigURL")
            enabled = get("ProxyEnable")
            server = get("ProxyServer") or ""
            override = get("ProxyOverride") or ""

        bypass = [p.strip() for p in override.split(";") if p.strip() and p.strip() != "<local>"]

        if enabled and server:
            # ProxyServer may be "host:port" or "http=h:p;https=h:p;socks=h:p"
            chosen = ""
            scheme = SCHEME_HTTP
            if "=" in server:
                parts = {}
                for chunk in server.split(";"):
                    if "=" in chunk:
                        k, v = chunk.split("=", 1)
                        parts[k.strip().lower()] = v.strip()
                for pref in ("https", "http"):
                    if parts.get(pref):
                        chosen = parts[pref]
                        break
                if not chosen and parts.get("socks"):
                    chosen = parts["socks"]
                    scheme = SCHEME_SOCKS5
            else:
                chosen = server.strip()

            cfg = parse_proxy(chosen, scheme)
            if cfg is not None:
                cfg.mode = MODE_SYSTEM
                cfg.source = "Windows 系统代理"
                cfg.bypass = bypass
                return cfg

        if pac:
            cfg = ProxyConfig(MODE_SYSTEM)
            cfg.source = "PAC"
            cfg.unresolved = f"系统使用 PAC 自动配置脚本，无法自动解析（{pac[:60]}）"
            return cfg
    except OSError:
        return None
    return None


def _from_macos() -> ProxyConfig | None:
    import subprocess

    try:
        out = subprocess.run(
            ["scutil", "--proxy"], capture_output=True, timeout=5, text=True
        ).stdout
    except Exception:  # noqa: BLE001
        return None

    def field(name: str) -> str:
        m = re.search(rf"{name}\s*:\s*(\S+)", out)
        return m.group(1) if m else ""

    for enable, host_f, port_f, scheme in (
        ("HTTPSEnable", "HTTPSProxy", "HTTPSPort", SCHEME_HTTP),
        ("HTTPEnable", "HTTPProxy", "HTTPPort", SCHEME_HTTP),
        ("SOCKSEnable", "SOCKSProxy", "SOCKSPort", SCHEME_SOCKS5),
    ):
        if field(enable) == "1":
            host, port = field(host_f), field(port_f)
            if host and port:
                cfg = ProxyConfig(MODE_SYSTEM, scheme, host, int(port))
                cfg.source = "macOS 系统代理"
                return cfg
    return None


def _from_linux() -> ProxyConfig | None:
    import subprocess

    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.system.proxy", "mode"],
            capture_output=True, timeout=4, text=True,
        ).stdout.strip().strip("'")
    except Exception:  # noqa: BLE001
        return None
    if out != "manual":
        return None
    for schema, scheme in (("http", SCHEME_HTTP), ("socks", SCHEME_SOCKS5)):
        try:
            host = subprocess.run(
                ["gsettings", "get", f"org.gnome.system.proxy.{schema}", "host"],
                capture_output=True, timeout=4, text=True,
            ).stdout.strip().strip("'")
            port = subprocess.run(
                ["gsettings", "get", f"org.gnome.system.proxy.{schema}", "port"],
                capture_output=True, timeout=4, text=True,
            ).stdout.strip().strip("'")
        except Exception:  # noqa: BLE001
            continue
        if host and port.isdigit():
            cfg = ProxyConfig(MODE_SYSTEM, scheme, host, int(port))
            cfg.source = "GNOME 系统代理"
            return cfg
    return None


def system_proxy() -> ProxyConfig:
    """Resolve the operating system's proxy configuration."""
    cfg = _from_env()
    if cfg is not None:
        return cfg
    if os.name == "nt":
        cfg = _from_windows()
    elif sys.platform == "darwin":
        cfg = _from_macos()
    else:
        cfg = _from_linux()
    return cfg or ProxyConfig(MODE_SYSTEM)


# --------------------------------------------------------------------------- #
#  tunnelling
# --------------------------------------------------------------------------- #
class ProxyError(Exception):
    """Raised when the proxy refuses or fails to establish a tunnel."""


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProxyError("proxy closed the connection")
        buf += chunk
    return bytes(buf)


def _http_connect(sock: socket.socket, host: str, port: int, cfg: ProxyConfig) -> None:
    lines = [
        f"CONNECT {host}:{port} HTTP/1.1",
        f"Host: {host}:{port}",
        "Proxy-Connection: Keep-Alive",
        "User-Agent: BroadcastRadio/1.0",
    ]
    if cfg.username:
        token = base64.b64encode(
            f"{cfg.username}:{cfg.password}".encode("utf-8")
        ).decode("ascii")
        lines.append(f"Proxy-Authorization: Basic {token}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    sock.sendall(request)

    # Read just the response head.
    head = bytearray()
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(1)
        if not chunk:
            raise ProxyError("proxy closed the connection during CONNECT")
        head += chunk
        if len(head) > 16384:
            raise ProxyError("proxy response header too large")

    status_line = bytes(head).split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = status_line.split(" ", 2)
    code = parts[1] if len(parts) > 1 else ""
    if code != "200":
        raise ProxyError(f"proxy refused CONNECT ({status_line.strip()})")


def _socks5_connect(sock: socket.socket, host: str, port: int, cfg: ProxyConfig) -> None:
    # 1. greeting
    if cfg.username:
        sock.sendall(b"\x05\x02\x00\x02")
    else:
        sock.sendall(b"\x05\x01\x00")
    reply = _read_exact(sock, 2)
    if reply[0] != 0x05:
        raise ProxyError("not a SOCKS5 proxy")
    method = reply[1]
    if method == 0x02:
        user = cfg.username.encode("utf-8")[:255]
        pw = cfg.password.encode("utf-8")[:255]
        sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pw)]) + pw)
        auth = _read_exact(sock, 2)
        if auth[1] != 0x00:
            raise ProxyError("SOCKS5 authentication failed")
    elif method == 0xFF:
        raise ProxyError("SOCKS5 proxy accepted no authentication method")
    elif method != 0x00:
        raise ProxyError(f"unsupported SOCKS5 auth method 0x{method:02x}")

    # 2. connect request (resolve names locally)
    try:
        addr = socket.inet_aton(host)
        payload = b"\x01" + addr
    except OSError:
        name = host.encode("idna") if host.isascii() else host.encode("utf-8")
        if len(name) > 255:
            raise ProxyError("hostname too long for SOCKS5") from None
        payload = b"\x03" + bytes([len(name)]) + name
    sock.sendall(b"\x05\x01\x00" + payload + struct.pack("!H", port))

    reply = _read_exact(sock, 4)
    if reply[0] != 0x05:
        raise ProxyError("malformed SOCKS5 reply")
    if reply[1] != 0x00:
        reasons = {
            1: "general failure", 2: "connection not allowed", 3: "network unreachable",
            4: "host unreachable", 5: "connection refused", 6: "TTL expired",
            7: "command not supported", 8: "address type not supported",
        }
        raise ProxyError(f"SOCKS5: {reasons.get(reply[1], f'error {reply[1]}')}")

    atyp = reply[3]
    if atyp == 0x01:
        _read_exact(sock, 4 + 2)
    elif atyp == 0x03:
        length = _read_exact(sock, 1)[0]
        _read_exact(sock, length + 2)
    elif atyp == 0x04:
        _read_exact(sock, 16 + 2)
    else:
        raise ProxyError("malformed SOCKS5 address in reply")


def open_tunnel(
    host: str,
    port: int,
    timeout: float,
    cfg: ProxyConfig | None = None,
) -> socket.socket:
    """Return a socket connected to `host:port`, through the proxy if needed."""
    if cfg is None or not cfg.should_proxy(host):
        return socket.create_connection((host, port), timeout=timeout)

    try:
        sock = socket.create_connection((cfg.host, cfg.port), timeout=timeout)
    except OSError as exc:
        raise ProxyError(f"cannot reach proxy {cfg.host}:{cfg.port} ({exc})") from exc

    sock.settimeout(timeout)
    try:
        if cfg.scheme == SCHEME_SOCKS5:
            _socks5_connect(sock, host, port, cfg)
        else:
            _http_connect(sock, host, port, cfg)
    except ProxyError:
        sock.close()
        raise
    except OSError as exc:
        sock.close()
        raise ProxyError(f"proxy tunnel failed: {exc}") from exc
    return sock


# --------------------------------------------------------------------------- #
#  http.client integration
# --------------------------------------------------------------------------- #
class ProxiedHTTPConnection:
    """Mixin that routes `http.client` connections through a ProxyConfig."""

    def _init_proxy(self, proxy: ProxyConfig | None) -> None:
        self._proxy = proxy

    def connect(self):  # noqa: D102
        self.sock = open_tunnel(self.host, self.port, self.timeout, self._proxy)


def make_http_connection(
    scheme: str,
    host: str,
    port: int,
    timeout: float,
    verify: bool = True,
    proxy: ProxyConfig | None = None,
):
    """Build an http.client connection, proxied when appropriate."""
    import http.client

    use_proxy = proxy is not None and proxy.should_proxy(host)

    if scheme == "https":
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        if not use_proxy:
            return http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)

        class _TunnelledHTTPS(http.client.HTTPSConnection):
            def connect(self_inner):
                raw = open_tunnel(self_inner.host, self_inner.port, self_inner.timeout, proxy)
                self_inner.sock = self_inner._context.wrap_socket(
                    raw, server_hostname=self_inner.host
                )

        return _TunnelledHTTPS(host, port, timeout=timeout, context=ctx)

    if not use_proxy:
        return http.client.HTTPConnection(host, port, timeout=timeout)

    class _TunnelledHTTP(http.client.HTTPConnection):
        def connect(self_inner):
            self_inner.sock = open_tunnel(self_inner.host, self_inner.port,
                                          self_inner.timeout, proxy)

    return _TunnelledHTTP(host, port, timeout=timeout)


# --------------------------------------------------------------------------- #
#  connectivity test
# --------------------------------------------------------------------------- #
TEST_URLS = [
    ("https://www.gstatic.com/generate_204", "Google 204"),
    ("https://www.google.com/generate_204", "Google 204"),
    ("http://www.gstatic.com/generate_204", "Google 204 (HTTP)"),
    ("https://www.cloudflare.com/cdn-cgi/trace", "Cloudflare"),
]


def test_proxy(cfg: ProxyConfig, timeout: float = 8.0, target: str = "") -> dict:
    """Check whether traffic flows. Returns {ok, message, detail, target}."""
    import time

    if cfg.mode == MODE_SYSTEM and not cfg.usable:
        return {
            "ok": False,
            "message": cfg.unresolved or "未检测到系统代理设置",
            "detail": "",
            "target": "",
        }

    candidates = [(target, "自定义目标")] if target else TEST_URLS
    last = ""
    for url, label in candidates:
        parts = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        path = parts.path or "/"
        t0 = time.time()
        try:
            conn = make_http_connection(
                parts.scheme, host, port, timeout, verify=False, proxy=cfg
            )
            conn.request("GET", path, headers={"User-Agent": DEFAULT_TEST_UA,
                                               "Connection": "close"})
            resp = conn.getresponse()
            resp.read(64)
            status = resp.status
            conn.close()
            elapsed = time.time() - t0
            via = "通过代理" if cfg.should_proxy(host) else "直连"
            if status < 400:
                return {
                    "ok": True,
                    "message": f"连接正常（{via}）· HTTP {status} · {elapsed*1000:.0f} ms",
                    "detail": f"{label}  {url}",
                    "target": url,
                    "ms": int(elapsed * 1000),
                }
            last = f"HTTP {status}"
        except ProxyError as exc:
            last = str(exc)
            break          # a proxy-level failure will not differ per target
        except ssl.SSLError as exc:
            last = f"TLS 错误：{exc}"
        except socket.timeout:
            last = "连接超时"
        except OSError as exc:
            last = str(exc)
    return {"ok": False, "message": last or "无法连接", "detail": "", "target": ""}


DEFAULT_TEST_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BroadcastRadio/1.0"


# --------------------------------------------------------------------------- #
#  local CONNECT shim for external tools
# --------------------------------------------------------------------------- #
class LocalProxyShim:
    """A loopback HTTP CONNECT proxy that forwards through `upstream`.

    ffmpeg (used for HLS and for re-muxing recordings) understands
    `-http_proxy` but has no portable SOCKS5 support, and its handling of
    proxy authentication varies by build. Rather than special-casing each
    combination, external tools are pointed at this shim, which tunnels every
    CONNECT through the same `open_tunnel()` path the rest of the application
    uses - so HTTP, HTTPS, SOCKS5 and credentials all behave identically.
    """

    def __init__(self, upstream: ProxyConfig | None = None, timeout: float = 15.0):
        self.upstream = upstream
        self.timeout = timeout
        self._server = None
        self._thread = None
        self._port = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> str:
        import select
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        shim = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D102
                pass

            def do_CONNECT(self):  # noqa: N802
                target = self.path
                if ":" not in target:
                    self.send_error(400, "expected host:port")
                    return
                host, _, port_s = target.rpartition(":")
                host = host.strip("[]")
                try:
                    port = int(port_s)
                except ValueError:
                    self.send_error(400, "bad port")
                    return

                try:
                    upstream_sock = open_tunnel(host, port, shim.timeout, shim.upstream)
                except (ProxyError, OSError) as exc:
                    try:
                        self.send_error(502, f"tunnel failed: {exc}")
                    except OSError:
                        pass
                    return

                self.send_response(200, "Connection Established")
                self.end_headers()
                try:
                    self.connection.setblocking(False)
                    upstream_sock.setblocking(False)
                    sockets = [self.connection, upstream_sock]
                    while not shim._stopping:
                        readable, _, errored = select.select(sockets, [], sockets, 1.0)
                        if errored:
                            break
                        if not readable:
                            continue
                        for src in readable:
                            dst = upstream_sock if src is self.connection else self.connection
                            try:
                                data = src.recv(65536)
                            except (BlockingIOError, InterruptedError):
                                continue
                            except OSError:
                                data = b""
                            if not data:
                                raise StopIteration
                            view = memoryview(data)
                            while view:
                                try:
                                    sent = dst.send(view)
                                    view = view[sent:]
                                except (BlockingIOError, InterruptedError):
                                    select.select([], [dst], [], 1.0)
                                except OSError:
                                    raise StopIteration
                except (StopIteration, OSError):
                    pass
                finally:
                    for s in (upstream_sock,):
                        try:
                            s.close()
                        except OSError:
                            pass
                    self.close_connection = True

        self._stopping = False
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="proxy-shim", daemon=True
        )
        self._thread.start()
        return self.url

    def stop(self) -> None:
        self._stopping = True
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False
