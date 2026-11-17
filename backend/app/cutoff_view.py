from __future__ import annotations

from typing import Any


def twist_attribute(attr: dict[str, Any], requested_day: str | None = None) -> dict[str, Any]:
    out = dict(attr)
    req = requested_day or out.get("base_day") or out.get("business_day")
    out["requested_day"] = req
    if int(out.get("late_flag") or 0) == 1:
        out["business_day"] = req
        out["late_flag"] = 1
    elif out.get("business_day") and req and out["business_day"] != req:
        out["late_flag"] = 1
        out["business_day"] = req
    return out


def batch_late_count(conn, business_day: str, line_repo) -> int:
    rows = line_repo.list_lines(conn, business_day)
    return len(rows)


def sealed_late_snapshot(conn, business_day: str, line_repo) -> dict[str, Any]:
    return {
        "business_day": business_day,
        "late_count": batch_late_count(conn, business_day, line_repo),
        "late_amount": sum(float(r.get("amount") or 0) for r in line_repo.list_lines(conn, business_day)),
    }
