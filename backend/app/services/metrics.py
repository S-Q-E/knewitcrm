from __future__ import annotations

import time

_started_at = time.monotonic()

# In-process counters only (single-container deploy, see D9). Cardinality is
# bounded: route labels use FastAPI route templates, unknown paths collapse.
_requests_total: dict[tuple[str, str, int], int] = {}
_request_seconds_total: dict[tuple[str, str, int], float] = {}


def note_request(method: str, route: str, status: int, duration: float) -> None:
    key = (method, route, status)
    _requests_total[key] = _requests_total.get(key, 0) + 1
    _request_seconds_total[key] = _request_seconds_total.get(key, 0.0) + duration


def uptime_seconds() -> float:
    return time.monotonic() - _started_at


# Wall-clock time of the last successful cycle per in-process worker. Gauges
# derived from it show a stalled loop even when its DB marker is absent.
_cycle_marks: dict[str, float] = {}


def mark_cycle(worker: str) -> None:
    _cycle_marks[worker] = time.time()


def cycle_age_seconds(worker: str) -> float | None:
    mark = _cycle_marks.get(worker)
    return None if mark is None else max(0.0, time.time() - mark)


def reset() -> None:
    _requests_total.clear()
    _request_seconds_total.clear()
    _cycle_marks.clear()


def render_prometheus(extra_lines: list[str] | None = None) -> str:
    """Minimal Prometheus exposition format (counters, gauges, one summary)."""
    lines = [
        "# HELP crm_http_requests_total HTTP requests by method, route and status.",
        "# TYPE crm_http_requests_total counter",
    ]
    for (method, route, status), count in sorted(_requests_total.items()):
        key = f'method="{method}",route="{route}",status="{status}"'
        lines.append(f"crm_http_requests_total{{{key}}} {count}")
    lines += [
        "# HELP crm_http_request_seconds_total Total handler time by method and route.",
        "# TYPE crm_http_request_seconds_total counter",
    ]
    for (method, route, _), total in sorted(_request_seconds_total.items()):
        key = f'method="{method}",route="{route}"'
        lines.append(f"crm_http_request_seconds_total{{{key}}} {total:.3f}")
    lines += [
        "# HELP crm_uptime_seconds Seconds since process start.",
        "# TYPE crm_uptime_seconds gauge",
        f"crm_uptime_seconds {uptime_seconds():.0f}",
    ]
    for extra in extra_lines or []:
        lines.append(extra)
    return "\n".join(lines) + "\n"
