"""入库管理业务规则：状态流转口径、字段校验与筛选逻辑都收在这里。

流转口径（终态之外每个状态都有明确的下一步）：
- 确认收货：仅「待收货」可执行，必须登记到货温度，完成后变为「已收货」；
- 安排上架：仅「已收货」可执行，完成后变为「已上架」，并在库存管理里
  按同一批次生成库存记录（同入库单重复执行只保留原记录，不重建、不覆盖）；
- 退回入库：「待收货」「已收货」可执行，完成后变为「已退回」；
- 「已上架」「已退回」为终态，不再接受任何动作。
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.store import store

MODULE = "inbound"
INVENTORY_MODULE = "inventory"
REQUIRED_FIELDS = ["入库单号", "供应商名称", "货物名称"]

STATUS_PENDING = "待收货"
STATUS_RECEIVED = "已收货"
STATUS_SHELVED = "已上架"
STATUS_RETURNED = "已退回"
STATUS_ORDER = [STATUS_PENDING, STATUS_RECEIVED, STATUS_SHELVED, STATUS_RETURNED]
TERMINAL_STATUSES = (STATUS_SHELVED, STATUS_RETURNED)

# 动作 -> (允许执行的当前状态集合, 目标状态)
ACTION_FLOW: dict[str, tuple[tuple[str, ...], str]] = {
    "确认收货": ((STATUS_PENDING,), STATUS_RECEIVED),
    "安排上架": ((STATUS_RECEIVED,), STATUS_SHELVED),
    "退回入库": ((STATUS_PENDING, STATUS_RECEIVED), STATUS_RETURNED),
}
ACTION_ORDER = ["确认收货", "安排上架", "退回入库"]

# 内存仓库没有事务：动作里要做「查状态 + 改状态 + 写库存」，加进程内锁防并发双提交。
_flow_lock = threading.Lock()


def available_actions(status: str) -> list[str]:
    """某个状态下页面上应当出现的动作入口，按固定顺序返回。"""
    return [action for action in ACTION_ORDER if status in ACTION_FLOW[action][0]]


def parse_temperature(raw: Any) -> str | None:
    """把到货温度归一化成「数值+℃」；空值或非数字返回 None，交由上层拦下。"""
    text = str(raw or "").strip().removesuffix("℃").removesuffix("°C").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return f"{value:g}℃"


class InboundService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("入库单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        with _flow_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"入库单 {entry_id} 不存在或已归档"
            if action not in ACTION_FLOW:
                return None, f"动作「{action}」不属于入库管理可执行范围"

            status = str(entry.get("status") or "")
            allowed, target = ACTION_FLOW[action]
            if status not in allowed:
                options = "、".join(available_actions(status)) or "无"
                return None, (
                    f"入库单当前处于「{status}」状态，不能{action}；"
                    f"当前可选动作：{options}。"
                )

            if action == "确认收货":
                temperature = parse_temperature(values.get("到货温度"))
                if temperature is None:
                    return None, "确认收货必须登记到货温度，请填写数字温度（如 2.5 或 -18℃）"
                entry["到货温度"] = temperature
                message = f"入库单已确认收货，到货温度 {temperature} 已记录"
            elif action == "安排上架":
                inventory = self._ensure_inventory(entry)
                message = (
                    f"入库单已安排上架，批次「{inventory['批次号']}」"
                    f"已在库存管理生成记录 {inventory['库存编码']}"
                )
            else:
                message = "入库单已退回，不能再确认收货或安排上架"

            entry["status"] = target
            entry["pending"] = target not in TERMINAL_STATUSES
            return entry, message

    def _ensure_inventory(self, entry: dict[str, Any]) -> dict[str, Any]:
        """上架完成后把同一批次写进库存管理；同入库单重复上架复用原记录。"""
        rows = store.rows(INVENTORY_MODULE)
        order_no = str(entry.get("入库单号") or "")
        batch = str(entry.get("批次号") or "").strip() or f"批次-{order_no or entry.get('id')}"

        # 已上架过的入库单直接返回原有库存记录，保留原上架记录。
        if order_no:
            for row in rows:
                if str(row.get("来源入库单号") or "") == order_no:
                    return row

        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        record = {
            "id": new_id,
            "status": "正常",
            "pending": True,
            "abnormal": False,
            "库存编码": f"INVE-{new_id:04d}",
            "货物名称": entry.get("货物名称", ""),
            "批次号": batch,
            "库位编号": "待分配",
            "在库数量": entry.get("入库数量", 0),
            "锁定量": 0,
            "保质期至": "—",
            "入库日期": entry.get("入库时间") or date.today().isoformat(),
            "来源入库单号": order_no,
        }
        rows.append(record)
        return record
