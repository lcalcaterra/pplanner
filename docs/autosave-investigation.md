# Autosave investigation

The production autosave code was left unchanged. Real-time Edge testing against
an isolated database confirmed description, title, tags, phase and schedule saves
for both new tasks/subtasks and temporary copies of these existing records:
Read documentation, Request access, and Read RTP documentation. The current
editor displayed its Saved indicator and the API returned the saved values.

The original local database lacked project_tags, task_tags, project_comments and
projects.status. This confirms the current startup migrations had not been
applied to that database. It does not independently prove which server/browser
version was previously being viewed; the reported absence of any save indicator
also differed from the current editor.

A consistent SQLite backup was created before applying the existing additive
startup migrations. The original named task records were preserved, and the
current app was started on localhost:8000. No speculative autosave patch was made.

## Browser regression fixture

Run from the project root:

    python3 tests/browser_autosave.py

Visit http://localhost:8765/autosave-test in a browser. It creates temporary
project/task data, exercises autosave, reads persisted values back from the API,
and reports JSON in the autosave-test-results element. The real database is not
modified. Stop the fixture with Ctrl+C.

To reproduce against a temporary copy of the three named existing tasks:

    python3 tests/browser_autosave.py --existing-copy

Then visit http://localhost:8765/autosave-test?existing=1. SQLite backup creates a
consistent temporary copy; migrations and test edits apply only to that copy.
Use a real-time browser for this test. Virtual-time dump-DOM execution can stop
before native dialog close events have been delivered.

If the live issue persists, capture the exact editor status or browser console/
network error and the URL/start command. Reproduce it before changing save logic.

## Confirmed follow-up cause and fix

The user subsequently supplied the exact server error: both start/end dates were
required. That API validation and its matching database CHECK were confirmed
causes for rejecting partial-date saves. Both are now fixed: dates are optional
individually, with ordering checked only when both exist.

The browser regression now exercises start-only, end-only and blank-date changes
on all three named records. It waits for actual Saved acknowledgement instead of
fixed network delays. All checks passed in real-time Edge on temporary copies.
The earlier no-code-change conclusion applied to the first investigation, before
the rejected input and validation message were known.

## Confirmed stale-process follow-up

The live server process was launched before the optional-date fix was written.
Its working directory matched this checkout and its frontend JavaScript matched
the current disk file, but it retained the old imported Python validator. The
live SQLite task table also still had the original two-dates-required CHECK.
This explains why fresh fixture tests passed while the user's server still
rejected the same partial-date saves.

The verified stale process was stopped and the current app restarted on port
8000. Startup created its migration backup and replaced the constraint. Read-only
comparison confirmed task records, tags, links, checkpoints and comments match
the backup, and foreign-key checks passed.

The backend now fingerprints server.py and project_store.py when loaded. If
those files change while it runs, writes return an explicit restart-required 503
before changing data. Restart the server after backend updates; refreshing the
browser only reloads frontend files. The full regression suite has 33 tests.
