from __future__ import annotations
from typing import Any
from fastapi import HTTPException
from app.db import connect
from app.repositories import settings as settings_repo
from app.services import cutoff_service


def get_day() -> dict[str, Any]:
    conn = connect()
    try:
        return {"business_day": settings_repo.get(conn, "business_day")}
    finally:
        conn.close()


def set_day(body: dict[str, Any]) -> dict[str, Any]:
    day = (body.get("business_day") or "").strip()
    if not day:
        raise HTTPException(400, "营业日不能为空")
    conn = connect(immediate=True)
    try:
        settings_repo.set_value(conn, "business_day", day)
        conn.commit()
        return {"business_day": day}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_cutoff() -> dict[str, Any]:
    conn = connect()
    try:
        cfg = cutoff_service.get_cutoff_settings(conn)
        return {
            **cfg,
            "policies": list(cutoff_service.POLICIES),
            "policy_labels": cutoff_service.POLICY_LABELS,
        }
    finally:
        conn.close()


def set_cutoff(body: dict[str, Any]) -> dict[str, Any]:
    """更新 cutoff 配置。

    只影响此后新写入流水的归集与未封日的封账口径；已 sealed 日的批次
    合计冻结在 close_batches 快照里，不会被回溯改写，既有流水也不重算。
    """
    conn = connect(immediate=True)
    try:
        try:
            cfg = cutoff_service.save_cutoff_settings(
                conn,
                cutoff_time=body.get("cutoff_time", ""),
                cutoff_policy=body.get("cutoff_policy", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        conn.commit()
        return cfg
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
