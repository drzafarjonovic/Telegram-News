"""
Yengil monitoring/metrikslar moduli (Enterprise v2.0).

Tashqi kutubxonasiz (prometheus_client shart emas) — oddiy Counter/Gauge
registri va ixtiyoriy HTTP eksport (/metrics Prometheus formatida, /healthz).
`metrics_enabled=False` bo'lsa HTTP server ishga tushmaydi, lekin hisoblagichlar
baribir ishlab turadi (ichki diagnostika uchun).

Grafana/Prometheus scrape target: http://<host>:<METRICS_PORT>/metrics
"""
from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

_registry: dict = {}


class _Metric:
    def __init__(self, name: str, help_text: str, kind: str) -> None:
        self.name = name
        self.help = help_text
        self.kind = kind
        self._value = 0.0
        self._lock = threading.Lock()
        _registry[name] = self

    def inc(self, n: float = 1) -> None:
        with self._lock:
            self._value += n

    def dec(self, n: float = 1) -> None:
        with self._lock:
            self._value -= n

    def set(self, v: float) -> None:
        with self._lock:
            self._value = float(v)

    @property
    def value(self) -> float:
        return self._value


def counter(name: str, help_text: str) -> _Metric:
    return _Metric(name, help_text, "counter")


def gauge(name: str, help_text: str) -> _Metric:
    return _Metric(name, help_text, "gauge")


# --- Metrikslar ro'yxati ---
messages_received = counter("tgnews_messages_received_total", "Qabul qilingan xabarlar (event)")
messages_processed = counter("tgnews_messages_processed_total", "Muvaffaqiyatli qayta ishlangan xabarlar")
messages_dropped = counter("tgnews_messages_dropped_total", "Navbat to'lgani sababli kutgan/tashlangan xabarlar")
ingest_errors = counter("tgnews_ingest_errors_total", "Ingest bosqichidagi xatolar")
ocr_total = counter("tgnews_ocr_total", "OCR bajarilgan media soni")
stt_total = counter("tgnews_stt_total", "Speech-to-text bajarilgan media soni")
backfill_messages = counter("tgnews_backfill_messages_total", "Backfill orqali olingan xabarlar")
edits_total = counter("tgnews_edits_total", "Tahrirlangan xabarlar")
deletes_total = counter("tgnews_deletes_total", "O'chirilgan xabarlar")
floodwait_total = counter("tgnews_floodwait_total", "FloodWait hodisalari soni")
queue_depth = gauge("tgnews_queue_depth", "Ingest navbati uzunligi")
workers_active = gauge("tgnews_workers_active", "Faol worker soni")


def render() -> str:
    """Prometheus matn formatida barcha metrikslarni qaytaradi."""
    lines: list[str] = []
    for m in _registry.values():
        lines.append(f"# HELP {m.name} {m.help}")
        lines.append(f"# TYPE {m.name} {m.kind}")
        val = m.value
        out = int(val) if float(val).is_integer() else val
        lines.append(f"{m.name} {out}")
    return "\n".join(lines) + "\n"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.rstrip("/")
        if path in ("/metrics", ""):
            body = render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # HTTP loglarini jim qilamiz
        return


_server = None


def start_server(port: int) -> None:
    global _server
    if _server is not None:
        return
    try:
        _server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    except OSError as exc:
        logger.warning("Metrics server ishga tushmadi (port %s): %s", port, exc)
        _server = None
        return
    t = threading.Thread(target=_server.serve_forever, daemon=True, name="metrics")
    t.start()
    logger.info("Metrics server: http://0.0.0.0:%s/metrics", port)


def stop_server() -> None:
    global _server
    if _server is not None:
        try:
            _server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        _server = None
