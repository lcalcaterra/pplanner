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
