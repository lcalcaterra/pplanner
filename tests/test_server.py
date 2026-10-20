import importlib.util
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("planner", Path(__file__).resolve().parents[1] / "server.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.original_today = app.planner_today
        self.clock_patch = patch.object(app, "planner_today", return_value=date(2026, 10, 13))
        self.clock = self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        app.DB = Path(self.temp.name) / "test.sqlite3"
        app.initialize()
        self.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, **headers):
        headers = {"Content-Type": "application/json", **headers}
        request = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            response = urlopen(request)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if "application/json" in response.headers["Content-Type"] else raw

    def test_note_tags_lifecycle(self):
        status, data = self.request("/api/notes", {"date":"2026-10-12","body":"Tagged","tags":[" area : personal ","priority:high","area:personal"]})
        self.assertEqual(status,201)
        note=data["note"]; note_id=note["id"]
        self.assertEqual(note["tags"],["area:personal","priority:high"])
        self.assertEqual(self.week_notes()[0]["tags"],note["tags"])
        self.action(note_id,"edit",{"date":"2026-10-12","body":"Legacy edit"})
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["note"]["tags"],note["tags"])
        for action,payload in [("move",{"date":"2026-10-13"}),("complete",{"completed":True}),("complete",{"completed":False})]:
            self.assertEqual(self.action(note_id,action,payload)[1]["notes"][0]["tags"],note["tags"])
        self.clock.return_value=date(2026,10,19)
        app.rollover_week()
        app.initialize()
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["note"]["tags"],note["tags"])
        self.assertEqual(self.action(note_id,"edit",{"date":"2026-10-19","body":"Updated","tags":["topic:test"]})[1]["note"]["tags"],["topic:test"])
        self.assertEqual(self.action(note_id,"edit",{"date":"2026-10-19","body":"Updated","tags":[]})[1]["note"]["tags"],[])
        self.action(note_id,"edit",{"date":"2026-10-19","body":"Updated","tags":["topic:test"]})
        self.action(note_id,"delete",{})
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM note_tags").fetchone()[0],0)

    def test_note_tags_validation_is_atomic(self):
        note_id=self.add("Original")
        for tags in ["area:personal",["invalid"],[":value"],["name:"],["name:line\nbreak"],["n:v"]*31]:
            payload={"date":"2026-10-13","body":"Changed","tags":tags}
            self.assertEqual(self.action(note_id,"edit",payload)[0],400)
            self.assertEqual(self.request("/api/notes",payload)[0],400)
        saved=self.request(f"/api/notes/{note_id}")[1]["note"]
        self.assertEqual((saved["body"],saved["date"],saved["tags"]),("Original","2026-10-12",[]))

    def test_persistence_order_and_range(self):
        for body in ["first", "second"]:
            self.assertEqual(self.request("/api/notes", {"date":"2026-10-12", "body":body})[0], 201)
        self.request("/api/notes", {"date":"2026-10-19", "body":"next week"})
        app.initialize()
        status, data = self.request("/api/notes?start=2026-10-12&end=2026-10-16")
        self.assertEqual(status, 200)
        self.assertEqual([n["body"] for n in data["notes"]], ["second", "first"])

    def add(self, body, selected="2026-10-12"):
        return self.request("/api/notes", {"date": selected, "body": body})[1]["note"]["id"]

    def week_notes(self):
        return self.request("/api/notes?start=2026-10-12&end=2026-10-16")[1]["notes"]

    def action(self, note_id, action, payload):
        return self.request(f"/api/notes/{note_id}/{action}", payload)

    def test_reorder_move_and_completion_persist(self):
        first, second, third = [self.add(body) for body in ["first", "second", "third"]]
        self.assertEqual(self.action(first, "move", {"date":"2026-10-12","before_id":third})[0], 200)
        self.assertEqual([n["id"] for n in self.week_notes()], [first, third, second])
        self.assertEqual(self.action(third, "move", {"date":"2026-10-13"})[0], 200)
        self.assertEqual(self.action(first, "complete", {"completed": True})[0], 200)
        self.assertEqual([n["id"] for n in self.week_notes() if n["date"] == "2026-10-12"], [second, first])
        new = self.add("new")
        app.initialize()
        notes = self.week_notes()
        self.assertEqual([n["id"] for n in notes if n["date"] == "2026-10-12"], [new, second, first])
        self.assertEqual(next(n for n in notes if n["id"] == first)["completed"], 1)
        self.assertEqual(self.action(first, "complete", {"completed": False})[0], 200)
        self.assertEqual([n["id"] for n in self.week_notes() if n["date"] == "2026-10-12"], [first, new, second])

    def test_move_validation_and_atomicity(self):
        first, second = self.add("first"), self.add("second")
        for payload in [{"date":"2026-10-19"}, {"date":"2026-10-17"}, {"date":"2026-10-13","before_id":second}, {"date":"2026-10-12","before_id":first}, {"date":"2026-10-12","before_id":True}]:
            self.assertEqual(self.action(first, "move", payload)[0], 400)
        self.assertEqual(self.action(99999, "move", {"date":"2026-10-13"})[0], 404)
        self.assertEqual(self.action(first, "complete", {"completed":"yes"})[0], 400)
        self.action(second, "complete", {"completed":True})
        self.assertEqual(self.action(first, "move", {"date":"2026-10-12","before_id":second})[0], 400)
        self.assertEqual([n["id"] for n in self.week_notes()], [first, second])
        self.assertEqual(self.action(first, "move", {"date":"2026-10-13"},)[0], 200)

    def test_completion_is_idempotent_and_completed_order(self):
        first, second, third = [self.add(body) for body in ["one","two","three"]]
        for note_id in [first,second]:
            self.action(note_id,"complete",{"completed":True})
        self.assertEqual([n["id"] for n in self.week_notes()], [third,first,second])
        self.action(first,"complete",{"completed":True})
        self.assertEqual([n["id"] for n in self.week_notes()], [third,first,second])
        self.action(second,"move",{"date":"2026-10-12","before_id":first})
        self.assertEqual([n["id"] for n in self.week_notes()], [third,second,first])

    def test_old_database_migration_preserves_notes(self):
        with app.connect() as db:
            db.execute("DROP TABLE notes")
            db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '2026-10-12T10:00:00Z')")
            db.executemany("INSERT INTO notes(date,body) VALUES ('2026-10-12',?)", [("old first",),("old second",)])
        app.initialize()
        app.initialize()
        notes = self.week_notes()
        self.assertEqual([n["body"] for n in notes], ["old second","old first"])
        self.assertTrue(all(n["completed"] == 0 for n in notes))
        self.action(notes[1]["id"],"complete",{"completed":True})
        self.assertEqual(self.week_notes()[-1]["completed"], 1)

    def test_edit_text_date_and_preserve_completion(self):
        note_id = self.add("original")
        self.action(note_id, "complete", {"completed": True})
        result, data = self.action(note_id, "edit", {"date":"2026-10-19","body":" updated body "})
        self.assertEqual(result, 200)
        self.assertEqual(data["note"]["body"], "updated body")
        self.assertEqual(data["note"]["date"], "2026-10-19")
        self.assertEqual(data["note"]["completed"], 1)
        self.assertEqual(self.week_notes(), [])
        app.initialize()
        status, detail = self.request(f"/api/notes/{note_id}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["note"]["body"], "updated body")

    def test_edit_validation_does_not_change_note(self):
        note_id = self.add("original")
        for payload in [{"date":"2026-10-17","body":"weekend"}, {"date":"bad","body":"bad"}, {"date":"2026-10-13","body":" "}, {"date":"2026-10-13","body":"x"*10001}]:
            self.assertEqual(self.action(note_id,"edit",payload)[0],400)
        detail = self.request(f"/api/notes/{note_id}")[1]
        self.assertEqual(detail["note"]["body"],"original")
        self.assertEqual(detail["note"]["date"],"2026-10-12")
        self.assertEqual(self.action(99999,"edit",{"date":"2026-10-12","body":"x"})[0],404)

    def test_comments_order_persistence_and_delete_cascade(self):
        note_id = self.add("with history")
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["comments"], [])
        for body in ["first comment", "<script>plain text</script>"]:
            self.assertEqual(self.action(note_id,"comments",{"body":body})[0],201)
        for body in [" ", "x"*10001, 123]:
            self.assertEqual(self.action(note_id,"comments",{"body":body})[0],400)
        self.action(note_id,"edit",{"date":"2026-10-20","body":"moved"})
        app.initialize()
        comments = self.request(f"/api/notes/{note_id}")[1]["comments"]
        self.assertEqual([c["body"] for c in comments],["first comment","<script>plain text</script>"])
        self.assertTrue(all(c["created_at"].endswith("Z") for c in comments))
        self.assertEqual(self.action(note_id,"delete",{})[0],200)
        self.assertEqual(self.request(f"/api/notes/{note_id}")[0],404)
        self.assertEqual(self.action(note_id,"comments",{"body":"orphan"})[0],404)
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM comments WHERE note_id = ?",(note_id,)).fetchone()[0],0)

    def test_edit_order_and_bin_asset(self):
        first, second = self.add("first"), self.add("second")
        self.action(first,"edit",{"date":"2026-10-12","body":"edited"})
        self.assertEqual([n["id"] for n in self.week_notes()],[second,first])
        destination = self.add("destination","2026-10-13")
        self.action(first,"edit",{"date":"2026-10-13","body":"moved"})
        self.assertEqual([n["id"] for n in self.week_notes() if n["date"] == "2026-10-13"],[first,destination])
        self.assertEqual(self.request("/imgs/bin.png")[0],200)

    def test_comment_edit_delete_and_persistence(self):
        note_id = self.add("note")
        first = self.action(note_id,"comments",{"body":"first"})[1]["comment"]
        second = self.action(note_id,"comments",{"body":"second"})[1]["comment"]
        status, data = self.action(note_id,"comment-edit",{"comment_id":first["id"],"body":" updated "})
        self.assertEqual(status,200)
        self.assertEqual(data["comment"]["body"],"updated")
        self.assertEqual(data["comment"]["created_at"],first["created_at"])
        app.initialize()
        comments = self.request(f"/api/notes/{note_id}")[1]["comments"]
        self.assertEqual([c["body"] for c in comments],["updated","second"])
        self.assertEqual(self.action(note_id,"comment-delete",{"comment_id":first["id"]})[0],200)
        app.initialize()
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["comments"],[second])
        self.assertEqual(self.action(note_id,"comment-delete",{"comment_id":first["id"]})[0],404)
        self.assertEqual(self.action(note_id,"comment-delete",{"comment_id":second["id"]})[0],200)
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["comments"],[])

    def test_comment_actions_validation_and_note_ownership(self):
        first, other = self.add("first"), self.add("other")
        comment = self.action(first,"comments",{"body":"unchanged"})[1]["comment"]
        for action in ["comment-edit","comment-delete"]:
            self.assertEqual(self.action(other,action,{"comment_id":comment["id"],"body":"wrong note"})[0],404)
            for invalid in [None,True,-1,"1"]:
                self.assertEqual(self.action(first,action,{"comment_id":invalid,"body":"invalid"})[0],400)
            self.assertEqual(self.action(99999,action,{"comment_id":comment["id"],"body":"missing"})[0],404)
            self.assertEqual(self.action(first,action,{"comment_id":99999,"body":"missing"})[0],404)
        for body in [" ",123,"x"*10001]:
            self.assertEqual(self.action(first,"comment-edit",{"comment_id":comment["id"],"body":body})[0],400)
        self.assertEqual(self.request(f"/api/notes/{first}")[1]["comments"],[comment])
        self.assertEqual(self.action(first,"comment-delete",{"comment_id":comment["id"]})[0],200)

    def test_rollover_monday_catches_up_and_preserves_comments(self):
        old = self.add("old", "2026-09-30")
        recent = self.add("recent", "2026-10-16")
        completed = self.add("done", "2026-10-16")
        self.action(completed,"complete",{"completed":True})
        existing = self.add("already Monday","2026-10-19")
        future = self.add("future","2026-10-20")
        self.action(old,"comments",{"body":"history"})
        before = self.request(f"/api/notes/{old}")[1]["note"]["created_at"]
        self.clock.return_value = date(2026,10,19)
        status, data = self.request("/api/notes?start=2026-10-19&end=2026-10-23")
        self.assertEqual(status,200)
        self.assertEqual([n["id"] for n in data["notes"] if n["date"] == "2026-10-19"],[existing,old,recent])
        self.assertEqual(next(n["date"] for n in data["notes"] if n["id"] == future),"2026-10-20")
        detail = self.request(f"/api/notes/{old}")[1]
        self.assertEqual(detail["comments"][0]["body"],"history")
        self.assertEqual(detail["note"]["created_at"],before)
        self.assertEqual(self.request(f"/api/notes/{completed}")[1]["note"]["date"],"2026-10-16")
        self.assertEqual(app.rollover_week(),0)
        self.assertEqual(self.request("/api/clock")[1],{"today":"2026-10-19","week":"2026-10-19"})

    def test_rollover_not_before_monday_and_only_once_per_week(self):
        note_id = self.add("Friday","2026-10-16")
        self.clock.return_value = date(2026,10,18)
        self.assertEqual(app.rollover_week(),0)
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["note"]["date"],"2026-10-16")
        self.clock.return_value = date(2026,10,19)
        self.assertEqual(app.rollover_week(),1)
        self.action(note_id,"edit",{"date":"2026-10-16","body":"intentionally backdated"})
        app.initialize()
        self.assertEqual(app.rollover_week(),0)
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["note"]["date"],"2026-10-16")
        self.clock.return_value = date(2026,11,2)
        self.assertEqual(app.rollover_week(),1)
        self.assertEqual(self.request(f"/api/notes/{note_id}")[1]["note"]["date"],"2026-11-02")

    def test_initial_rollover_and_concurrent_checks(self):
        # Simulate data from an older installation before its first rollover.
        with app.connect() as db:
            db.execute("DELETE FROM app_state")
            db.executemany("INSERT INTO notes(date,body,position) VALUES (?,?,?)",
                           [("2025-12-31","one",0),("2026-01-02","two",0)])
        self.clock.return_value = date(2026,1,5)
        with ThreadPoolExecutor(max_workers=4) as pool:
            counts = list(pool.map(lambda _: app.rollover_week(),range(4)))
        self.assertEqual(sum(counts),2)
        with app.connect() as db:
            rows = list(db.execute("SELECT date,body,position FROM notes ORDER BY position"))
        self.assertEqual([(n["date"],n["body"]) for n in rows],[("2026-01-05","one"),("2026-01-05","two")])
        self.assertEqual(len({n["position"] for n in rows}),2)

    def test_background_rollover_and_local_timezone(self):
        note_id = self.add("background","2026-10-16")
        self.clock.return_value = date(2026,10,19)
        class Timer:
            next_rollover_check = 0
        timer = Timer()
        app.PlannerServer.service_actions(timer)
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT date FROM notes WHERE id = ?",(note_id,)).fetchone()[0],"2026-10-19")
        # Sunday UTC is already Monday in Rome, including the autumn DST boundary.
        with patch.object(app, "datetime") as clock, patch.dict(app.os.environ, {"PPLANNER_TIMEZONE":"Europe/Rome"}):
            clock.now.side_effect = lambda zone: datetime(2026,10,18,22,5,tzinfo=timezone.utc).astimezone(zone)
            # Call the original timezone-aware helper rather than the per-test mock.
            self.assertEqual(self.original_today(),date(2026,10,19))

    def test_project_task_details_and_timeline(self):
        status, result = self.request("/api/projects",{"name":"Launch","color":"#65518c"})
        self.assertEqual(status,201)
        project_id=result["project"]["id"]
        status,result=self.request("/api/tasks",{"project_id":project_id,"title":"Design","phase":"Planning","start_date":"2026-10-19","end_date":"2026-10-23"})
        self.assertEqual(status,201)
        task=result["task"]
        status,result=self.request("/api/tasks",{"project_id":project_id,"parent_id":task["id"],"title":"Wireframes"})
        self.assertEqual(status,201)
        self.assertEqual(result["task"]["phase_id"],task["phase_id"])
        checkpoint=self.request(f"/api/tasks/{task['id']}/checkpoints",{"title":"Review"})[1]["checkpoint"]
        self.assertEqual(self.request(f"/api/tasks/{task['id']}/checkpoint-update",{"checkpoint_id":checkpoint["id"],"completed":True})[0],200)
        note_id=self.add("context")
        self.assertEqual(self.request(f"/api/tasks/{task['id']}/notes",{"note_id":note_id})[0],200)
        self.request(f"/api/tasks/{task['id']}/notes",{"note_id":note_id})
        app.initialize()
        detail=self.request(f"/api/tasks/{task['id']}")[1]
        self.assertEqual(len(detail["subtasks"]),1)
        self.assertEqual(len(detail["notes"]),1)
        self.assertEqual(detail["checkpoints"][0]["completed"],1)
        tasks=self.request(f"/api/timeline?project_id={project_id}")[1]["tasks"]
        self.assertEqual(len(tasks),2)
        self.assertEqual(tasks[0]["project_name"],"Launch")
        self.assertEqual(tasks[0]["phase_name"],"Planning")
        self.assertEqual(self.request(f"/api/tasks/{task['id']}/update",{"completed":True})[1]["task"]["completed"],1)

    def test_project_validation_and_isolation(self):
        first=self.request("/api/projects",{"name":"First"})[1]["project"]["id"]
        second=self.request("/api/projects",{"name":"Second"})[1]["project"]["id"]
        task=self.request("/api/tasks",{"project_id":first,"title":"Parent"})[1]["task"]
        for payload in [{"project_id":second,"parent_id":task["id"],"title":"Wrong parent"},
                        {"project_id":first,"title":"Bad dates","start_date":"2026-10-20","end_date":"2026-10-19"},
                        {"project_id":first,"title":"Invalid date","start_date":"not-a-date"},
                        {"project_id":first,"title":" "}]:
            self.assertEqual(self.request("/api/tasks",payload)[0],400)
        self.assertEqual(len(self.request(f"/api/projects/{second}")[1]["tasks"]),0)
        self.assertEqual(len(self.request("/api/timeline")[1]["tasks"]),1)
        self.assertEqual(self.request("/api/projects",{"name":" ","color":"#65518c"})[0],400)
        self.assertEqual(self.request("/api/projects",{"name":"Bad color","color":"red"})[0],400)
        self.assertEqual(self.request("/api/tasks",{"project_id":99999,"title":"Missing"})[0],404)
        self.assertEqual(self.request("/api/timeline?project_id=99999")[0],404)
        self.assertEqual(self.request(f"/api/tasks/{task['id']}/update",{"completed":"yes"})[0],400)

    def test_checkpoints_owned_by_task_and_note_links_cascade(self):
        project=self.request("/api/projects",{"name":"Project"})[1]["project"]["id"]
        first,second=[self.request("/api/tasks",{"project_id":project,"title":title})[1]["task"]["id"] for title in ["One","Two"]]
        checkpoint=self.request(f"/api/tasks/{first}/checkpoints",{"title":"Check"})[1]["checkpoint"]["id"]
        self.assertEqual(self.request(f"/api/tasks/{second}/checkpoint-update",{"checkpoint_id":checkpoint,"completed":True})[0],404)
        note_id=self.add("linked")
        self.request(f"/api/tasks/{first}/notes",{"note_id":note_id})
        self.action(note_id,"delete",{})
        self.assertEqual(self.request(f"/api/tasks/{first}")[1]["notes"],[])
        self.assertEqual(self.request(f"/api/tasks/{first}/notes",{"note_id":99999})[0],404)

    def test_workspace_navigation_and_static_script(self):
        status,html=self.request("/")
        self.assertEqual(status,200)
        for hook in [b'id="calendar-page"',b'id="projects-page"',b'id="gantt-page"',b'href="#calendar"',b'href="#projects"',b'href="#gantt"']:
            self.assertIn(hook,html)
        self.assertIn(b'id="projects-page" class="workspace-page" hidden',html)
        self.assertIn(b'id="gantt-page" class="workspace-page" hidden',html)
        self.assertEqual(self.request("/workspace.js")[0],200)
        self.assertEqual(self.request("/project_store.py")[0],404)
        self.assertEqual(self.request("/api/projects")[1]["projects"],[])
        self.assertEqual(self.request("/api/timeline")[1]["tasks"],[])

    def test_project_tags_task_inheritance_and_subtask_description(self):
        project=self.request("/api/projects",{"name":"Alpha","description":"Context","tags":["team:engineering","priority:high","team:engineering"]})[1]["project"]
        self.assertEqual(project["description"],"Context")
        self.assertEqual(project["tags"],["priority:high","team:engineering"])
        task=self.request("/api/tasks",{"project_id":project["id"],"title":"Build","description":"Task context","tags":["owner:Luca"]})[1]["task"]
        self.assertEqual(task["tags"],["owner:Luca"])
        self.assertEqual(task["inherited_tags"],["project:Alpha"])
        sub=self.request("/api/tasks",{"project_id":project["id"],"parent_id":task["id"],"title":"Step","description":"Subtask context"})[1]["task"]
        self.assertEqual(sub["description"],"Subtask context")
        app.initialize()
        data=self.request(f"/api/projects/{project['id']}")[1]
        self.assertEqual(data["project"]["tags"],project["tags"])
        self.assertEqual(next(t for t in data["tasks"] if t["id"]==task["id"])["tags"],["owner:Luca"])
        with app.connect() as db:
            db.execute("UPDATE projects SET name='Renamed' WHERE id=?",(project["id"],))
        self.assertEqual(self.request(f"/api/tasks/{task['id']}")[1]["task"]["inherited_tags"],["project:Renamed"])

    def test_tag_validation_is_atomic(self):
        project=self.request("/api/projects",{"name":"Tags"})[1]["project"]["id"]
        for tags in [["broken"],[":value"],["name:"],"name:value",["x:y"]*31,["x:bad\nvalue"]]:
            self.assertEqual(self.request("/api/projects",{"name":"Invalid","tags":tags})[0],400)
        for tags in [["project:Fake"],["PROJECT:Fake"],["bad"],[True]]:
            self.assertEqual(self.request("/api/tasks",{"project_id":project,"title":"Bad","tags":tags})[0],400)
        self.assertEqual(len(self.request("/api/projects")[1]["projects"]),1)
        self.assertEqual(self.request(f"/api/projects/{project}")[1]["tasks"],[])

    def test_project_and_task_discussions_are_isolated_and_persistent(self):
        project=self.request("/api/projects",{"name":"Discuss"})[1]["project"]["id"]
        other=self.request("/api/projects",{"name":"Other"})[1]["project"]["id"]
        first,second=[self.request("/api/tasks",{"project_id":project,"title":name})[1]["task"]["id"] for name in ["One","Two"]]
        root=self.request(f"/api/projects/{project}/comments",{"body":"Project comment"})[1]["comment"]
        comment=self.request(f"/api/projects/{project}/comments",{"task_id":first,"body":"Task comment"})[1]["comment"]
        self.assertEqual(len(self.request(f"/api/projects/{project}/comments")[1]["comments"]),1)
        self.assertEqual(self.request(f"/api/projects/{project}/comments?task_id={second}")[1]["comments"],[])
        self.assertEqual(self.request(f"/api/projects/{other}/comments?task_id={first}")[0],404)
        self.assertEqual(self.request(f"/api/projects/{other}/comments",{"task_id":first,"body":"Wrong project"})[0],404)
        self.assertEqual(self.request(f"/api/projects/{project}/comment-delete",{"task_id":second,"comment_id":comment["id"]})[0],404)
        self.assertEqual(self.request(f"/api/projects/{project}/comment-edit",{"task_id":first,"comment_id":comment["id"],"body":"Changed"})[0],200)
        app.initialize()
        detail=self.request(f"/api/tasks/{first}")[1]
        self.assertEqual(detail["comments"][0]["body"],"Changed")
        self.assertEqual(detail["comments"][0]["created_at"],comment["created_at"])
        self.assertEqual(self.request(f"/api/projects/{project}/comments",{"body":" "})[0],400)
        self.assertEqual(self.request(f"/api/projects/{project}/comment-delete",{"task_id":first,"comment_id":comment["id"]})[0],200)
        self.assertEqual(self.request(f"/api/tasks/{first}")[1]["comments"],[])
        self.assertEqual(self.request(f"/api/projects/{project}/comments")[1]["comments"],[root])

    def test_task_and_subtask_edit_preserves_links_and_updates_timeline(self):
        project=self.request("/api/projects",{"name":"Editing"})[1]["project"]["id"]
        parent=self.request("/api/tasks",{"project_id":project,"title":"Parent"})[1]["task"]["id"]
        child=self.request("/api/tasks",{"project_id":project,"parent_id":parent,"title":"Child","description":"Old"})[1]["task"]["id"]
        self.request(f"/api/projects/{project}/comments",{"task_id":child,"body":"Context"})
        note=self.add("Linked")
        self.request(f"/api/tasks/{child}/notes",{"note_id":note})
        self.request(f"/api/tasks/{child}/checkpoints",{"title":"Review"})
        status,result=self.request(f"/api/tasks/{child}/edit",{"title":"Edited child","description":"New text","tags":["owner:Luca"],"phase":"Build","start_date":"2026-10-20","end_date":"2026-10-23"})
        self.assertEqual(status,200)
        self.assertEqual(result["task"]["parent_id"],parent)
        self.assertEqual(result["task"]["inherited_tags"],["project:Editing"])
        self.assertEqual(result["task"]["phase_name"],"Build")
        app.initialize()
        detail=self.request(f"/api/tasks/{child}")[1]
        self.assertEqual(detail["task"]["description"],"New text")
        self.assertEqual(detail["task"]["title"],"Edited child")
        self.assertEqual(len(detail["notes"]),1)
        self.assertEqual(len(detail["checkpoints"]),1)
        self.assertEqual(detail["comments"][0]["body"],"Context")
        timeline=self.request(f"/api/timeline?project_id={project}")[1]["tasks"]
        self.assertEqual(next(task for task in timeline if task["id"]==child)["start_date"],"2026-10-20")
        self.assertEqual(self.request(f"/api/tasks/{parent}/edit",{"title":"Edited parent","description":"","tags":[],"phase":"","start_date":"","end_date":""})[0],200)

    def test_task_edit_validation_is_atomic(self):
        project=self.request("/api/projects",{"name":"Immutable"})[1]["project"]["id"]
        task=self.request("/api/tasks",{"project_id":project,"title":"Original","tags":["priority:high"]})[1]["task"]
        for values in [{"title":" "},{"title":"Changed","tags":["project:Fake"]},{"title":"Changed","start_date":"2026-10-23","end_date":"2026-10-20"},{"title":"Changed","parent_id":task["id"]},{"title":"Changed","project_id":999}]:
            self.assertEqual(self.request(f"/api/tasks/{task['id']}/edit",values)[0],400)
        persisted=self.request(f"/api/tasks/{task['id']}")[1]["task"]
        self.assertEqual(persisted["title"],"Original")
        self.assertEqual(persisted["tags"],["priority:high"])
        self.assertEqual(self.request("/api/tasks/99999/edit",{"title":"Missing"})[0],404)

    def test_project_status_defaults_transitions_and_persistence(self):
        project=self.request("/api/projects",{"name":"Lifecycle"})[1]["project"]
        self.assertEqual(project["status"],"active")
        for status in ["suspended","completed","rejected","closed","active"]:
            result,data=self.request(f"/api/projects/{project['id']}/status",{"status":status})
            self.assertEqual(result,200)
            self.assertEqual(data["project"]["status"],status)
            app.initialize()
            self.assertEqual(self.request(f"/api/projects/{project['id']}")[1]["project"]["status"],status)
        created=self.request("/api/projects",{"name":"Paused","status":"suspended"})[1]["project"]
        self.assertEqual(created["status"],"suspended")
        self.assertEqual(self.request("/api/timeline")[1]["projects"][-1]["status"],"suspended")

    def test_project_status_validation_and_task_independence(self):
        project=self.request("/api/projects",{"name":"Project"})[1]["project"]
        task=self.request("/api/tasks",{"project_id":project["id"],"title":"Still open"})[1]["task"]
        for status in ["unknown","Active","",None,False,[]]:
            self.assertEqual(self.request(f"/api/projects/{project['id']}/status",{"status":status})[0],400)
        self.assertEqual(self.request(f"/api/projects/{project['id']}")[1]["project"]["status"],"active")
        self.assertEqual(self.request("/api/projects",{"name":"Invalid","status":"done"})[0],400)
        self.assertEqual(self.request("/api/projects/99999/status",{"status":"active"})[0],404)
        self.request(f"/api/projects/{project['id']}/status",{"status":"closed"})
        self.assertEqual(self.request(f"/api/tasks/{task['id']}")[1]["task"]["completed"],0)

    def test_legacy_project_status_migration(self):
        original=app.DB
        try:
            app.DB=Path(self.temp.name)/"legacy.sqlite3"
            with app.connect() as db:
                db.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',color TEXT NOT NULL DEFAULT '#65518c',created_at TEXT NOT NULL DEFAULT '2026-10-20T00:00:00Z')")
                db.execute("INSERT INTO projects(name,description) VALUES ('Legacy','Keep me')")
            app.initialize()
            app.initialize()
            data=self.request("/api/projects/1")[1]["project"]
            self.assertEqual(data["status"],"active")
            self.assertEqual(data["description"],"Keep me")
            with app.connect() as db:
                self.assertEqual(len([c for c in db.execute("PRAGMA table_info(projects)") if c["name"]=="status"]),1)
        finally:
            app.DB=original

    def test_independently_optional_dates_for_task_and_subtask(self):
        project=self.request("/api/projects",{"name":"Optional dates"})[1]["project"]["id"]
        parent=self.request("/api/tasks",{"project_id":project,"title":"Parent"})[1]["task"]["id"]
        cases=[(None,None),("2026-10-20",None),(None,"2026-10-23"),("2026-10-20","2026-10-23"),("2026-10-20","2026-10-20"),("","")]
        for parent_id in [None,parent]:
            for start,end in cases:
                payload={"project_id":project,"parent_id":parent_id,"title":"Dates","start_date":start,"end_date":end}
                status,data=self.request("/api/tasks",payload)
                self.assertEqual(status,201,(payload,data))
                task_id=data["task"]["id"]
                self.assertEqual(data["task"]["start_date"],start or None)
                self.assertEqual(data["task"]["end_date"],end or None)
                for edited_start,edited_end in [("2026-10-21",None),(None,"2026-10-22"),(None,None)]:
                    result,edited=self.request(f"/api/tasks/{task_id}/edit",{"title":"Edited","description":"saved","start_date":edited_start,"end_date":edited_end})
                    self.assertEqual(result,200,edited)
                    self.assertEqual(edited["task"]["start_date"],edited_start)
                    self.assertEqual(edited["task"]["end_date"],edited_end)
        for start,end in [("invalid",None),(None,"2026-02-30"),("2026-10-23","2026-10-20"),(False,None)]:
            self.assertEqual(self.request("/api/tasks",{"project_id":project,"title":"Invalid","start_date":start,"end_date":end})[0],400)

    def test_legacy_optional_date_migration_preserves_task_relations(self):
        original=app.DB
        try:
            app.DB=Path(self.temp.name)/"legacy-dates.sqlite3"
            app.initialize()
            with app.sqlite3.connect(app.DB) as db:
                db.execute("DROP TABLE project_tasks")
                schema=next(statement for statement in app.project_store.SCHEMA.split(";") if "CREATE TABLE IF NOT EXISTS project_tasks (" in statement)
                schema=schema.replace("CHECK(start_date IS NULL OR end_date IS NULL OR start_date <= end_date)","CHECK((start_date IS NULL AND end_date IS NULL) OR (start_date IS NOT NULL AND end_date IS NOT NULL AND start_date <= end_date))")
                db.execute(schema)
                db.execute("CREATE INDEX custom_task_title ON project_tasks(title)")
                db.execute("INSERT INTO projects(id,name) VALUES (1,'Legacy')")
                db.execute("INSERT INTO project_tasks(id,project_id,title) VALUES (40,1,'Parent')")
                db.execute("INSERT INTO project_tasks(id,project_id,parent_id,title) VALUES (41,1,40,'Child')")
                db.execute("INSERT INTO project_tasks(id,project_id,title) VALUES (80,1,'Deleted')")
                db.execute("DELETE FROM project_tasks WHERE id=80")
                db.execute("INSERT INTO notes(id,date,body) VALUES (1,'2026-10-20','Context')")
                db.execute("INSERT INTO task_notes(task_id,note_id) VALUES (41,1)")
                db.execute("INSERT INTO task_tags(task_id,name,value) VALUES (41,'team','test')")
                db.execute("INSERT INTO task_checkpoints(task_id,title) VALUES (41,'Check')")
                db.execute("INSERT INTO project_comments(project_id,task_id,body) VALUES (1,41,'History')")
            app.initialize()
            app.initialize()
            detail=self.request("/api/tasks/41")[1]
            self.assertEqual(detail["task"]["parent_id"],40)
            self.assertEqual(detail["task"]["tags"],["team:test"])
            self.assertEqual(len(detail["notes"]),1)
            self.assertEqual(len(detail["checkpoints"]),1)
            self.assertEqual(detail["comments"][0]["body"],"History")
            result,edited=self.request("/api/tasks/41/edit",{"title":"Child","start_date":"2026-10-20","end_date":None})
            self.assertEqual(result,200,edited)
            self.assertEqual(edited["task"]["start_date"],"2026-10-20")
            new=self.request("/api/tasks",{"project_id":1,"title":"Next"})[1]["task"]
            self.assertGreater(new["id"],80)
            with app.connect() as db:
                self.assertEqual(list(db.execute("PRAGMA foreign_key_check")),[])
                self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='custom_task_title'").fetchone())
            self.assertEqual(len(list((app.DB.parent/"backups").glob("legacy-dates-before-optional-task-dates-*.sqlite3"))),1)
        finally:
            app.DB=original

    def test_stale_backend_refuses_writes_with_actionable_error(self):
        with patch.object(app,"backend_digest",return_value="changed-on-disk"):
            status,data=self.request("/api/projects",{"name":"Should not be created"})
            self.assertEqual(status,503)
            self.assertIn("Restart python3 server.py",data["error"])
        self.assertEqual(self.request("/api/projects")[1]["projects"],[])

    def deletion_fixture(self):
        project=self.request("/api/projects",{"name":"Delete test","tags":["team:test"]})[1]["project"]["id"]
        parent=self.request("/api/tasks",{"project_id":project,"title":"Parent","phase":"Build","tags":["owner:test"]})[1]["task"]["id"]
        child=self.request("/api/tasks",{"project_id":project,"parent_id":parent,"title":"Child"})[1]["task"]["id"]
        grandchild=self.request("/api/tasks",{"project_id":project,"parent_id":child,"title":"Grandchild"})[1]["task"]["id"]
        sibling=self.request("/api/tasks",{"project_id":project,"title":"Unrelated"})[1]["task"]["id"]
        note=self.add("Keep calendar note")
        self.action(note,"comments",{"body":"Keep note history"})
        for task_id in [parent,child,grandchild]:
            self.request(f"/api/tasks/{task_id}/checkpoints",{"title":"Check"})
            self.request(f"/api/tasks/{task_id}/notes",{"note_id":note})
            self.request(f"/api/projects/{project}/comments",{"task_id":task_id,"body":"Task history"})
        self.request(f"/api/projects/{project}/comments",{"body":"Project history"})
        return project,parent,child,grandchild,sibling,note

    def test_delete_subtask_cascades_children_but_preserves_parent_and_notes(self):
        project,parent,child,grandchild,sibling,note=self.deletion_fixture()
        status,data=self.request(f"/api/tasks/{child}/delete",{})
        self.assertEqual(status,200)
        self.assertEqual(data["parent_id"],parent)
        self.assertEqual(self.request(f"/api/tasks/{child}")[0],404)
        self.assertEqual(self.request(f"/api/tasks/{grandchild}")[0],404)
        self.assertEqual(self.request(f"/api/tasks/{parent}")[0],200)
        self.assertEqual(self.request(f"/api/tasks/{sibling}")[0],200)
        self.assertEqual(self.request(f"/api/notes/{note}")[1]["comments"][0]["body"],"Keep note history")
        self.assertEqual(self.request(f"/api/tasks/{child}/delete",{})[0],404)
        with app.connect() as db:
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")),[])
            for table,column in [("task_checkpoints","task_id"),("task_notes","task_id"),("project_comments","task_id")]:
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IN (?,?)",(child,grandchild)).fetchone()[0],0)

    def test_delete_task_cascades_descendants_keeps_project_and_sibling(self):
        project,parent,child,grandchild,sibling,note=self.deletion_fixture()
        self.assertEqual(self.request(f"/api/tasks/{parent}/delete",{})[0],200)
        self.assertEqual([task["id"] for task in self.request(f"/api/projects/{project}")[1]["tasks"]],[sibling])
        self.assertEqual(self.request(f"/api/projects/{project}")[1]["comments"][0]["body"],"Project history")
        self.assertEqual(self.request(f"/api/notes/{note}")[0],200)
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_tags").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM project_tags").fetchone()[0],1)

    def test_delete_project_cascades_work_preserves_calendar_and_other_projects(self):
        project,parent,child,grandchild,sibling,note=self.deletion_fixture()
        other=self.request("/api/projects",{"name":"Keep"})[1]["project"]["id"]
        keep=self.request("/api/tasks",{"project_id":other,"title":"Keep task"})[1]["task"]["id"]
        status,data=self.request(f"/api/projects/{project}/delete",{})
        self.assertEqual(status,200)
        self.assertEqual(data["deleted_project_id"],project)
        self.assertEqual(self.request(f"/api/projects/{project}")[0],404)
        self.assertEqual(self.request(f"/api/tasks/{keep}")[0],200)
        self.assertEqual(self.request(f"/api/notes/{note}")[1]["comments"][0]["body"],"Keep note history")
        self.assertEqual(self.request(f"/api/projects/{project}/delete",{})[0],404)
        self.assertEqual(self.request("/api/projects/99999/delete",{})[0],404)
        self.assertEqual(self.request("/api/tasks/99999/delete",{})[0],404)
        with app.connect() as db:
            for table in ["project_phases","task_checkpoints","task_notes","task_tags","project_tags","project_comments"]:
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],0,table)
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")),[])

    def test_validation(self):
        for payload in [{"date":"2026-10-17","body":"weekend"}, {"date":"bad","body":"x"}, {"date":"2026-10-12","body":"  "}, {"date":"2026-10-12","body":"x"*10001}, []]:
            self.assertEqual(self.request("/api/notes", payload)[0], 400)
        self.assertEqual(self.request("/api/notes?start=bad&end=2026-10-16")[0], 400)

    def test_cross_site_rejected(self):
        self.assertEqual(self.request("/api/notes", {"date":"2026-10-12","body":"x"}, Origin="https://example.com")[0], 403)

    def test_static_allowlist(self):
        for path in ["/", "/app.js", "/style.css"]:
            self.assertEqual(self.request(path)[0], 200)
        for path in ["/server.py", "/data/planner.sqlite3", "/../server.py"]:
            self.assertEqual(self.request(path)[0], 404)

if __name__ == "__main__":
    unittest.main()
