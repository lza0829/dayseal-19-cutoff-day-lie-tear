from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import closes as close_repo
from app.repositories import lines as line_repo
from app.repositories import settings as settings_repo
from app.services import cutoff_service
from app import align_19 as align_mod


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def preview(business_day: str | None = None) -> dict[str, Any]:
    conn = connect()
    try:
        day = business_day or settings_repo.get(conn, "business_day") or ""
        cfg = cutoff_service.get_cutoff_settings(conn)
        sealed_batch = close_repo.get_sealed_batch(conn, day) if day else None

        if sealed_batch is not None:
            # 已封账日：合计/笔数/晚到/cutoff 全部以封账时冻结的批次快照为准，
            # 不再对 cash_lines 做实时聚合——避免改 cutoff 或误投流水后预览与
            # 已 sealed 批次悄悄分叉（已封批数字不得被新 cutoff 篡改）。
            return {
                "business_day": day,
                "system_total": float(sealed_batch["system_total"]),
                "line_count": int(sealed_batch["line_count"]),
                "sealed": True,
                "batch_no": sealed_batch["batch_no"],
                "lines": line_repo.list_lines(conn, day),
                "cutoff_time": sealed_batch["cutoff_time"] or cfg["cutoff_time"],
                "cutoff_policy": sealed_batch["cutoff_policy"] or cfg["cutoff_policy"],
                "late_count": int(sealed_batch["late_count"]),
                "late_total": round(float(sealed_batch["late_total"]), 2),
            }

        # 未封日：实时聚合，口径与流水写入同源（late_total 仅统计 late_flag=1）。
        total, count = line_repo.day_total(conn, day)
        late_sum, late_count = line_repo.late_total(conn, day)
        return {
            "business_day": day,
            "system_total": total,
            "line_count": count,
            "sealed": False,
            "lines": line_repo.list_lines(conn, day),
            # 与落库归集同源的 cutoff 口径；roll 策略下晚到行已落次日，故这里天然为 0。
            "cutoff_time": cfg["cutoff_time"],
            "cutoff_policy": cfg["cutoff_policy"],
            "late_count": late_count,
            "late_total": round(late_sum, 2),
        }
    finally:
        conn.close()


def seal(body: dict[str, Any]) -> dict[str, Any]:
    conn = connect(immediate=True)
    try:
        day = body.get("business_day") or settings_repo.get(conn, "business_day")
        if not day:
            raise HTTPException(400, "未指定营业日")
        if close_repo.is_sealed(conn, day):
            raise HTTPException(409, f"营业日 {day} 已封账")
        declared = float(body["declared_cash"])
        total, count = line_repo.day_total(conn, day)
        late_sum, late_count = line_repo.late_total(conn, day)
        cfg = cutoff_service.get_cutoff_settings(conn)
        variance = round(declared - total, 2)
        sealed_at = _now()
        batch_id = close_repo.create_batch(
            conn,
            batch_no=close_repo.next_batch_no(conn),
            business_day=day,
            system_total=total,
            declared_cash=declared,
            variance=variance,
            line_count=count,
            status="sealed",
            sealed_at=sealed_at,
            note=body.get("note"),
            # 快照冻结：日后改 cutoff/策略不影响已 sealed 批次的合计与晚到核验。
            late_count=late_count,
            late_total=round(late_sum, 2),
            cutoff_time=cfg["cutoff_time"],
            cutoff_policy=cfg["cutoff_policy"],
        )
        disposition = "pending" if abs(variance) > 1e-9 else "balanced"
        close_repo.add_variance(
            conn,
            batch_id=batch_id,
            business_day=day,
            variance=variance,
            disposition=disposition,
            created_at=sealed_at,
        )
        # 晚到快照（late_count/late_total）与封账合计、未封预览同源：
        # 都来自 line_repo 按 business_day(+late_flag=1) 的聚合，封账后冻结在
        # close_batches，不再存在第二套“统计当日全部行”的口径。
        conn.commit()
        return {
            "batch_id": batch_id,
            "business_day": day,
            "system_total": total,
            "declared_cash": declared,
            "variance": variance,
            "line_count": count,
            "status": "sealed",
            "disposition": disposition,
            "late_count": late_count,
            "late_total": round(late_sum, 2),
            "cutoff_time": cfg["cutoff_time"],
            "cutoff_policy": cfg["cutoff_policy"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_batches() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return close_repo.list_batches(conn)
    finally:
        conn.close()


def list_variances() -> list[dict[str, Any]]:
    conn = connect()
    try:
        return close_repo.list_variances(conn)
    finally:
        conn.close()

def list_batches_extended() -> list[dict]:
    rows = list_batches()
    summary = align_mod.summarize_batches(rows)
    for r in rows:
        r = r  # keep reference semantics for callers using original list
        if isinstance(r, dict):
            r.setdefault("alignment", summary.get("alignment_token") if False else summary.get("sealed_count"))
    return rows


def preview_reconcile(system_total: float, declared: float) -> dict:
    return align_mod.reconcile_hint(system_total, declared)

