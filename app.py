from copy import deepcopy
from datetime import date, datetime
from getpass import getuser

from flask import Flask, jsonify, render_template, request


app = Flask(__name__)
TASK_STATUSES = ("未开始", "进行中", "已完成")
STATUS_SCORE = {"未开始": 0, "进行中": 50, "已完成": 100}
project = {
    "code": "YC-2026-018", "name": "HK125C 定制零件生产交付", "customer": "示例客户",
    "product": "HK125C", "creator": getuser(),
    "created_date": date.today().isoformat(), "launch_date": "2026-08-05",
    "promised_delivery_date": "2026-11-20",
    "status": "草稿", "plan_version": 1, "editing_plan": False, "active_adjustment_reason": "", "change_logs": [],
    "note": "",
    "tasks": [
        {"name": "图纸发布", "owner": "ME", "start": "2026-08-05", "end": "2026-08-08", "actual": "", "status": "未开始", "children": []},
        {"name": "派单", "owner": "PM", "start": "2026-08-09", "end": "2026-08-10", "actual": "", "status": "未开始", "children": []},
        {"name": "样品制造", "owner": "供应商", "start": "2026-08-11", "end": "2026-08-20", "actual": "", "status": "未开始", "children": []},
        {"name": "样品质检&交付", "owner": "QC", "start": "2026-08-21", "end": "2026-08-24", "actual": "", "status": "未开始", "children": []},
        {"name": "样品客户反馈", "owner": "PM", "start": "2026-08-25", "end": "2026-08-28", "actual": "", "status": "未开始", "children": []},
        {"name": "大货制造", "owner": "供应商", "start": "2026-08-29", "end": "2026-09-20", "actual": "", "status": "未开始", "children": [
            {"name": "第一批", "description": "首批大货制造与进度跟进", "owner": "供应商", "start": "2026-08-29", "end": "2026-09-20", "actual": "", "status": "未开始"}
        ]},
        {"name": "大货质检&交付", "owner": "QC", "start": "2026-09-21", "end": "2026-09-30", "actual": "", "status": "未开始", "children": []},
        {"name": "大货客户反馈", "owner": "PM", "start": "2026-10-01", "end": "2026-10-08", "actual": "", "status": "未开始", "children": []},
    ],
}


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def task_progress(tasks):
    return round(sum(STATUS_SCORE.get(task["status"], 0) for task in tasks) / len(tasks)) if tasks else 0


def scheduled_progress(task):
    """进行中的任务按今天在计划周期内所处的位置计算进度。"""
    if task.get("status") == "已完成":
        return 100
    if task.get("status") != "进行中":
        return 0
    try:
        start = parse_date(task["start"])
        end = parse_date(task["end"])
    except (KeyError, TypeError, ValueError):
        return 50
    if end < start:
        return 50
    now = datetime.now()
    start_time = datetime.combine(start, datetime.min.time())
    end_time = datetime.combine(end, datetime.max.time())
    if now <= start_time:
        return 0
    if now >= end_time:
        return 99
    duration = (end_time - start_time).total_seconds()
    elapsed = (now - start_time).total_seconds()
    return max(1, min(99, round(elapsed / duration * 100)))


def can_edit_plan():
    return project["status"] == "草稿" or project["editing_plan"] is True


def can_update_progress():
    return project["status"] == "执行中" and project["editing_plan"] is False


FIELD_LABELS = {
    "code": "项目编号", "name": "名称", "customer": "客户", "product": "产品型号",
    "note": "项目备注", "launch_date": "启动日期",
    "promised_delivery_date": "承诺交付日期", "description": "任务描述",
    "owner": "负责人", "start": "计划开始", "end": "计划完成",
    "actual": "实际完成", "status": "状态", "order": "任务顺序",
}


def record_change(scope, field, old_value, new_value):
    """计划调整期间记录字段级变更，草稿阶段不生成审计日志。"""
    if project["status"] != "执行中" or not project["editing_plan"] or old_value == new_value:
        return
    project["change_logs"].append({
        "type": "change", "version": project["plan_version"],
        "reason": project.get("active_adjustment_reason", ""),
        "scope": scope, "field": FIELD_LABELS.get(field, field),
        "old": old_value or "—", "new": new_value or "—",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


def sync_parent_schedule(parent):
    """有具体任务时，一级任务日期取子任务最早开始和最晚完成。"""
    children = parent.get("children", [])
    starts = [child["start"] for child in children if child.get("start")]
    ends = [child["end"] for child in children if child.get("end")]
    if not starts or not ends:
        return
    new_start, new_end = min(starts), max(ends)
    if parent.get("start") != new_start:
        record_change(f"一级任务 · {parent['name']}", "start", parent.get("start", ""), new_start)
        parent["start"] = new_start
    if parent.get("end") != new_end:
        record_change(f"一级任务 · {parent['name']}", "end", parent.get("end", ""), new_end)
        parent["end"] = new_end


def sync_parent_status(parent):
    """一级任务状态由具体任务汇总，并在全部完成时同步实际完成日期。"""
    children = parent.get("children", [])
    if not children:
        return
    statuses = [child.get("status", "未开始") for child in children]
    if all(status == "未开始" for status in statuses):
        new_status = "未开始"
    elif all(status == "已完成" for status in statuses):
        new_status = "已完成"
    else:
        new_status = "进行中"
    if parent.get("status") != new_status:
        record_change(f"一级任务 · {parent['name']}", "status", parent.get("status", ""), new_status)
        parent["status"] = new_status
    completed_dates = [child.get("actual") for child in children if child.get("actual")]
    new_actual = max(completed_dates) if new_status == "已完成" and len(completed_dates) == len(children) else ""
    if parent.get("actual", "") != new_actual:
        record_change(f"一级任务 · {parent['name']}", "actual", parent.get("actual", ""), new_actual)
        parent["actual"] = new_actual


def project_payload():
    data = deepcopy(project)
    for task in data["tasks"]:
        children = task.get("children", [])
        for child in children:
            child["progress"] = scheduled_progress(child)
        task["progress"] = round(sum(child["progress"] for child in children) / len(children)) if children else scheduled_progress(task)
    actual_scores = []
    for task in data["tasks"]:
        children = task.get("children", [])
        actual_scores.append(task_progress(children) if children else STATUS_SCORE.get(task["status"], 0))
    data["task_progress"] = round(sum(actual_scores) / len(actual_scores)) if actual_scores else 0
    data["progress"] = data["task_progress"]
    data["can_edit_plan"] = can_edit_plan()
    data["can_update_progress"] = can_update_progress()
    data["is_readonly"] = data["status"] == "已结项"
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
    for field in (
        "code", "name", "customer", "product", "note",
        "launch_date", "promised_delivery_date",
    ):
        if field in payload:
            new_value = str(payload[field]).strip()
            record_change("项目资料", field, project.get(field, ""), new_value)
            project[field] = new_value
    return jsonify({"message": "项目信息已更新"})


@app.patch("/api/tasks/<int:task_index>")
def update_macro_task(task_index):
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    payload = request.get_json(force=True)
    task = project["tasks"][task_index]
    if any(field in payload for field in {"name", "owner", "start", "end"}) and not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if any(field in payload for field in {"status", "actual"}) and not can_update_progress():
        return error("确认计划后才能更新执行进度", 403)
    if "status" in payload and payload["status"] not in TASK_STATUSES:
        return error("状态无效")
    if payload.get("status") == "已完成" and not (payload.get("actual") or task.get("actual")):
        return error("请先选择实际完成日期，再将状态更新为已完成")
    if payload.get("actual") and task.get("start") and payload["actual"] < task["start"]:
        return error("实际完成日期不能早于计划开始日期")
    for field in ("name", "owner", "start", "end", "actual", "status"):
        if field in payload:
            new_value = str(payload[field]).strip()
            record_change(f"一级任务 · {task['name']}", field, task.get(field, ""), new_value)
            task[field] = new_value
    if payload.get("actual") and task["status"] != "已完成":
        record_change(f"一级任务 · {task['name']}", "status", task["status"], "已完成")
        task["status"] = "已完成"
    elif "actual" in payload and not payload["actual"] and task["status"] == "已完成":
        record_change(f"一级任务 · {task['name']}", "status", "已完成", "进行中")
        task["status"] = "进行中"
    return jsonify({"message": "一级任务已更新"})


@app.post("/api/tasks")
def add_macro_task():
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    payload = request.get_json(silent=True) or {}
    required = {"name": "任务名", "start": "计划开始日期", "end": "计划完成日期", "owner": "负责人"}
    missing = [label for field, label in required.items() if not str(payload.get(field, "")).strip()]
    if missing:
        return error(f"请填写：{'、'.join(missing)}")
    if payload["end"] < payload["start"]:
        return error("计划完成日期不能早于计划开始日期")
    task = {
        "name": str(payload.get("name") or "新一级任务").strip(),
        "owner": str(payload.get("owner") or "").strip(),
        "start": str(payload.get("start") or "").strip(),
        "end": str(payload.get("end") or "").strip(),
        "actual": "", "status": "未开始", "children": [],
    }
    raw_position = payload.get("position", len(project["tasks"]))
    try:
        position = max(0, min(int(raw_position), len(project["tasks"])))
    except (TypeError, ValueError):
        return error("插入位置无效")
    project["tasks"].insert(position, task)
    record_change("项目任务总览", "name", "—", task["name"])
    return jsonify({"message": "一级任务已增加"}), 201


@app.delete("/api/tasks/<int:task_index>")
def delete_macro_task(task_index):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    removed = project["tasks"].pop(task_index)
    record_change("项目任务总览", "name", removed["name"], "已删除")
    return jsonify({"message": "一级任务已删除"})


@app.post("/api/tasks/<int:task_index>/move")
def move_macro_task(task_index):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    payload = request.get_json(silent=True) or {}
    if "position" in payload:
        try:
            target = int(payload["position"]) - 1
        except (TypeError, ValueError):
            return error("目标序号无效")
    else:
        direction = payload.get("direction")
        target = task_index - 1 if direction == "up" else task_index + 1 if direction == "down" else -1
    if target < 0 or target >= len(project["tasks"]):
        return error(f"序号必须在 1 至 {len(project['tasks'])} 之间")
    if target == task_index:
        return jsonify({"message": "任务顺序未变化"})
    task_name = project["tasks"][task_index]["name"]
    moving_task = project["tasks"].pop(task_index)
    project["tasks"].insert(target, moving_task)
    record_change(f"一级任务 · {task_name}", "order", f"第 {task_index + 1} 位", f"第 {target + 1} 位")
    return jsonify({"message": "任务顺序已调整"})


@app.post("/api/tasks/<int:task_index>/children")
def add_child_task(task_index):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    payload = request.get_json(silent=True) or {}
    required = {"name": "任务名", "description": "任务描述", "start": "计划开始日期", "end": "计划完成日期", "owner": "负责人"}
    missing = [label for field, label in required.items() if not str(payload.get(field, "")).strip()]
    if missing:
        return error(f"请填写：{'、'.join(missing)}")
    if payload["end"] < payload["start"]:
        return error("计划完成日期不能早于计划开始日期")
    parent = project["tasks"][task_index]
    child = {
        "name": str(payload.get("name") or "新任务").strip(),
        "description": str(payload.get("description") or "").strip(),
        "owner": str(payload.get("owner") or "").strip(),
        "start": str(payload.get("start") or "").strip(),
        "end": str(payload.get("end") or "").strip(),
        "actual": "", "status": "未开始",
    }
    parent["children"].append(child)
    record_change(f"{parent['name']} · 具体任务", "name", "—", child["name"])
    sync_parent_schedule(parent)
    sync_parent_status(parent)
    return jsonify({"message": "具体任务已增加"}), 201


@app.patch("/api/tasks/<int:task_index>/children/<int:child_index>")
def update_child_task(task_index, child_index):
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    children = project["tasks"][task_index]["children"]
    if child_index < 0 or child_index >= len(children):
        return error("未找到二级任务", 404)
    payload = request.get_json(force=True)
    if any(field in payload for field in {"name", "description", "owner", "start", "end"}) and not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if any(field in payload for field in {"status", "actual"}) and not can_update_progress():
        return error("确认计划后才能更新执行进度", 403)
    if "status" in payload and payload["status"] not in TASK_STATUSES:
        return error("状态无效")
    child = children[child_index]
    if payload.get("status") == "已完成" and not (payload.get("actual") or child.get("actual")):
        return error("请先选择实际完成日期，再将状态更新为已完成")
    if payload.get("actual") and child.get("start") and payload["actual"] < child["start"]:
        return error("实际完成日期不能早于计划开始日期")
    proposed_start = str(payload.get("start", child.get("start", ""))).strip()
    proposed_end = str(payload.get("end", child.get("end", ""))).strip()
    if proposed_start and proposed_end and proposed_end < proposed_start:
        return error("计划完成日期不能早于计划开始日期")
    for field in ("name", "description", "owner", "start", "end", "actual", "status"):
        if field in payload:
            new_value = str(payload[field]).strip()
            record_change(f"{project['tasks'][task_index]['name']} · {child['name']}", field, child.get(field, ""), new_value)
            child[field] = new_value
    if payload.get("actual") and child["status"] != "已完成":
        record_change(f"{project['tasks'][task_index]['name']} · {child['name']}", "status", child["status"], "已完成")
        child["status"] = "已完成"
    elif "actual" in payload and not payload["actual"] and child["status"] == "已完成":
        record_change(f"{project['tasks'][task_index]['name']} · {child['name']}", "status", "已完成", "进行中")
        child["status"] = "进行中"
    if "start" in payload or "end" in payload:
        sync_parent_schedule(project["tasks"][task_index])
    sync_parent_status(project["tasks"][task_index])
    return jsonify({"message": "具体任务已更新"})


@app.delete("/api/tasks/<int:task_index>/children/<int:child_index>")
def delete_child_task(task_index, child_index):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    parent = project["tasks"][task_index]
    if child_index < 0 or child_index >= len(parent["children"]):
        return error("未找到具体任务", 404)
    removed = parent["children"].pop(child_index)
    record_change(f"{parent['name']} · 具体任务", "name", removed["name"], "已删除")
    sync_parent_schedule(parent)
    sync_parent_status(parent)
    return jsonify({"message": "具体任务已删除"})


@app.post("/api/tasks/<int:task_index>/children/<int:child_index>/copy")
def copy_child_task(task_index, child_index):
    if not can_edit_plan():
        return error("计划已锁定，请先点击“调整计划”", 403)
    if task_index < 0 or task_index >= len(project["tasks"]):
        return error("未找到一级任务", 404)
    task = project["tasks"][task_index]
    if task["name"] != "大货制造":
        return error("仅大货制造任务支持复制批次")
    children = task["children"]
    if child_index < 0 or child_index >= len(children):
        return error("未找到二级任务", 404)
    copied = deepcopy(children[child_index])
    copy_number = len(children) + 1
    chinese_numbers = {2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
    copied.update(name=f"第{chinese_numbers.get(copy_number, copy_number)}批", actual="", status="未开始")
    children.append(copied)
    record_change(f"{task['name']} · 具体任务", "name", "—", copied["name"])
    sync_parent_schedule(task)
    sync_parent_status(task)
    return jsonify({"message": "批次任务已复制"}), 201


@app.post("/api/project/confirm")
def confirm_project():
    if project["status"] == "已结项":
        return error("已结项项目不可重新确认", 403)
    was_adjusting = project["editing_plan"]
    project["status"] = "执行中"
    project["editing_plan"] = False
    project["active_adjustment_reason"] = ""
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
    project["active_adjustment_reason"] = reason
    project["change_logs"].append({"type": "adjustment", "version": project["plan_version"], "reason": reason, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return jsonify({"message": "计划已解锁，请修改后重新确认"})


@app.post("/api/project/close")
def close_project():
    if project["status"] != "执行中" or project["editing_plan"]:
        return error("请先确认计划，再进行结项", 403)
    project["status"] = "已结项"
    return jsonify({"message": "项目已结项，全部内容已锁定"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
