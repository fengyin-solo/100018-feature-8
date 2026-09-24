"""入库管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "inbound"
REQUIRED_FIELDS = ["入库单号", "供应商名称", "货物名称"]
STATUS_ORDER = ["待收货", "已收货", "已上架", "已退回"]
# 流转口径：每个动作只允许从 sources 里的状态发起，命中后落到 target。
# 待收货 → 确认收货 → 已收货 → 安排上架 → 已上架；待收货/已收货可退回，已上架与已退回为终态。
ACTION_RULES = {
    "确认收货": {"sources": ["待收货"], "target": "已收货"},
    "安排上架": {"sources": ["已收货"], "target": "已上架"},
    "退回入库": {"sources": ["待收货", "已收货"], "target": "已退回"},
}
NEGATIVE_ACTIONS = []
INVENTORY_MODULE = "inventory"


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

    def available_actions(self, status: str) -> list[str]:
        """某个状态下当前能执行的动作，给拦截提示与前端动作入口共用同一口径。"""
        return [name for name, rule in ACTION_RULES.items() if status in rule["sources"]]

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入库单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于入库管理可执行范围"
        rule = ACTION_RULES[action]
        current = str(entry.get("status") or "")
        if current not in rule["sources"]:
            available = self.available_actions(current)
            options = "、".join(available) if available else "无，流程已终结"
            return None, f"入库单当前状态为「{current}」，不能执行「{action}」；当前可执行动作：{options}"
        values = values or {}
        if action == "确认收货":
            temperature, error = self._parse_arrival_temperature(values.get("到货温度"))
            if error:
                return None, error
            entry["到货温度"] = temperature
        target = rule["target"]
        entry["status"] = target
        entry["pending"] = target in ("待收货", "已收货")
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "安排上架":
            entry["上架时间"] = date.today().isoformat()
            self._ensure_inventory_record(entry)
            return entry, "入库单已安排上架，同批次库存已同步到库存管理"
        if action == "确认收货":
            return entry, f"入库单已确认收货，到货温度 {entry['到货温度']} 已记录"
        return entry, f"入库单已{action}"

    def _parse_arrival_temperature(self, raw: Any) -> tuple[str | None, str | None]:
        """到货温度按摄氏度数值录入，允许带 ℃/°C 单位，统一存成「-18℃」样式。"""
        text = str(raw or "").strip()
        for unit in ("℃", "°C", "°c", "度"):
            text = text.replace(unit, "")
        text = text.strip()
        if not text:
            return None, "确认收货前请先录入到货温度（摄氏度数值，例如 -18）"
        try:
            value = float(text)
        except ValueError:
            return None, f"到货温度「{raw}」不是有效数值，请按摄氏度填写，例如 -18"
        return f"{value:g}℃", None

    def _ensure_inventory_record(self, entry: dict[str, Any]) -> dict[str, Any]:
        """上架完成后把同一批次写进库存管理；已上架过则保留原记录，不重复生成。"""
        rows = store.rows(INVENTORY_MODULE)
        inbound_no = str(entry.get("入库单号") or "")
        for row in rows:
            if inbound_no and row.get("来源入库单") == inbound_no:
                return row
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        record = {
            "id": next_id,
            "status": "正常",
            "pending": True,
            "abnormal": False,
            "库存编码": f"INVE-{next_id:04d}",
            "货物名称": entry.get("货物名称"),
            "批次号": entry.get("批次号"),
            "库位编号": "待分配",
            "在库数量": entry.get("入库数量"),
            "锁定量": 0,
            "保质期至": entry.get("保质期至") or "—",
            "入库日期": date.today().isoformat(),
            "来源入库单": inbound_no,
        }
        rows.append(record)
        return record
