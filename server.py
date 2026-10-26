"""Pplanner: private, single-user weekly notes. Python 3.12+, no dependencies."""
import argparse
import hashlib
import json
import os
import sys
import time
import sqlite3
import project_store
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("PPLANNER_DB", ROOT / "data" / "planner.sqlite3"))
MAX_BODY = 65536

def backend_digest():
    """Fingerprint code loaded by this process; static assets are served fresh."""
    digest=hashlib.sha256()
    for name in ("server.py","project_store.py"):
        digest.update((ROOT/name).read_bytes())
    return digest.hexdigest()

LOADED_BACKEND_DIGEST = backend_digest()


def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.execute("PRAGMA foreign_keys = ON")
    db.row_factory = sqlite3.Row
    return db

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    project_store.migrate_task_dates(DB)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )""")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(notes)")}
        if "completed" not in columns:
            db.execute("ALTER TABLE notes ADD COLUMN completed INTEGER NOT NULL DEFAULT 0")
        if "position" not in columns:
            db.execute("ALTER TABLE notes ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE notes SET position = -id")
        db.execute("CREATE INDEX IF NOT EXISTS notes_order ON notes(date, completed, position, id)")
        db.execute("""CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS comments_note_id ON comments(note_id, id)")
        db.execute("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for statement in project_store.SCHEMA.split(";"):
            if statement.strip():
                db.execute(statement)
        project_store.migrate(db)


def planner_today():
    return datetime.now(ZoneInfo(os.environ.get("PPLANNER_TIMEZONE", "Europe/Rome"))).date()

def rollover_week(today=None):
    """Move overdue unfinished notes once per local week, atomically."""
    today = today or planner_today()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    with connect() as db:
        previous = db.execute("SELECT value FROM app_state WHERE key = 'rollover_week'").fetchone()
        if previous and previous[0] >= monday:
            return 0
        db.execute("BEGIN IMMEDIATE")
        # Another request may have completed rollover while we waited for the lock.
        previous = db.execute("SELECT value FROM app_state WHERE key = 'rollover_week'").fetchone()
        if previous and previous[0] >= monday:
            return 0
        overdue = list(db.execute("SELECT id FROM notes WHERE completed = 0 AND date < ? ORDER BY date, position, id DESC", (monday,)))
        position = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM notes WHERE completed = 0 AND date = ?", (monday,)).fetchone()[0]
        for offset, note in enumerate(overdue):
            db.execute("UPDATE notes SET date = ?, position = ? WHERE id = ?", (monday, position + offset, note["id"]))
        db.execute("INSERT INTO app_state(key,value) VALUES ('rollover_week',?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (monday,))
    return len(overdue)

class PlannerServer(ThreadingHTTPServer):
    """Check the calendar even when no browser requests are arriving."""
    next_rollover_check = 0

    def service_actions(self):
        if time.monotonic() < self.next_rollover_check:
            return
        self.next_rollover_check = time.monotonic() + 30
        try:
            rollover_week()
        except sqlite3.Error as exc:
            print(f"Weekly rollover will retry: {exc}", file=sys.stderr, flush=True)


def valid_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use a valid date in YYYY-MM-DD format.")
    return value

class Handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            try:
                rollover_week()
            except sqlite3.Error:
                self.respond(503, {"error": "Could not prepare the current week. Please retry."})
                return
        if url.path.startswith(("/api/projects", "/api/tasks", "/api/timeline")):
            try:
                with connect() as db:
                    result = project_store.read(db,url.path,parse_qs(url.query))
                self.respond(200,result)
            except LookupError as exc:
                self.respond(404,{"error":str(exc)})
            except (ValueError,TypeError) as exc:
                self.respond(400,{"error":str(exc)})
            except sqlite3.Error:
                self.respond(503,{"error":"Could not load the project. Please retry."})
            return
        if url.path == "/api/clock":
            today = planner_today()
            self.respond(200, {"today": today.isoformat(), "week": (today - timedelta(days=today.weekday())).isoformat()})
            return
        if url.path == "/api/notes":
            try:
                query = parse_qs(url.query)
                start = valid_date(query.get("start", [""])[0])
                end = valid_date(query.get("end", [""])[0])
                if start > end:
                    raise ValueError("Start must precede end.")
                with connect() as db:
                    rows = db.execute("SELECT * FROM notes WHERE date BETWEEN ? AND ? ORDER BY date, completed, position, id DESC", (start, end))
                    self.respond(200, {"notes": [project_store.note_record(db,row) for row in rows]})
            except (ValueError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})
            return
        parts = url.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "notes"] and parts[2].isdigit():
            with connect() as db:
                note = db.execute("SELECT * FROM notes WHERE id = ?", (int(parts[2]),)).fetchone()
                if note is None:
                    self.respond(404, {"error": "Note not found."})
                    return
                comments = [dict(c) for c in db.execute("SELECT * FROM comments WHERE note_id = ? ORDER BY id", (note["id"],))]
            self.respond(200, {"note": project_store.note_record(db,note), "comments": comments})
            return
        paths = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                 "/style.css": ("style.css", "text/css"), "/workspace.js": ("workspace.js", "text/javascript")}
        for icon in ("left-arrow", "right-arrow", "settings", "add", "bin", "calendar", "project", "gantt", "locked", "update-required", "loading", "completed", "high-priority", "medium-priority", "low-priority"):
            paths[f"/imgs/{icon}.png"] = (f"../imgs/{icon}.png", "image/png")
        if url.path not in paths:
            self.respond(404, {"error": "Not found."})
            return
        name, mime = paths[url.path]
        data = (ROOT / "static" / name).read_bytes()
        if mime == "image/png" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        self.send_response(200)
        self.send_header("Content-Type", mime if mime.startswith("image/") else mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        action_path = self.path.startswith("/api/notes/")
        workspace_path = self.path.startswith(("/api/projects", "/api/tasks"))
        if self.path != "/api/notes" and not action_path and not workspace_path:
            self.respond(404, {"error": "Not found."})
            return
        # Reject browser cross-origin writes; this service intentionally has no CORS.
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.respond(403, {"error": "Cross-site requests are forbidden."})
            return
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self.respond(403, {"error": "Origin is not allowed."})
            return
        try:
            current_digest=backend_digest()
        except OSError:
            current_digest=None
        if current_digest != LOADED_BACKEND_DIGEST:
            self.respond(503, {"error": "Server code has changed. Restart python3 server.py and refresh the browser before saving. Your draft has not been saved."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.respond(413, {"error": "Request is too large or empty."})
                return
            if self.headers.get_content_type() != "application/json":
                self.respond(415, {"error": "Send application/json."})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
            rollover_week()
            if workspace_path:
                with connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    status,result=project_store.write(db,self.path,payload)
                self.respond(status,result)
                return
            if action_path:
                self.update_note(payload)
                return
            selected = valid_date(payload.get("date"))
            if date.fromisoformat(selected).weekday() > 4:
                raise ValueError("Choose a weekday, Monday to Friday.")
            body = payload.get("body")
            if not isinstance(body, str) or not body.strip() or len(body) > 10000:
                raise ValueError("Write a note between 1 and 10,000 characters.")
            tags=project_store.tag_pairs(payload.get("tags",[]))
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                position = db.execute("SELECT COALESCE(MIN(position), 0) - 1 FROM notes WHERE date = ? AND completed = 0", (selected,)).fetchone()[0]
                cursor = db.execute("INSERT INTO notes(date, body, position) VALUES (?, ?, ?)", (selected, body.strip(), position))
                project_store.replace_note_tags(db,cursor.lastrowid,tags)
                project_store.set_note_project(db,cursor.lastrowid,payload.get("project_id"))
                note = project_store.note_record(db,db.execute("SELECT * FROM notes WHERE id = ?", (cursor.lastrowid,)).fetchone())
            self.respond(201, {"note": note})
        except LookupError as exc:
            self.respond(404, {"error": str(exc)})
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            self.respond(400, {"error": str(exc)})
        except sqlite3.Error:
            self.respond(503, {"error": "Could not save your note. Please retry."})

    def update_note(self, payload):
        parts = self.path.strip("/").split("/")
        if len(parts) != 4 or not parts[2].isdigit() or parts[3] not in ("move", "complete", "edit", "comments", "delete", "comment-edit", "comment-delete"):
            self.respond(404, {"error": "Not found."})
            return
        note_id, action = int(parts[2]), parts[3]
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if row is None:
                self.respond(404, {"error": "Note not found."})
                return
            if action in ("edit", "comments", "delete", "comment-edit", "comment-delete"):
                self.edit_note(db, row, action, payload)
                return
            source = row["date"]
            target = source
            completed = row["completed"]
            before = None
            if action == "complete":
                if type(payload.get("completed")) is not bool:
                    raise ValueError("completed must be a boolean.")
                completed = int(payload["completed"])
                if completed == row["completed"]:
                    self.respond(200, {"notes": [project_store.note_record(db,n) for n in db.execute("SELECT * FROM notes WHERE date = ? ORDER BY completed, position, id DESC", (source,))]})
                    return
            else:
                target = valid_date(payload.get("date"))
                original = date.fromisoformat(source)
                destination = date.fromisoformat(target)
                if destination.weekday() > 4 or original - timedelta(days=original.weekday()) != destination - timedelta(days=destination.weekday()):
                    raise ValueError("Move notes only between weekdays of the same week.")
                before = payload.get("before_id")
                if before is not None and (type(before) is not int or before == note_id):
                    raise ValueError("Invalid insertion point.")
            ids = [n[0] for n in db.execute("SELECT id FROM notes WHERE date = ? AND completed = ? AND id != ? ORDER BY position, id DESC", (target, completed, note_id))]
            if before is not None and before not in ids:
                raise ValueError("The insertion point must be in the same day and completion group.")
            # Completing goes last; reopening goes first. Moves use an explicit insertion point.
            index = (len(ids) if completed else 0) if action == "complete" else (ids.index(before) if before is not None else len(ids))
            ids.insert(index, note_id)
            db.execute("UPDATE notes SET date = ?, completed = ? WHERE id = ?", (target, completed, note_id))
            for position, current_id in enumerate(ids):
                db.execute("UPDATE notes SET position = ? WHERE id = ?", (position, current_id))
            notes = [project_store.note_record(db,n) for n in db.execute("SELECT * FROM notes WHERE date IN (?, ?) ORDER BY date, completed, position, id DESC", (source, target))]
        self.respond(200, {"notes": notes, "dates": list(dict.fromkeys([source, target]))})

    def edit_note(self, db, row, action, payload):
        note_id, source = row["id"], row["date"]
        target = source
        if action in ("comment-edit", "comment-delete"):
            comment_id = payload.get("comment_id")
            if type(comment_id) is not int or comment_id < 1:
                raise ValueError("Use a valid comment ID.")
            comment = db.execute("SELECT * FROM comments WHERE id = ? AND note_id = ?", (comment_id, note_id)).fetchone()
            if comment is None:
                self.respond(404, {"error": "Comment not found on this note."})
                return
            if action == "comment-edit":
                body = payload.get("body")
                if not isinstance(body, str) or not body.strip() or len(body) > 10000:
                    raise ValueError("Write a comment between 1 and 10,000 characters.")
                db.execute("UPDATE comments SET body = ? WHERE id = ? AND note_id = ?", (body.strip(), comment_id, note_id))
                result = {"comment": dict(db.execute("SELECT * FROM comments WHERE id = ?", (comment_id,)).fetchone())}
            else:
                db.execute("DELETE FROM comments WHERE id = ? AND note_id = ?", (comment_id, note_id))
                result = {"deleted_comment_id": comment_id}
            db.commit()
            self.respond(200, result)
            return
        if action == "comments":
            body = payload.get("body")
            if not isinstance(body, str) or not body.strip() or len(body) > 10000:
                raise ValueError("Write a comment between 1 and 10,000 characters.")
            cursor = db.execute("INSERT INTO comments(note_id, body) VALUES (?, ?)", (note_id, body.strip()))
            comment = dict(db.execute("SELECT * FROM comments WHERE id = ?", (cursor.lastrowid,)).fetchone())
            db.commit()
            self.respond(201, {"comment": comment})
            return
        if action == "delete":
            db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        else:
            target = valid_date(payload.get("date"))
            if date.fromisoformat(target).weekday() > 4:
                raise ValueError("Choose a weekday, Monday to Friday.")
            body = payload.get("body")
            if not isinstance(body, str) or not body.strip() or len(body) > 10000:
                raise ValueError("Write a note between 1 and 10,000 characters.")
            tags=project_store.tag_pairs(payload["tags"]) if "tags" in payload else None
            if "project_id" in payload:
                project_store.set_note_project(db,note_id,payload["project_id"])
            position = row["position"]
            if target != source:
                aggregate = "MAX" if row["completed"] else "MIN"
                step = 1 if row["completed"] else -1
                position = db.execute(f"SELECT COALESCE({aggregate}(position), 0) FROM notes WHERE date = ? AND completed = ?", (target, row["completed"])).fetchone()[0] + step
            db.execute("UPDATE notes SET date = ?, body = ?, position = ? WHERE id = ?", (target, body.strip(), position, note_id))
            if tags is not None:
                project_store.replace_note_tags(db,note_id,tags)
        notes = [project_store.note_record(db,n) for n in db.execute("SELECT * FROM notes WHERE date IN (?, ?) ORDER BY date, completed, position, id DESC", (source, target))]
        result = {"notes": notes, "dates": list(dict.fromkeys([source, target]))}
        if action == "edit":
            result["note"] = project_store.note_record(db,db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone())
        db.commit()
        self.respond(200, result)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    initialize()
    rollover_week()
    server = PlannerServer((args.host, args.port), Handler)
    print(f"Pplanner is running at http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
