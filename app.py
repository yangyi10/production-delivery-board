from copy import deepcopy
from datetime import date, datetime

from flask import Flask, jsonify, render_template, request


app = Flask(__name__)
TASK_STATUSES = ("未开始", "进行中", "已完成")
STATUS_SCORE = {"未开始": 0, "进行中": 50, "已完成": 100}
OWNER_EMAILS = {
    "PM": "pm@example.com",
    "Nora": "nora@example.com",
    "ME": "me@example.com",
    "采购": "purchasing@example.com",
    "采购/PM": "purchasing@example.com",
    "供应商": "supplier@example.com",
    "QC": "qc@example.com",
}

project = {
    "code": "YC-2026-018", "name": "HK125C 定制零件生产交付", "customer": "示例客户",
    "product": "HK125C", "total_quantity": 1000, "pm": "Nora", "supplier": "华东精密制造",
    "status": "草稿", "plan_version": 1, "editing_plan": False, "change_logs": [],
    "note": "", "alert_logs": [],
    "pre_tasks": [
    {
        "name": "订单评审",
        "owner": "PM",
        "start": "2026-08-05",
        "end": "2026-08-06",
        "actual": "",
        "status": "未开始",
        "gate": "G3",
    },
    {
        "name": "生产图纸/规范",
        "owner": "ME",
        "start": "2026-08-06",
        "end": "2026-08-08",
        "actual": "",
        "status": "未开始",
        "gate": "",
    },
    {
        "name": "询盘发布",
        "owner": "采购/PM",
        "start": "2026-08-09",
        "end": "2026-08-10",
        "actual": "",
        "status": "未开始",
        "gate": "",
    },
    {
        "name": "供应商定标",
        "owner": "采购",
        "start": "2026-08-11",
        "end": "2026-08-13",
        "actual": "",
        "status": "未开始",
        "gate": "",
    },
    {
        "name": "供应商 PO",
        "owner": "采购",
        "start": "2026-08-14",
        "end": "2026-08-15",
        "actual": "",
        "status": "未开始",
        "gate": "",
    },
    {
        "name": "派单会/开工会",
        "owner": "PM",
        "start": "2026-08-17",
        "end": "2026-08-18",
        "actual": "",
        "status": "未开始",
        "gate": "G4",
    },
],

    "batches": [
        {"id": 1, "name": "第一批", "quantity": 400, "start_date": "2026-08-20", "delivery_date": "2026-09-30", "status": "未开始", "tasks": [
            {"name": "原材料准备", "owner": "采购", "start": "2026-08-20", "end": "2026-08-25", "actual": "", "status": "未开始"},
            {"name": "机加工", "owner": "供应商", "start": "2026-08-26", "end": "2026-09-10", "actual": "", "status": "未开始"},
            {"name": "表面处理", "owner": "供应商", "start": "2026-09-11", "end": "2026-09-18", "actual": "", "status": "未开始"},
            {"name": "供应商自检", "owner": "供应商", "start": "2026-09-19", "end": "2026-09-21", "actual": "", "status": "未开始"},
            {"name": "QC 检验", "owner": "QC", "start": "2026-09-22", "end": "2026-09-24", "actual": "", "status": "未开始"},
            {"name": "包装发货", "owner": "PM", "start": "2026-09-25", "end": "2026-09-30", "actual": "", "status": "未开始"},
        ]},
        {"id": 2, "name": "第二批", "quantity": 600, "start_date": "2026-10-10", "delivery_date": "2026-11-20", "status": "未开始", "tasks": [
            {"name": "原材料准备", "owner": "采购", "start": "2026-10-10", "end": "2026-10-15", "actual": "", "status": "未开始"},
            {"name": "机加工", "owner": "供应商", "start": "2026-10-16", "end": "2026-10-31", "actual": "", "status": "未开始"},
            {"name": "表面处理", "owner": "供应商", "start": "2026-11-01", "end": "2026-11-08", "actual": "", "status": "未开始"},
            {"name": "供应商自检", "owner": "供应商", "start": "2026-11-09", "end": "2026-11-11", "actual": "", "status": "未开始"},
            {"name": "QC 检验", "owner": "QC", "start": "2026-11-12", "end": "2026-11-14", "actual": "", "status": "未开始"},
            {"name": "包装发货", "owner": "PM", "start": "2026-11-15", "end": "2026-11-20", "actual": "", "status": "未开始"},
        ]},
    ],
}


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def task_progress(tasks):
    return round(sum(STATUS_SCORE.get(task["status"], 0) for task in tasks) / len(tasks)) if tasks else 0


def can_edit_plan():
    return project["status"] == "草稿" or project["editing_plan"] is True


def can_update_progress():
    return project["status"] == "执行中" and project["editing_plan"] is False


def recalculate_batch(batch):
    score = task_progress(batch["tasks"])
    batch["status"] = "已完成" if score == 100 else ("未开始" if score == 0 else "进行中")


def risk_items():
    today = date.today()
    items = []

    def append_risk(task, group):
        if task.get("status") == "已完成" or not task.get("end"):
            return
        days_left = (parse_date(task["end"]) - today).days
        if days_left > 3:
            return
        level = "逾期" if days_left < 0 else "临期"
        items.append({
            "group": group,
            "task": task["name"],
            "owner": task.get("owner", ""),
            "email": OWNER_EMAILS.get(task.get("owner", ""), ""),
            "end": task["end"],
            "days": abs(days_left),
            "level": level,
        })

    for task in project["pre_tasks"]:
        append_risk(task, "项目准备")
    for batch in project["batches"]:
        for task in batch["tasks"]:
            append_risk(task, batch["name"])
    return sorted(items, key=lambda item: (item["level"] != "逾期", item["end"]))


def project_payload():
    data = deepcopy(project)
    for batch in data["batches"]:
        for task in batch["tasks"]:
            task.setdefault("actual", "")
        batch["progress"] = task_progress(batch["tasks"])
    total = sum(batch["quantity"] for batch in data["batches"]) or 1
    batch_score = sum(batch["quantity"] * batch["progress"] for batch in data["batches"]) / total
    data["pre_progress"] = task_progress(data["pre_tasks"])
    data["progress"] = round(data["pre_progress"] * 0.3 + batch_score * 0.7)
    data["is_split"] = len(data["batches"]) > 1

    data["planned_completion"] = max(
    (
        batch["delivery_date"]
        for batch in data["batches"]
        if batch.get("delivery_date")
    ),
    default=""
)
    
    data["can_edit_plan"] = can_edit_plan()
    data["can_update_progress"] = can_update_progress()
    data["is_readonly"] = data["status"] == "已结项"
    data["risks"] = risk_items()
    data["risk_summary"] = {
        "overdue": sum(item["level"] == "逾期" for item in data["risks"]),
        "due_soon": sum(item["level"] == "临期" for item in data["risks"]),
    }
    return data


def error(message, status=400):
    return jsonify({"error": message}), status


@app.get("/")
def index():
    return render_template("index.html", project=project_payload())


@app.get("/api/project")
def get_project():
    return jsonify(project_payload())


@app.patch("/api/project")
def update_project():
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    payload = request.get_json(force=True)
    for field in ("code", "name", "customer", "product", "pm", "supplier", "note"):
        if field in payload:
            project[field] = str(payload[field]).strip()
    return jsonify({"message": "项目信息已更新"})


@app.post("/api/alerts/send")
def send_alerts():
    risks = risk_items()
    recipients = sorted({item["email"] for item in risks if item["email"]})
    if not risks:
        return error("当前没有需要提醒的临期或逾期节点")
    log = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "risk_count": len(risks),
        "recipient_count": len(recipients),
        "recipients": recipients,
    }
    project["alert_logs"].insert(0, log)
    return jsonify({"message": f"已模拟向 {len(recipients)} 个邮箱发送 {len(risks)} 条风险提醒"})


@app.post("/api/project/confirm")
def confirm_project():
    if project["status"] == "已结项":
        return error("已结项项目不可重新确认", 403)
    was_adjusting = project["editing_plan"]
    project["status"] = "执行中"
    project["editing_plan"] = False
    if was_adjusting:
        project["plan_version"] += 1
    return jsonify({"message": "调整后的计划已确认" if was_adjusting else "计划已确认并进入执行"})


@app.post("/api/project/adjust")
def adjust_project():
    if project["status"] != "执行中" or project["editing_plan"]:
        return error("当前状态不能发起计划调整", 403)
    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason", "")).strip()
    if not reason:
        return error("请填写调整原因")
    project["editing_plan"] = True
    project["change_logs"].append({"version": project["plan_version"], "reason": reason, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return jsonify({"message": "计划已解锁，请修改后重新确认"})


@app.post("/api/project/close")
def close_project():
    if project["status"] != "执行中" or project["editing_plan"]:
        return error("请先确认计划，再进行结项", 403)
    project["status"] = "已结项"
    return jsonify({"message": "项目已结项，全部内容已锁定"})


@app.patch("/api/pre-tasks/<int:task_index>")
def update_pre_task(task_index):
    if task_index < 0 or task_index >= len(project["pre_tasks"]):
        return error("未找到前置节点", 404)
    payload = request.get_json(force=True)
    task = project["pre_tasks"][task_index]
    if any(field in payload for field in {"owner", "start", "end"}) and not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if any(field in payload for field in {"status", "actual"}) and not can_update_progress():
        return error("确认计划后才能更新执行进度", 403)
    if "status" in payload:
        if payload["status"] not in TASK_STATUSES:
            return error("状态无效")
        task["status"] = payload["status"]
    for field in ("owner", "start", "end", "actual"):
        if field in payload:
            task[field] = payload[field]
    return jsonify({"message": "前置节点已更新"})


@app.patch("/api/batches/<int:batch_id>")
def update_batch(batch_id):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    batch = next((item for item in project["batches"] if item["id"] == batch_id), None)
    if not batch:
        return error("未找到批次", 404)
    payload = request.get_json(force=True)
    for field in ("name", "start_date", "delivery_date"):
        if field in payload:
            batch[field] = str(payload[field]).strip()
    if "quantity" in payload:
        quantity = int(payload["quantity"])
        if quantity < 1:
            return error("批次数量必须大于 0")
        batch["quantity"] = quantity
    project["total_quantity"] = sum(item["quantity"] for item in project["batches"])
    return jsonify({"message": "批次信息已更新"})


@app.post("/api/batches/<int:batch_id>/copy")
def copy_batch(batch_id):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    source = next((item for item in project["batches"] if item["id"] == batch_id), None)
    if not source:
        return error("未找到原批次", 404)
    payload = request.get_json(force=True)
    if any(not payload.get(key) for key in ("name", "quantity", "start_date")):
        return error("请填写批次名称、数量和开始日期")
    offset = parse_date(payload["start_date"]) - parse_date(source["start_date"])
    copied = deepcopy(source)
    copied.update(id=max(item["id"] for item in project["batches"]) + 1, name=payload["name"].strip(), quantity=int(payload["quantity"]), start_date=payload["start_date"], delivery_date=(parse_date(source["delivery_date"]) + offset).isoformat(), status="未开始")
    for task in copied["tasks"]:
        task.update(start=(parse_date(task["start"]) + offset).isoformat(), end=(parse_date(task["end"]) + offset).isoformat(), actual="", status="未开始")
    project["batches"].append(copied)
    project["total_quantity"] = sum(item["quantity"] for item in project["batches"])
    return jsonify({"message": "批次复制成功"}), 201


@app.delete("/api/batches/<int:batch_id>")
def delete_batch(batch_id):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if len(project["batches"]) <= 1:
        return error("项目至少保留一个生产交付计划")
    before = len(project["batches"])
    project["batches"] = [item for item in project["batches"] if item["id"] != batch_id]
    if len(project["batches"]) == before:
        return error("未找到批次", 404)
    project["total_quantity"] = sum(item["quantity"] for item in project["batches"])
    return jsonify({"message": "批次已删除"})


@app.patch("/api/batches/<int:batch_id>/tasks/<int:task_index>")
def update_task(batch_id, task_index):
    batch = next((item for item in project["batches"] if item["id"] == batch_id), None)
    if not batch or task_index < 0 or task_index >= len(batch["tasks"]):
        return error("未找到生产节点", 404)
    payload = request.get_json(force=True)
    task = batch["tasks"][task_index]
    if any(field in payload for field in {"owner", "start", "end"}) and not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if any(field in payload for field in {"status", "actual"}) and not can_update_progress():
        return error("确认计划后才能更新执行进度", 403)
    if "status" in payload:
        if payload["status"] not in TASK_STATUSES:
            return error("状态无效")
        task["status"] = payload["status"]
    for field in ("owner", "start", "end", "actual"):
        if field in payload:
            task[field] = payload[field]
    recalculate_batch(batch)
    return jsonify({"message": "生产节点已更新"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
