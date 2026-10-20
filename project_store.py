"""Project/task persistence and API. No external dependencies."""
from datetime import date
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

PROJECT_STATUSES = ("active", "suspended", "completed", "rejected", "closed")

def valid_status(value):
    if not isinstance(value, str) or value not in PROJECT_STATUSES:
        raise ValueError("Status must be active, suspended, completed, rejected, or closed.")
    return value

def migrate(db):
    columns={record["name"] for record in db.execute("PRAGMA table_info(projects)")}
    if "status" not in columns:
        db.execute("ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended','completed','rejected','closed'))")


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL DEFAULT '#65518c',
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS project_phases (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 name TEXT NOT NULL,
 UNIQUE(project_id,name)
);
CREATE TABLE IF NOT EXISTS project_tasks (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 parent_id INTEGER REFERENCES project_tasks(id) ON DELETE CASCADE,
 phase_id INTEGER REFERENCES project_phases(id) ON DELETE SET NULL,
 title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 start_date TEXT,
 end_date TEXT,
 completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK(start_date IS NULL OR end_date IS NULL OR start_date <= end_date)
);
CREATE INDEX IF NOT EXISTS tasks_project_parent ON project_tasks(project_id,parent_id);
CREATE TABLE IF NOT EXISTS task_notes (
 task_id INTEGER NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
 note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
 PRIMARY KEY(task_id,note_id)
);
CREATE TABLE IF NOT EXISTS task_checkpoints (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 task_id INTEGER NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1))
);
CREATE INDEX IF NOT EXISTS checkpoints_task ON task_checkpoints(task_id,id);
"""

def text(value, label, maximum=10000, required=False):
    if not isinstance(value,str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"{label} must contain {'1' if required else '0'} to {maximum} characters.")
    return value.strip()

def identifier(value):
    if type(value) is not int or value < 1:
        raise ValueError("Use a valid numeric ID.")
    return value

def row(db, table, value):
    # Table names are internal constants, never request input.
    found = db.execute(f"SELECT * FROM {table} WHERE id = ?",(identifier(value),)).fetchone()
    if found is None:
        raise LookupError("Item not found.")
    item=dict(found)
    return metadata(db,item,"project") if table=="projects" else metadata(db,item,"task") if table=="project_tasks" else item

def task_rows(db, project_id=None):
    sql = """SELECT t.*, p.name AS project_name, p.color AS project_color,
             ph.name AS phase_name FROM project_tasks t
             JOIN projects p ON p.id=t.project_id LEFT JOIN project_phases ph ON ph.id=t.phase_id"""
    return [metadata(db,dict(r),"task") for r in db.execute(sql + (" WHERE t.project_id = ?" if project_id else "") + " ORDER BY t.id DESC", (project_id,) if project_id else ())]

def read(db, path, query):
    parts = path.strip("/").split("/")
    if path == "/api/projects":
        return {"projects":[metadata(db,dict(r),"project") for r in db.execute("SELECT * FROM projects ORDER BY id DESC")]}
    if len(parts)==4 and parts[1]=="projects" and parts[2].isdigit() and parts[3]=="comments":
        raw=query.get("task_id",[""])[0]
        return {"comments":discussion(db,int(parts[2]),identifier(int(raw)) if raw else None)}
    if path == "/api/timeline":
        raw = query.get("project_id",[""])[0]
        project_id = identifier(int(raw)) if raw else None
        if project_id:
            row(db,"projects",project_id)
        return {"projects":[dict(r) for r in db.execute("SELECT * FROM projects ORDER BY id")], "tasks":task_rows(db,project_id)}
    if len(parts)==3 and parts[1] in ("projects","tasks") and parts[2].isdigit():
        item_id = int(parts[2])
        if parts[1]=="projects":
            return {"project":row(db,"projects",item_id), "comments":discussion(db,item_id,None), "tasks":task_rows(db,item_id),
                    "phases":[dict(r) for r in db.execute("SELECT * FROM project_phases WHERE project_id=? ORDER BY id",(item_id,))]}
        task = row(db,"project_tasks",item_id)
        return {"task":task,
                "comments":discussion(db,task["project_id"],item_id),
                "subtasks":[metadata(db,dict(r),"task") for r in db.execute("SELECT * FROM project_tasks WHERE parent_id=? ORDER BY id",(item_id,))],
                "notes":[dict(r) for r in db.execute("SELECT n.* FROM notes n JOIN task_notes l ON l.note_id=n.id WHERE l.task_id=? ORDER BY n.date DESC,n.id DESC",(item_id,))],
                "checkpoints":[dict(r) for r in db.execute("SELECT * FROM task_checkpoints WHERE task_id=? ORDER BY id",(item_id,))]}
    raise LookupError("Not found.")

def schedule(payload):
    values=[]
    for field in ("start_date","end_date"):
        value=payload.get(field)
        if value is None or value=="":
            values.append(None)
            continue
        try:
            if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
                raise ValueError()
        except (ValueError,TypeError):
            raise ValueError(f"Use a valid {field.replace('_',' ')} in YYYY-MM-DD format.")
        values.append(value)
    start,end=values
    if start is not None and end is not None and start>end:
        raise ValueError("Start date must be on or before end date.")
    return start,end

def write(db,path,payload):
    if path=="/api/projects":
        name=text(payload.get("name"),"Project name",120,True)
        description=text(payload.get("description",""),"Description")
        tags=tag_pairs(payload.get("tags",[]))
        status=valid_status(payload.get("status","active"))
        color=payload.get("color","#65518c")
        if not isinstance(color,str) or not re.fullmatch(r"#[0-9a-fA-F]{6}",color):
            raise ValueError("Choose a valid hex project color.")
        cursor=db.execute("INSERT INTO projects(name,description,color,status) VALUES (?,?,?,?)",(name,description,color,status))
        store_tags(db,"project",cursor.lastrowid,tags)
        return 201,{"project":row(db,"projects",cursor.lastrowid)}
    if path=="/api/tasks":
        project_id=identifier(payload.get("project_id"))
        row(db,"projects",project_id)
        parent_id=payload.get("parent_id")
        if parent_id is not None:
            parent=row(db,"project_tasks",parent_id)
            if parent["project_id"]!=project_id:
                raise ValueError("A subtask must belong to its parent's project.")
        tags=tag_pairs(payload.get("tags",[]),task=True)
        title=text(payload.get("title"),"Task title",200,True)
        description=text(payload.get("description",""),"Description")
        start,end=schedule(payload)
        phase=text(payload.get("phase",""),"Phase",120)
        phase_id=None
        if phase:
            db.execute("INSERT OR IGNORE INTO project_phases(project_id,name) VALUES (?,?)",(project_id,phase))
            phase_id=db.execute("SELECT id FROM project_phases WHERE project_id=? AND name=?",(project_id,phase)).fetchone()[0]
        elif parent_id:
            phase_id=parent["phase_id"]
        cursor=db.execute("INSERT INTO project_tasks(project_id,parent_id,phase_id,title,description,start_date,end_date) VALUES (?,?,?,?,?,?,?)",(project_id,parent_id,phase_id,title,description,start,end))
        store_tags(db,"task",cursor.lastrowid,tags)
        return 201,{"task":row(db,"project_tasks",cursor.lastrowid)}
    parts=path.strip("/").split("/")
    if len(parts)==4 and parts[1]=="projects" and parts[2].isdigit() and parts[3]=="delete":
        project_id=int(parts[2])
        row(db,"projects",project_id)
        db.execute("DELETE FROM projects WHERE id=?",(project_id,))
        return 200,{"deleted_project_id":project_id}
    if len(parts)==4 and parts[1]=="projects" and parts[2].isdigit() and parts[3]=="status":
        project_id=int(parts[2])
        row(db,"projects",project_id)
        status=valid_status(payload.get("status"))
        db.execute("UPDATE projects SET status=? WHERE id=?",(status,project_id))
        return 200,{"project":row(db,"projects",project_id)}
    if len(parts)==4 and parts[1]=="projects" and parts[2].isdigit() and parts[3] in ("comments","comment-edit","comment-delete"):
        return write_discussion(db,int(parts[2]),parts[3],payload)
    if len(parts)!=4 or parts[1]!="tasks" or not parts[2].isdigit():
        raise LookupError("Not found.")
    task_id=int(parts[2])
    row(db,"project_tasks",task_id)
    action=parts[3]
    if action=="delete":
        task=row(db,"project_tasks",task_id)
        db.execute("DELETE FROM project_tasks WHERE id=?",(task_id,))
        return 200,{"deleted_task_id":task_id,"project_id":task["project_id"],"parent_id":task["parent_id"]}
    if action=="edit":
        task=row(db,"project_tasks",task_id)
        if ("project_id" in payload and payload["project_id"]!=task["project_id"]) or ("parent_id" in payload and payload["parent_id"]!=task["parent_id"]):
            raise ValueError("Project and parent membership cannot be changed in this editor.")
        title=text(payload.get("title"),"Task title",200,True)
        description=text(payload.get("description",""),"Description")
        start,end=schedule(payload)
        pairs=tag_pairs(payload.get("tags",task["tags"]),task=True)
        phase_id=task["phase_id"]
        if "phase" in payload:
            phase=text(payload["phase"],"Phase",120)
            phase_id=None
            if phase:
                db.execute("INSERT OR IGNORE INTO project_phases(project_id,name) VALUES (?,?)",(task["project_id"],phase))
                phase_id=db.execute("SELECT id FROM project_phases WHERE project_id=? AND name=?",(task["project_id"],phase)).fetchone()[0]
        db.execute("UPDATE project_tasks SET title=?,description=?,start_date=?,end_date=?,phase_id=? WHERE id=?",(title,description,start,end,phase_id,task_id))
        db.execute("DELETE FROM task_tags WHERE task_id=?",(task_id,))
        store_tags(db,"task",task_id,pairs)
        return 200,{"task":row(db,"project_tasks",task_id)}
    if action=="update":
        if "completed" not in payload or type(payload["completed"]) is not bool:
            raise ValueError("completed must be a boolean.")
        db.execute("UPDATE project_tasks SET completed=? WHERE id=?",(int(payload["completed"]),task_id))
        return 200,{"task":row(db,"project_tasks",task_id)}
    if action=="checkpoints":
        title=text(payload.get("title"),"Checkpoint",500,True)
        cursor=db.execute("INSERT INTO task_checkpoints(task_id,title) VALUES (?,?)",(task_id,title))
        return 201,{"checkpoint":row(db,"task_checkpoints",cursor.lastrowid)}
    if action=="checkpoint-update":
        checkpoint=row(db,"task_checkpoints",payload.get("checkpoint_id"))
        if checkpoint["task_id"]!=task_id:
            raise LookupError("Checkpoint not found on this task.")
        if type(payload.get("completed")) is not bool:
            raise ValueError("completed must be a boolean.")
        db.execute("UPDATE task_checkpoints SET completed=? WHERE id=?",(int(payload["completed"]),checkpoint["id"]))
        return 200,{"checkpoint":row(db,"task_checkpoints",checkpoint["id"])}
    if action=="notes":
        note_id=identifier(payload.get("note_id"))
        row(db,"notes",note_id)
        db.execute("INSERT OR IGNORE INTO task_notes(task_id,note_id) VALUES (?,?)",(task_id,note_id))
        return 200,{"note_id":note_id}
    raise LookupError("Not found.")

# Additive project metadata and contextual discussion tables.
SCHEMA += """
CREATE TABLE IF NOT EXISTS project_tags (
 project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 name TEXT NOT NULL, value TEXT NOT NULL,
 PRIMARY KEY(project_id,name,value)
);
CREATE TABLE IF NOT EXISTS task_tags (
 task_id INTEGER NOT NULL REFERENCES project_tasks(id) ON DELETE CASCADE,
 name TEXT NOT NULL, value TEXT NOT NULL,
 PRIMARY KEY(task_id,name,value)
);
CREATE TABLE IF NOT EXISTS project_comments (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 task_id INTEGER REFERENCES project_tasks(id) ON DELETE CASCADE,
 body TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS project_comments_context ON project_comments(project_id,task_id,id);
"""

def tag_pairs(value, task=False):
    if not isinstance(value,list) or len(value)>30:
        raise ValueError("Use a list of up to 30 name:value tags.")
    pairs=[]
    for entry in value:
        if not isinstance(entry,str) or ":" not in entry:
            raise ValueError("Each tag must use name:value format.")
        name,content=entry.split(":",1)
        name=text(name,"Tag name",80,True)
        content=text(content,"Tag value",200,True)
        if any(c in name+content for c in "\r\n"):
            raise ValueError("Tags must be single-line.")
        if task and name.casefold()=="project":
            raise ValueError("The project tag is inherited automatically.")
        if (name,content) not in pairs:
            pairs.append((name,content))
    return pairs

def store_tags(db,kind,item_id,pairs):
    table,column=("project_tags","project_id") if kind=="project" else ("task_tags","task_id")
    db.executemany(f"INSERT INTO {table}({column},name,value) VALUES (?,?,?)",[(item_id,name,value) for name,value in pairs])

def metadata(db,item,kind):
    table,column=("project_tags","project_id") if kind=="project" else ("task_tags","task_id")
    item["tags"]=[r["name"]+":"+r["value"] for r in db.execute(f"SELECT name,value FROM {table} WHERE {column}=? ORDER BY name,value",(item["id"],))]
    if kind=="task":
        name=db.execute("SELECT name FROM projects WHERE id=?",(item["project_id"],)).fetchone()[0]
        item["inherited_tags"]=["project:"+name]
        item["project_name"]=name
        phase=db.execute("SELECT name FROM project_phases WHERE id=?",(item["phase_id"],)).fetchone() if item["phase_id"] else None
        item["phase_name"]=phase[0] if phase else None
    return item

def comment_context(db,project_id,task_id):
    row(db,"projects",project_id)
    if task_id is not None and row(db,"project_tasks",task_id)["project_id"]!=project_id:
        raise LookupError("Task not found in this project.")
    return task_id

def discussion(db,project_id,task_id):
    comment_context(db,project_id,task_id)
    return [dict(r) for r in db.execute("SELECT * FROM project_comments WHERE project_id=? AND task_id IS ? ORDER BY id",(project_id,task_id))]

def write_discussion(db,project_id,action,payload):
    task_id=payload.get("task_id")
    comment_context(db,project_id,task_id)
    if action=="comments":
        body=text(payload.get("body"),"Comment",10000,True)
        cursor=db.execute("INSERT INTO project_comments(project_id,task_id,body) VALUES (?,?,?)",(project_id,task_id,body))
        return 201,{"comment":row(db,"project_comments",cursor.lastrowid)}
    comment=row(db,"project_comments",payload.get("comment_id"))
    if comment["project_id"]!=project_id or comment["task_id"]!=task_id:
        raise LookupError("Comment not found in this discussion.")
    if action=="comment-edit":
        body=text(payload.get("body"),"Comment",10000,True)
        db.execute("UPDATE project_comments SET body=? WHERE id=?",(body,comment["id"]))
        return 200,{"comment":row(db,"project_comments",comment["id"])}
    db.execute("DELETE FROM project_comments WHERE id=?",(comment["id"],))
    return 200,{"deleted_comment_id":comment["id"]}

def migrate_task_dates(database):
    """Rebuild the legacy task CHECK without cascading to related records."""
    path=Path(database)
    if not path.exists():
        return
    with sqlite3.connect(path, timeout=10) as db:
        old_check="CHECK((start_date IS NULL AND end_date IS NULL) OR (start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date))"
        found=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='project_tasks'").fetchone()
        if not found or old_check not in found[0]:
            return
        backups=path.parent/"backups"
        backups.mkdir(exist_ok=True)
        backup=backups/(path.stem+"-before-optional-task-dates-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+".sqlite3")
        with sqlite3.connect(backup) as target:
            db.backup(target)
        # FK enforcement must be disabled before BEGIN, never inside a transaction.
        # This avoids deleting checkpoints, links, tags, comments and children.
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        try:
            schema=db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='project_tasks'").fetchone()[0]
            if old_check not in schema:
                db.rollback()
                return
            extra=[row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='project_tasks' AND type IN ('index','trigger') AND sql IS NOT NULL")]
            sequence=db.execute("SELECT seq FROM sqlite_sequence WHERE name='project_tasks'").fetchone()
            new_schema=schema.replace(old_check,"CHECK(start_date IS NULL OR end_date IS NULL OR start_date <= end_date)")
            new_schema=re.sub(r"^CREATE TABLE (?:IF NOT EXISTS )?project_tasks\b","CREATE TABLE project_tasks_dates_new",new_schema,count=1,flags=re.I)
            db.execute(new_schema)
            columns=",".join('"'+row[1]+'"' for row in db.execute("PRAGMA table_info(project_tasks)"))
            db.execute(f"INSERT INTO project_tasks_dates_new ({columns}) SELECT {columns} FROM project_tasks")
            db.execute("DROP TABLE project_tasks")
            db.execute("ALTER TABLE project_tasks_dates_new RENAME TO project_tasks")
            for statement in extra:
                db.execute(statement)
            if sequence:
                db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='project_tasks'",(sequence[0],))
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise sqlite3.IntegrityError("Task-date migration failed foreign key verification.")
            db.commit()
        except BaseException:
            db.rollback()
            raise

SCHEMA += """
CREATE TABLE IF NOT EXISTS note_tags (
 note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
 name TEXT NOT NULL,
 value TEXT NOT NULL,
 PRIMARY KEY(note_id,name,value)
);
"""

def note_record(db,record):
    note=dict(record)
    note["tags"]=[item["name"]+":"+item["value"] for item in db.execute("SELECT name,value FROM note_tags WHERE note_id=? ORDER BY name,value",(note["id"],))]
    return note

def replace_note_tags(db,note_id,pairs):
    db.execute("DELETE FROM note_tags WHERE note_id=?",(note_id,))
    db.executemany("INSERT INTO note_tags(note_id,name,value) VALUES (?,?,?)",[(note_id,name,value) for name,value in pairs])
