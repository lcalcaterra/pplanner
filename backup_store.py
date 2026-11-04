"""Versioned Pplanner backups. Only data is imported; never executable SQL."""
import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from uuid import uuid4

FORMAT = "pplanner-backup"
VERSION = 1
MAX_BYTES = 64 * 1024 * 1024

def quoted(name):
    return '"' + name.replace('"', '""') + '"'

def tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")] + ["sqlite_sequence"]

def snapshot(db):
    return {"format": FORMAT, "version": VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "tables": {name: [dict(row) for row in db.execute("SELECT * FROM " + quoted(name))] for name in tables(db)}}

def encode(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")

def insert_rows(db, data):
    for name in tables(db):
        db.execute("DELETE FROM " + quoted(name))
    # Clear sequences again after cascades, then restore them after all records.
    for name in tables(db):
        if name == "sqlite_sequence":
            continue
        columns = [r["name"] for r in db.execute("PRAGMA table_info(" + quoted(name) + ")")]
        sql = "INSERT INTO " + quoted(name) + " (" + ",".join(map(quoted, columns)) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
        db.executemany(sql, [tuple(row[c] for c in columns) for row in data[name]])
    db.execute("DELETE FROM sqlite_sequence")
    db.executemany("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", [(r["name"], r["seq"]) for r in data["sqlite_sequence"]])

def check_semantics(db):
    projects = {r["id"]: r for r in db.execute("SELECT * FROM projects")}
    tasks = {r["id"]: r for r in db.execute("SELECT * FROM project_tasks")}
    phases = {r["id"]: r for r in db.execute("SELECT * FROM project_phases")}
    for p in projects.values():
        if p["status"] not in ("active","suspended","completed","rejected","closed") or not re.fullmatch(r"#[0-9a-fA-F]{6}",p["color"]):
            raise ValueError("Invalid project status or color.")
    for task in tasks.values():
        if task["status"] not in ("open","locked","update-required","loading","completed") or task["priority"] not in ("none","high","medium","low") or task["completed"] != int(task["status"] == "completed"):
            raise ValueError("Invalid activity status or priority.")
        if task["phase_id"] is not None and phases[task["phase_id"]]["project_id"] != task["project_id"]:
            raise ValueError("Task phase belongs to another project.")
        seen = {task["id"]}
        parent = task["parent_id"]
        while parent is not None:
            if parent in seen or tasks[parent]["project_id"] != task["project_id"]:
                raise ValueError("Invalid task hierarchy.")
            seen.add(parent)
            parent = tasks[parent]["parent_id"]
        for field in ("start_date","end_date"):
            if task[field] is not None:
                valid_date(task[field])
    for note in db.execute("SELECT * FROM notes"):
        valid_date(note["date"])
        if date.fromisoformat(note["date"]).weekday() > 4 or note["completed"] not in (0,1):
            raise ValueError("Invalid note date or completion.")
    for table in ("notes","comments","projects","project_tasks","project_comments"):
        for row in db.execute("SELECT * FROM " + quoted(table)):
            datetime.fromisoformat(row["created_at"].replace("Z","+00:00"))
            for field in ("body","title","name"):
                if field in row.keys() and not row[field].strip():
                    raise ValueError("Empty title or text in backup.")
            for field in ("body","description"):
                if field in row.keys() and len(row[field]) > 10000:
                    raise ValueError("Text exceeds the supported length.")
    for row in db.execute("SELECT * FROM project_comments WHERE task_id IS NOT NULL"):
        if tasks[row["task_id"]]["project_id"] != row["project_id"]:
            raise ValueError("Comment belongs to another project.")
    for table in ("note_tags","task_tags","project_tags"):
        for row in db.execute("SELECT name,value FROM " + table):
            if not row["name"].strip() or not row["value"].strip() or len(row["name"])>80 or len(row["value"])>200 or any(c in row["name"]+row["value"] for c in "\r\n"):
                raise ValueError("Invalid tags.")
    for row in db.execute("SELECT value FROM app_state WHERE key='rollover_week'"):
        valid_date(row[0])
        if date.fromisoformat(row[0]).weekday() != 0:
            raise ValueError("Invalid rollover state.")
    for seq in db.execute("SELECT * FROM sqlite_sequence"):
        if seq["name"] not in tables(db) or seq["name"] == "sqlite_sequence" or seq["seq"] < 0:
            raise ValueError("Invalid ID sequence.")
    if db.execute("SELECT name FROM sqlite_sequence GROUP BY name HAVING count(*)>1").fetchone():
        raise ValueError("Duplicate ID sequence.")

def valid_date(value):
    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
        raise ValueError("Invalid date in backup.")

def validate(db, payload):
    if not isinstance(payload,dict) or payload.get("format") != FORMAT or type(payload.get("version")) is not int or payload["version"] != VERSION:
        raise ValueError("Choose a Pplanner export file with a supported backup version.")
    data = payload.get("tables")
    if not isinstance(data,dict) or set(data) != set(tables(db)):
        raise ValueError("Backup is incomplete or uses a different database version.")
    for name in tables(db):
        columns = list(db.execute("PRAGMA table_info(" + quoted(name) + ")"))
        if not isinstance(data[name],list):
            raise ValueError("Invalid backup table.")
        for row in data[name]:
            if not isinstance(row,dict) or set(row) != {c["name"] for c in columns}:
                raise ValueError("Backup columns do not match this Pplanner version.")
            for col in columns:
                value = row[col["name"]]
                if value is None:
                    if col["notnull"] or col["pk"]:
                        raise ValueError("Missing required backup value.")
                elif col["type"].upper() == "INTEGER" or (name=="sqlite_sequence" and col["name"]=="seq"):
                    if type(value) is not int or not -(2**63) <= value < 2**63:
                        raise ValueError("Invalid integer in backup.")
                elif not isinstance(value,str):
                    raise ValueError("Invalid text in backup.")
                if col["name"]=="id" and (type(value) is not int or value<1):
                    raise ValueError("Invalid record ID.")
    # Reconstruct only the installed schema in memory; no uploaded SQL is run.
    with sqlite3.connect(":memory:") as check:
        check.row_factory = sqlite3.Row
        check.execute("PRAGMA foreign_keys=ON")
        schema = [r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL")]
        for statement in schema:
            check.execute(statement)
        check.execute("BEGIN")
        check.execute("PRAGMA defer_foreign_keys=ON")
        try:
            insert_rows(check,data)
            if check.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Backup contains broken record links.")
            check_semantics(check)
        except (sqlite3.Error, KeyError, TypeError, OverflowError) as exc:
            raise ValueError("Backup contains invalid or inconsistent records.") from exc
    return data

def restore(db, payload, directory):
    data = validate(db,payload)
    db.execute("BEGIN IMMEDIATE")
    # The write lock prevents another request from changing data between backup
    # and replacement. Save a Pplanner-format recovery file before any deletion.
    directory.mkdir(parents=True,exist_ok=True)
    path = directory / ("before-import-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8] + ".pplanner")
    try:
        with path.open("xb") as file:
            file.write(encode(snapshot(db)))
            file.flush()
            os.fsync(file.fileno())
        db.execute("PRAGMA defer_foreign_keys=ON")
        insert_rows(db,data)
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup contains broken record links.")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return path.name
