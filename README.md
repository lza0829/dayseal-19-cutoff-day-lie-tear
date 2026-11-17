# Dayseal（日封台）

收银流水按营业日归集，日结封账后锁定；长短款可查。

- 前端 http://127.0.0.1:5700
- API http://127.0.0.1:10700

## 日内截止归集

接近换日的流水按全局唯一的 cutoff 配置归集（`GET/PUT /api/settings/cutoff`）：

- `cutoff_time`：营业日截止时刻（UTC，HH:MM，默认 02:00），营业日 D 的窗口为
  `[D 日 cutoff, D+1 日 cutoff)`。
- 策略 `roll_to_next_day`（截止后归入次日）：occurred_at **严格晚于** cutoff 的流水
  落库 `business_day` 为下一营业日，当日封账预览与批次合计不含这些行。
- 策略 `mark_late`（截止后仍归本日并打晚到标）：流水仍属当日 `business_day` 并进入
  当日封账合计，但持久化 `late_flag=1`；封账批次快照记录晚到笔数 `late_count` 与
  金额 `late_total`，晚到行不会被丢弃。

两种策略互斥，全局只贯彻一种；归集口径、封账预览、批次快照同源
（`app/services/cutoff_service.py`）。修改 cutoff 只影响未封日的新写入，已 sealed
批次的合计与快照（含冻结的 cutoff_time/cutoff_policy）不回溯、不篡改。

## 启动

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 10700 --app-dir .
```

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5700
```

## 核验

```bash
# 独立临时库，覆盖两种策略、cutoff 边界、改 cutoff 不影响已封日
DAYSEAL_DATA_DIR=$(mktemp -d) backend/.venv/bin/python -I tests/test_cutoff.py
```
