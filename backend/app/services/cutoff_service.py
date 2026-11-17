"""日内截止（intraday cutoff）归集规则——全局唯一事实源。

流水落库的 business_day 归集、封账预览、批次快照全部经由本模块，
保证 cutoff 配置与归集口径同源。策略全局互斥，只贯彻 cutoff_policy 这一种：

- roll_to_next_day：occurred_at 严格晚于营业日 cutoff 时刻的流水，
  business_day 落为下一营业日，不进入当日封账预览与批次合计。
- mark_late：流水仍归入当前营业日 business_day 并进入当日封账合计，
  但持久化 late_flag=1，批次快照核验晚到笔数与金额，不得丢弃晚到行。
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.repositories import settings as settings_repo

DEFAULT_CUTOFF_TIME = "02:00"

POLICY_ROLL = "roll_to_next_day"
POLICY_LATE = "mark_late"
POLICIES = (POLICY_ROLL, POLICY_LATE)
POLICY_LABELS = {
    POLICY_ROLL: "截止后归入次日",
    POLICY_LATE: "截止后仍归本日并打晚到标",
}


def normalize_cutoff_time(value: str | None) -> str:
    """校验并归一化为 HH:MM；非法值抛 ValueError。"""
    text = (value or "").strip()
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ValueError("cutoff_time 必须是 HH:MM 格式（00:00-23:59）") from exc
    return parsed.strftime("%H:%M")


def get_cutoff_settings(conn: Any) -> dict[str, str]:
    """读取当前唯一生效的 cutoff 配置（带默认值与容错）。"""
    raw_time = settings_repo.get(conn, "cutoff_time")
    raw_policy = settings_repo.get(conn, "cutoff_policy")
    cutoff_time = DEFAULT_CUTOFF_TIME
    if raw_time:
        try:
            cutoff_time = normalize_cutoff_time(raw_time)
        except ValueError:
            cutoff_time = DEFAULT_CUTOFF_TIME
    cutoff_policy = raw_policy if raw_policy in POLICIES else POLICY_ROLL
    return {"cutoff_time": cutoff_time, "cutoff_policy": cutoff_policy}


def save_cutoff_settings(conn: Any, cutoff_time: str, cutoff_policy: str) -> dict[str, str]:
    cutoff_time = normalize_cutoff_time(cutoff_time)
    if cutoff_policy not in POLICIES:
        raise ValueError(f"cutoff_policy 必须是 {POLICIES} 之一")
    settings_repo.set_value(conn, "cutoff_time", cutoff_time)
    settings_repo.set_value(conn, "cutoff_policy", cutoff_policy)
    return {"cutoff_time": cutoff_time, "cutoff_policy": cutoff_policy}


def _parse_utc(occurred_at: str) -> datetime:
    text = occurred_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def natural_business_day(occurred_at: str, cutoff_time: str) -> str:
    """按滚动 cutoff 窗口计算自然营业日（YYYY-MM-DD）。

    营业日 D 的窗口为 [D 日 cutoff, D+1 日 cutoff]：
    occurred_at 时刻严格晚于当日 cutoff 才属于当日，否则（含恰好等于
    cutoff 的边界）顺延归属上一营业日。
    """
    dt = _parse_utc(occurred_at)
    cut_h, cut_m = (int(x) for x in cutoff_time.split(":"))
    cutoff_clock = time(hour=cut_h, minute=cut_m)
    calendar_day = dt.date()
    # 严格晚于 cutoff 才留在当日；恰好等于 cutoff（含秒级比较）顺延上一营业日。
    if dt.time() > cutoff_clock:
        day = calendar_day
    else:
        day = calendar_day - timedelta(days=1)
    return day.isoformat()


def attribute(conn: Any, base_day: str, occurred_at: str) -> dict[str, Any]:
    """流水归集唯一入口：返回落库 business_day 与 late_flag。

    base_day 为柜员当前工作的营业日（设置项或请求体携带）。
    两种策略共用同一个 natural_business_day 口径，保证互斥且同源。
    """
    cfg = get_cutoff_settings(conn)
    cutoff_time = cfg["cutoff_time"]
    policy = cfg["cutoff_policy"]
    natural = natural_business_day(occurred_at, cutoff_time)

    if policy == POLICY_ROLL:
        # 截止后归入次日：晚到行直接落到下一营业日，当日合计天然不含这些行。
        return {
            "business_day": natural,
            "late_flag": 0,
            "natural_business_day": natural,
            "cutoff_time": cutoff_time,
            "cutoff_policy": policy,
        }

    # mark_late：本应滚入次日的行仍钉在当前工作营业日，打晚到标，不得丢弃。
    base = date.fromisoformat(base_day)
    natural_day = date.fromisoformat(natural)
    if natural_day > base:
        return {
            "business_day": base_day,
            "late_flag": 1,
            "natural_business_day": natural,
            "cutoff_time": cutoff_time,
            "cutoff_policy": policy,
        }
    return {
        "business_day": natural,
        "late_flag": 0,
        "natural_business_day": natural,
        "cutoff_time": cutoff_time,
        "cutoff_policy": policy,
    }
