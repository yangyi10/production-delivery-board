from copy import deepcopy
from datetime import datetime

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
STATUS_SCORE = {"未开始": 0, "进行中": 50, "已完成": 100}

project = {
    "code": "YC-2026-018", "name": "HK125C 定制零件生产交付", "customer": "示例客户",
    "product": "HK125C", "total_quantity": 1000, "pm": "Nora", "supplier": "上海精密制造",
    "pre_tasks": [
        {"name": "订单评审", "owner": "PM", "plan": "2026-08-06", "actual": "2026-08-06", "status": "已完成", "gate": "G3"},
        {"name": "生产图纸/规范", "owner": "ME", "plan": "2026-08-08", "actual": "2026-08-08", "status": "已完成", "gate": ""},
        {"name": "询盘发布", "owner": "采购/PM", "plan": "2026-08-10", "actual": "2026-08-10", "status": "已完成", "gate": ""},
        {"name": "供应商定标", "owner": "采购", "plan": "2026-08-13", "actual": "", "status": "进行中", "gate": ""},
        {"name": "供应商 PO", "owner": "采购", "plan": "2026-08-15", "actual": "", "status": "未开始", "gate": ""},
        {"name": "派单会/开工会", "owner": "PM", "plan": "2026-08-18", "actual": "", "status": "未开始", "gate": "G4"},
    ],
    "batches": [
        {"id": 1, "name": "第一批", "quantity": 400, "start_date": "2026-08-20", "delivery_date": "2026-09-30", "status": "进行中", "tasks": [
            {"name": "原材料准备", "owner": "采购", "start": "2026-08-20", "end": "2026-08-25", "status": "已完成"},
            {"name": "机加工", "owner": "供应商", "start": "2026-08-26", "end": "2026-09-10", "status": "已完成"},
            {"name": "表面处理", "owner": "供应商", "start": "2026-09-11", "end": "2026-09-18", "status": "进行中"},
            {"name": "供应商自检", "owner": "供应商", "start": "2026-09-19", "end": "2026-09-21", "status": "未开始"},
            {"name": "QC 检验", "owner": "QC", "start": "2026-09-22", "end": "2026-09-24", "status": "未开始"},
            {"name": "包装发货", "owner": "PM", "start": "2026-09-25", "end": "2026-09-30", "status": "未开始"},
        ]},
        {"id": 2, "name": "第二批", "quantity": 600, "start_date": "2026-10-10", "delivery_date": "2026-11-20", "status": "未开始", "tasks": [
            {"name": "原材料准备", "owner": "采购", "start": "2026-10-10", "end": "2026-10-15", "status": "未开始"},
            {"name": "机加工", "owner": "供应商", "start": "2026-10-16", "end": "2026-10-31", "status": "未开始"},
            {"name": "表面处理", "owner": "供应商", "start": "2026-11-01", "end": "2026-11-08", "status": "未开始"},
            {"name": "供应商自检", "owner": "供应商", "start": "2026-11-09", "end": "2026-11-11", "status": "未开始"},
            {"name": "QC 检验", "owner": "QC", "start": "2026-11-12", "end": "2026-11-14", "status": "未开始"},
            {"name": "包装发货", "owner": "PM", "start": "2026-11-15", "end": "2026-11-20", "status": "未开始"},
        ]},
    ],
}

def parse_date(value): return datetime.strptime(value, "%Y-%m-%d").date()
def task_progress(tasks): return round(sum(STATUS_SCORE.get(t["status"], 0) for t in tasks) / len(tasks)) if tasks else 0

def project_payload():
    data = deepcopy(project)
    for batch in data["batches"]: batch["progress"] = task_progress(batch["tasks"])
    total = sum(b["quantity"] for b in data["batches"]) or 1
    batch_score = sum(b["quantity"] * b["progress"] for b in data["batches"]) / total
    data["pre_progress"] = task_progress(data["pre_tasks"])
    data["progress"] = round(data["pre_progress"] * .3 + batch_score * .7)
    data["is_split"] = len(data["batches"]) > 1
    return data

@app.get("/")
def index(): return render_template("index.html", project=project_payload())

@app.get("/api/project")
def get_project(): return jsonify(project_payload())

@app.patch("/api/pre-tasks/<int:task_index>")
def update_pre_task(task_index):
    if task_index < 0 or task_index >= len(project["pre_tasks"]):
        return jsonify({"error": "未找到前置节点"}), 404

    payload = request.get_json(force=True)
    task = project["pre_tasks"][task_index]

    if "status" in payload:
        if payload["status"] not in STATUS_SCORE:
            return jsonify({"error": "状态无效"}), 400
        task["status"] = payload["status"]

    if "owner" in payload:
        task["owner"] = payload["owner"]

    if "plan" in payload:
        task["plan"] = payload["plan"]

    if "actual" in payload:
        task["actual"] = payload["actual"]

    return jsonify({
        "message": "前置节点已更新",
        "task": task
    })

@app.post("/api/batches/<int:batch_id>/copy")
def copy_batch(batch_id):
    source = next((b for b in project["batches"] if b["id"] == batch_id), None)
    if not source: return jsonify({"error": "未找到原批次"}), 404
    payload = request.get_json(force=True)
    if any(not payload.get(k) for k in ("name", "quantity", "start_date")): return jsonify({"error": "请填写批次名称、数量和开始日期"}), 400
    offset = parse_date(payload["start_date"]) - parse_date(source["start_date"])
    copied = deepcopy(source)
    copied.update(id=max(b["id"] for b in project["batches"]) + 1, name=payload["name"], quantity=int(payload["quantity"]), start_date=payload["start_date"], delivery_date=(parse_date(source["delivery_date"]) + offset).isoformat(), status="未开始")
    for task in copied["tasks"]: task.update(start=(parse_date(task["start"]) + offset).isoformat(), end=(parse_date(task["end"]) + offset).isoformat(), status="未开始")
    project["batches"].append(copied); project["total_quantity"] = sum(b["quantity"] for b in project["batches"])
    return jsonify({"message": "批次复制成功", "batch": copied}), 201

@app.delete("/api/batches/<int:batch_id>")
def delete_batch(batch_id):
    if len(project["batches"]) <= 1: return jsonify({"error": "项目至少保留一个生产交付计划"}), 400
    before = len(project["batches"]); project["batches"] = [b for b in project["batches"] if b["id"] != batch_id]
    if len(project["batches"]) == before: return jsonify({"error": "未找到批次"}), 404
    project["total_quantity"] = sum(b["quantity"] for b in project["batches"])
    return jsonify({"message": "批次已删除"})

@app.patch("/api/batches/<int:batch_id>/tasks/<int:task_index>")
def update_task(batch_id, task_index):
    batch = next(
        (item for item in project["batches"] if item["id"] == batch_id),
        None
    )

    if not batch or task_index < 0 or task_index >= len(batch["tasks"]):
        return jsonify({"error": "未找到任务"}), 404

    payload = request.get_json(force=True)
    task = batch["tasks"][task_index]

    if "status" in payload:
        if payload["status"] not in STATUS_SCORE:
            return jsonify({"error": "状态无效"}), 400
        task["status"] = payload["status"]

    if "owner" in payload:
        task["owner"] = payload["owner"]

    if "start" in payload:
        task["start"] = payload["start"]

    if "end" in payload:
        task["end"] = payload["end"]

    score = task_progress(batch["tasks"])

    if score == 100:
        batch["status"] = "已完成"
    elif score == 0:
        batch["status"] = "未开始"
    else:
        batch["status"] = "进行中"

    return jsonify({
        "message": "生产节点已更新",
        "task": task
    })

if __name__ == "__main__": app.run(debug=True, port=5000)
