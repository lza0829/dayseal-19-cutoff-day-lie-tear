"""日内截止归集规则端到端核验。

覆盖：
1. roll_to_next_day：cutoff 前归当日、严格晚于 cutoff 落次日、当日封账不含次日行；
2. mark_late：晚到行仍归当日 + late_flag，批次快照可核验晚到笔数/金额，不丢行；
3. cutoff 边界（恰好等于 cutoff 不滚动，严格晚于才滚动）；
4. 改 cutoff 只影响未封日，已 sealed 批次合计与快照不动，既有流水不回溯重算。
"""
from __future__ import annotations
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="dayseal-test-")
os.environ["DAYSEAL_DATA_DIR"] = _tmp
sys.path.insert(0, "/workspace/backend")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import connect  # noqa: E402

client = TestClient(app)
failures: list[str] = []

# 清掉种子数据，保证合计断言只受本测试写入影响
_cleanup = connect()
_cleanup.execute("DELETE FROM cash_lines")
_cleanup.execute("DELETE FROM close_batches")
_cleanup.execute("DELETE FROM variance_rows")
_cleanup.commit()
_cleanup.close()


def check(name: str, got, want) -> None:
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
    if not ok:
        failures.append(name)


def set_day(day: str) -> None:
    r = client.put("/api/settings/business-day", json={"business_day": day})
    assert r.status_code == 200, r.text


def set_cutoff(time: str, policy: str) -> dict:
    r = client.put("/api/settings/cutoff", json={"cutoff_time": time, "cutoff_policy": policy})
    assert r.status_code == 200, r.text
    return r.json()


def add_line(amount: float, occurred_at: str, till: str = "TILL-A") -> dict:
    r = client.post("/api/lines", json={
        "till_code": till, "amount": amount, "occurred_at": occurred_at,
    })
    assert r.status_code == 200, r.text
    return r.json()


def post_line_raw(amount: float, occurred_at: str) -> int:
    return client.post("/api/lines", json={
        "till_code": "TILL-A", "amount": amount, "occurred_at": occurred_at,
    }).status_code


def day_rows(day: str) -> list[dict]:
    return client.get(f"/api/lines?business_day={day}").json()


def preview(day: str) -> dict:
    return client.get("/api/close/preview", params={"business_day": day}).json()


def seal(day: str, declared: float) -> dict:
    r = client.post("/api/close/seal", json={"business_day": day, "declared_cash": declared})
    assert r.status_code == 200, r.text
    return r.json()


def batches() -> list[dict]:
    return client.get("/api/close/batches").json()


# ---------- 场景一：roll_to_next_day ----------
print("== 场景一：截止后归入次日 ==")
set_day("2026-11-16")
set_cutoff("02:00", "roll_to_next_day")

before = add_line(100.0, "2026-11-17T01:59:00Z")   # 营业日 16 的窗口内
check("roll: cutoff 前流水归当日", before["business_day"], "2026-11-16")
check("roll: 正常行 late_flag=0", before["late_flag"], 0)

boundary = add_line(10.0, "2026-11-17T02:00:00Z")  # 恰好等于 cutoff，不滚动
check("roll: 恰好等于 cutoff 仍归当日", boundary["business_day"], "2026-11-16")

after = add_line(50.0, "2026-11-17T02:01:00Z")     # 严格晚于 cutoff -> 次日
check("roll: 严格晚于 cutoff 落次日（落库 business_day 已改）", after["business_day"], "2026-11-17")
check("roll: 次日行 late_flag=0", after["late_flag"], 0)

morning = add_line(70.0, "2026-11-17T08:30:00Z")
check("roll: 次日早晨归次日", morning["business_day"], "2026-11-17")

p16 = preview("2026-11-16")
check("roll: 当日预览笔数不含次日行", p16["line_count"], 2)
check("roll: 当日预览合计 = 100+10", round(p16["system_total"], 2), 110.0)
check("roll: 当日预览晚到为 0", (p16["late_count"], p16["late_total"]), (0, 0.0))
check("roll: 预览回传同源 cutoff", (p16["cutoff_time"], p16["cutoff_policy"]),
      ("02:00", "roll_to_next_day"))

p17 = preview("2026-11-17")
check("roll: 次日预览承接滚入行", (p17["line_count"], round(p17["system_total"], 2)), (2, 120.0))

# 落库核验（防止只改展示不改 business_day）
conn = connect()
db_day = conn.execute(
    "SELECT business_day FROM cash_lines WHERE line_no=?", (after["line_no"],)
).fetchone()["business_day"]
conn.close()
check("roll: 数据库内 business_day 确为次日", db_day, "2026-11-17")

sealed16 = seal("2026-11-16", 110.0)
check("roll: 封账合计不含次日行", round(sealed16["system_total"], 2), 110.0)
check("roll: 封账快照晚到为 0", (sealed16["late_count"], round(sealed16["late_total"], 2)), (0, 0.0))

check("roll: 已封日新增被拒(409)", post_line_raw(999.0, "2026-11-17T01:00:00Z"), 409)


# ---------- 场景二：mark_late ----------
print("\n== 场景二：截止后仍归本日并打晚到标 ==")
set_day("2026-11-18")
set_cutoff("02:00", "mark_late")

normal = add_line(200.0, "2026-11-19T01:00:00Z")
check("late: cutoff 前正常归当日", (normal["business_day"], normal["late_flag"]), ("2026-11-18", 0))

late = add_line(80.0, "2026-11-19T03:30:00Z")  # 夜班补录，自然归属应为次日
check("late: 晚到行仍钉在当日 business_day", late["business_day"], "2026-11-18")
check("late: 晚到行持久化 late_flag=1", late["late_flag"], 1)

late2 = add_line(20.0, "2026-11-19T02:00:30Z")
check("late: 严格晚于 cutoff 才算晚到", (late2["business_day"], late2["late_flag"]), ("2026-11-18", 1))

bound = add_line(5.0, "2026-11-19T02:00:00Z")
check("late: 等于 cutoff 不打晚到标", (bound["business_day"], bound["late_flag"]), ("2026-11-18", 0))

p18 = preview("2026-11-18")
check("late: 晚到行未被丢弃，全部进当日合计", (p18["line_count"], round(p18["system_total"], 2)),
      (4, 305.0))
check("late: 预览可核验晚到笔数与金额", (p18["late_count"], round(p18["late_total"], 2)), (2, 100.0))

sealed18 = seal("2026-11-18", 305.0)
check("late: 封账合计含晚到行", round(sealed18["system_total"], 2), 305.0)
check("late: 批次快照晚到笔数/金额", (sealed18["late_count"], round(sealed18["late_total"], 2)),
      (2, 100.0))
check("late: 批次快照冻结 cutoff 配置", (sealed18["cutoff_time"], sealed18["cutoff_policy"]),
      ("02:00", "mark_late"))


# ---------- 场景三：改 cutoff 只影响未封日，已封日不动 ----------
print("\n== 场景三：改 cutoff 的影响范围 ==")
set_day("2026-11-20")
set_cutoff("02:00", "roll_to_next_day")
a = add_line(30.0, "2026-11-21T01:30:00Z")
check("re-cut: 旧 cutoff(02:00) 下 01:30 归当日", a["business_day"], "2026-11-20")
a2 = add_line(70.0, "2026-11-21T03:00:00Z")
check("re-cut: 旧 cutoff(02:00) 下 03:00 滚次日", a2["business_day"], "2026-11-21")
seal("2026-11-20", 30.0)

# 改 cutoff 时刻 + 换策略（全局唯一，立即生效于新写入）
set_cutoff("04:00", "mark_late")
cfg = client.get("/api/settings/cutoff").json()
check("re-cut: 配置已全局切换", (cfg["cutoff_time"], cfg["cutoff_policy"]), ("04:00", "mark_late"))

# 已封日（20 日）：新 cutoff 下 03:00 本会归 20 日，但封账拦截，钻不进旧批次
check("re-cut: 新口径落到已封日时被封账拦截(409)",
      post_line_raw(60.0, "2026-11-21T03:00:00Z"), 409)

# 已封批次快照纹丝不动（合计/笔数/冻结的旧 cutoff）
b20 = [x for x in batches() if x["business_day"] == "2026-11-20"][0]
check("re-cut: 已封批次合计不被篡改", round(b20["system_total"], 2), 30.0)
check("re-cut: 已封批次笔数不被篡改", b20["line_count"], 1)
check("re-cut: 已封批次保留旧 cutoff 快照", (b20["cutoff_time"], b20["cutoff_policy"]),
      ("02:00", "roll_to_next_day"))

# 未封日（21 日）按新口径走：工作营业日切到 21
set_day("2026-11-21")
c = add_line(60.0, "2026-11-22T04:30:00Z")  # 严格晚于 04:00 -> 自然归 22 日，mark_late 钉在 21
check("re-cut: mark_late 下 04:30 钉工作营业日并打晚到",
      (c["business_day"], c["late_flag"]), ("2026-11-21", 1))
d = add_line(40.0, "2026-11-22T03:30:00Z")  # 新 cutoff 04:00 前 -> 自然归 21 日，非晚到
check("re-cut: 新 cutoff(04:00) 下 03:30 归工作营业日且非晚到",
      (d["business_day"], d["late_flag"]), ("2026-11-21", 0))

p21 = preview("2026-11-21")
# a2(70, 旧口径滚入) + c(60, 晚到) + d(40) = 3 笔 170，晚到 1 笔 60
check("re-cut: 未封日预览按新口径汇总且晚到可核验",
      (p21["line_count"], round(p21["system_total"], 2),
       p21["late_count"], round(p21["late_total"], 2)),
      (3, 170.0, 1, 60.0))

# 既有流水不回溯重算：a2 仍稳稳落在 21 日
rows21 = {r["line_no"]: r for r in day_rows("2026-11-21")}
check("re-cut: 改 cutoff 不回溯重算既有流水", rows21[a2["line_no"]]["business_day"], "2026-11-21")

# 非法配置被拒
bad = client.put("/api/settings/cutoff", json={"cutoff_time": "25:00", "cutoff_policy": "mark_late"})
check("re-cut: 非法时刻 400", bad.status_code, 400)
bad2 = client.put("/api/settings/cutoff", json={"cutoff_time": "03:00", "cutoff_policy": "whatever"})
check("re-cut: 非法策略 400", bad2.status_code, 400)


# ---------- 场景四：滚动窗口自然日边界 ----------
print("\n== 场景四：滚动窗口自然日边界 ==")
set_cutoff("02:00", "roll_to_next_day")
set_day("2026-11-22")
e1 = add_line(11.0, "2026-11-22T00:30:00Z")  # 凌晨 00:30 <= cutoff -> 属前一营业日 21
check("window: 当日凌晨 00:30 滚归前一营业日", e1["business_day"], "2026-11-21")
e2 = add_line(22.0, "2026-11-22T02:00:00Z")  # 恰好等于 cutoff，不滚动 -> 仍属 21 日
check("window: 02:00 整点（非严格晚于）仍属前一营业日", e2["business_day"], "2026-11-21")
e3 = add_line(33.0, "2026-11-22T23:59:00Z")
check("window: 23:59 归 22 日", e3["business_day"], "2026-11-22")

print("\n" + ("全部通过" if not failures else f"失败 {len(failures)} 项: {failures}"))
sys.exit(1 if failures else 0)
