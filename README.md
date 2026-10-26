# Pplanner

A small, private, open-source weekly calendar for one person. Inspired by the
simplicity of a planner, with a focus on notes rather than tasks. MIT licensed.

## First release

- Monday?Friday calendar with previous/next week arrows and a ?This week? shortcut.
- Day headers with date, day name, and an add button; current day highlighted.
- Inline form with a default date, multiline note, insert and cancel controls.
- Change the date to another weekday, including one outside the visible week.
- New notes appear first among unfinished notes. Each day scrolls vertically with the mouse.
- Drag notes between weekdays of the same week or reorder them within a day.
- Click a note circle to complete it: checked, muted, and below unfinished notes.
- Narrow screens scroll the five-day calendar horizontally.
- SQLite persistence across refreshes and restarts.
- Keyboard-accessible controls, visible focus, status announcements, reduced-motion support.
- Click a note to edit its text and date in a dialog with a comment history panel.
- Delete notes with the bin icon after confirmation.
- Placeholder logo; disabled settings button.

No accounts, analytics, external fonts, cloud connections, or third-party scripts.
Notes are plain text and rendered safely as text.

## Stack and installation

Python **3.12 or newer**, its standard-library HTTP server and SQLite module,
plus native HTML, CSS and JavaScript. No pip/npm dependencies, build step,
JavaScript framework, or separate database service.

This workspace already had Python 3.12.3. **No software or packages were installed.**
The SQLite database and its folder are created automatically on first run.
Node.js is not required.

## Run

From this folder in Ubuntu/WSL:

```sh
python3 server.py
```

Open **http://localhost:8000** in your browser. Stop with **Ctrl+C**.

From Windows PowerShell:

```powershell
wsl -d Ubuntu-24.04 --cd /home/lcalcaterra/personal-projects/pplanner python3 server.py
```

Change the port if needed:

```sh
python3 server.py --port 8080
```

The default bind address is 127.0.0.1. Run the server while using the app.
An internet connection is not needed. All assets are served locally.

## Using the calendar

Click + on a day, enter your note, and select Insert note. The date initially
matches that day. Only Monday?Friday dates are accepted because this release
shows working days. Notes can contain up to 10,000 characters. If saving fails,
the form retains your text for retrying.

Use the arrows to move exactly one week at a time. ?This week? returns to the
current week. Scroll inside a day when its notes exceed the available space.
A new note is placed above all unfinished notes, regardless of its creation timestamp.
Manual ordering is saved and takes precedence after you move notes.
There are deliberately no demo notes in your private database.

## Data, privacy and backups

Default database: `data/planner.sqlite3`, excluded from version control.
Dates use YYYY-MM-DD calendar dates; the server timezone chooses the current week (Europe/Rome by default). Creation timestamps are UTC and shown in your browser's timezone.

To make a simple backup, **stop the server first**, then copy the entire `data/`
directory to a safe location. To restore, stop the server and replace that
directory with the backup. SQLite uses WAL mode, so copying only the main file
while running can omit recent writes.

For a different database location:

```sh
PPLANNER_DB=/absolute/path/to/planner.sqlite3 python3 server.py
```

The database is not encrypted. Your operating system account and filesystem
permissions protect it. This version has no login and is intended for local use
by one trusted user. Do not expose it directly to the internet. If adding remote
access later, place it behind authenticated HTTPS access and review the server
deployment. The standard-library server is suitable for this small local
workflow, not a hardened public application server.

## Project layout

```text
server.py              HTTP server, validation, SQLite persistence
static/index.html      Accessible page structure and day template
static/style.css       Responsive calendar styling
static/app.js          Week navigation, inline forms, API interactions
imgs/                  Local PNG icons for navigation, settings and adding notes
tests/test_server.py   Isolated HTTP/database integration tests
data/                  Local runtime data (ignored)
LICENSE                MIT license
```

## API

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | /api/clock | Returns the current planner date and Monday as { "today": "YYYY-MM-DD", "week": "YYYY-MM-DD" } |
| GET | /api/notes?start=YYYY-MM-DD&end=YYYY-MM-DD | Returns { "notes": [...] } for the inclusive date range, unfinished first, then saved position |
| GET | /api/notes/{id} | Returns { "note": {...}, "comments": [...] }, comments oldest first |
| POST | /api/notes/{id}/edit | Accepts { "date": "YYYY-MM-DD", "body": "..." }; returns the updated note and ordered notes for affected days |
| POST | /api/notes/{id}/comments | Accepts { "body": "..." }; returns 201 with { "comment": {...} } |
| POST | /api/notes/{id}/comment-edit | Accepts { "comment_id": 123, "body": "..." }; returns the updated comment |
| POST | /api/notes/{id}/comment-delete | Accepts { "comment_id": 123 }; removes the comment |
| POST | /api/notes/{id}/delete | Accepts {}; deletes the note and its comments, returns remaining notes for its day |
| POST | /api/notes/{id}/move | Accepts { "date": "YYYY-MM-DD", "before_id": 123 }; omit before_id or use null to append within the completion group |
| POST | /api/notes/{id}/complete | Accepts { "completed": true } or false |
| POST | /api/notes | Accepts { "date": "YYYY-MM-DD", "body": "..." }; returns 201 with { "note": {...} } |

A note contains `id`, `date`, `body`, `created_at`, `completed` (0 or 1), and `position`.
Notes are ordered by date, completion group (unfinished first), then saved position.
Validation errors use 400; oversized requests use 413; wrong content type uses
415; cross-origin browser writes use 403. SQL statements use bound parameters.
Static serving uses an explicit allowlist; the database is never a static asset.
The frontend has no CORS dependency and the server applies a restrictive CSP.
An index on date, completion and position keeps week queries efficient; one short SQLite
transaction handles each insert. No in-memory note cache is required.

## Development and verification

Edit the files directly and refresh the browser. Restart Python after server
changes. Run the automated tests from the project root:

```sh
python3 -m unittest discover -s tests -v
```

Tests create temporary databases and HTTP servers; they do not touch your notes.
They cover saved-note persistence, default and manual ordering, same-week moves,
completion/reopening, migration, invalid insertion points, atomic failure handling,
week filtering, invalid dates/content, cross-origin writes, and static-file isolation.

Manual UI checklist:
1. Open this week and confirm the Monday?Friday dates and current-day highlight.
2. Add two notes to a day; refresh and confirm the newer one is first.
3. Change a note's date to another weekday and confirm its destination.
4. Navigate across month/year boundaries and return with This week.
5. Add enough notes to scroll a column; try a narrow browser window.
6. Disconnect/stop the server while saving and confirm the form keeps its text.
7. Navigate and submit using only the keyboard.

## Scope and next steps

This release supports adding, editing, deleting, moving, ordering, completing notes,
and adding comments. Search, export,
weekends, accounts, reminders, and active settings are not implemented.
There is no Microsoft integration or Microsoft affiliation.
Schema upgrades preserve existing notes; see migration guidance below.

### Interface icons

Buttons use the supplied imgs/left-arrow.png, right-arrow.png,
settings.png, add.png, and bin.png. Replace those files to customize the icons.
The server serves only those five image paths, with the matching PNG or WebP content type (the supplied .png files contain WebP images).
Button labels remain available to screen readers; settings remains inactive.

## Moving and completing notes

Drag a note by its card. Drop above another note to insert it
there, or below the final note to append it. A highlighted column and insertion
line indicate the destination. Near the top or bottom of a day, dragging scrolls
the column. Movement is limited to Monday?Friday of the note's existing week.

Reorder notes by dragging within a day or move them by dragging to another weekday.
To change a date without dragging, open the note editor and edit its Date field.

Click the circle to complete a note. A check appears and the card becomes muted;
it moves to the end of the day's completed notes. Click again to reopen it and
move it to the top of the unfinished notes. Completed notes can be reordered or
moved between days, but always remain below unfinished notes.

All changes save immediately. The UI updates after the server confirms the
change. If saving fails, the existing note order and completion state are retained
and an error is shown. Mutations are serialized in the UI; multiple browser tabs
are not synchronized live, so refresh another tab to see changes.

Move and completion endpoints return the ordered notes for the affected day(s).
Moves include a dates array. Invalid moves return 400 and missing notes return
404. Insertion points must belong to the destination day and completion group.
Writes use an immediate transaction so validation or storage failures do not
partially move or reorder notes.

## Database upgrade

Stop the server and back up data/ before upgrading an existing installation,
then restart with python3 server.py. Startup automatically adds the completed
and position columns if absent and creates the comments table and index. Existing notes remain unfinished and keep their
previous newest-first order. The migration runs inside a SQLite transaction and
can safely run again. No package installation is needed.

Additional manual checks:
1. Drag a note within a day, refresh, and confirm the order persists.
2. Drag between weekdays, including into an empty day; check both note counts.
3. Complete several notes and verify they remain below unfinished notes.
4. Reopen a note; confirm it moves to the top, then refresh.
5. Open a note with the keyboard and change its date in the editor.
6. Drag near the edge of a long day to scroll and drop at the desired position.
7. Stop the server and try a move/completion; verify an error appears without
   changing the displayed notes.

Automated verification covers the HTTP/database behavior. Browser interaction
and visual checks must be run manually in an environment with a browser.

## Note editor, comments and deletion

Click a note's text or card background to open its editor. Keyboard users can
focus the card and press Enter or Space. Completion, movement and bin buttons
act independently of opening the editor. Dragging still works from the card.

The dialog shows the note date and full text on the left, with comment history
and a new-comment form on the right. On narrow screens the comment panel appears
below the editor. Note text and date changes save automatically after a short pause. The date can be any weekday,
including a different week; if that week is not visible, the dialog tells you
where to find the saved note. Editing text alone preserves order. Changing the
date places unfinished notes first and completed notes last in the destination
day's respective group.

The compact send button inside the comment box saves a timestamped plain-text comment. Enter sends it; Shift+Enter inserts a line break. Comments are
shown oldest first and kept when the note's text or date changes. Note text and
comments accept 1?10,000 characters. An unsaved comment draft is separate from
autosaving the note. Closing first flushes pending note changes; remaining drafts or failed saves trigger a discard confirmation. Failed saves retain the text for retrying.

The bin icon in the upper-right of a note deletes it after confirmation.
Deletion is permanent and also deletes its comments; there is no recycle bin.
The supplied bin.png contains WebP data and is served with the matching MIME type.

Comments are stored in the same local SQLite database and included in existing
backup procedures. The comments table has an indexed note_id foreign key with
ON DELETE CASCADE; foreign-key enforcement is enabled on each connection.
Existing notes are preserved when startup creates the new table.

Verification now includes 18 HTTP/database integration tests covering editing
and its validation, text-only order preservation, moving to another week,
persistent comment history, deletion cascading, and the bin asset.

Manual UI checks:
1. Click a note, edit text and date, wait for Saved, and reopen it.
2. Add two comments; close/reopen and refresh to confirm their history persists.
3. Edit the date into a different week and navigate there after closing.
4. Press Escape with unsaved text and verify the discard prompt.
5. Click complete and the bin; confirm they do not open the editor.
6. Cancel a bin confirmation, then delete a disposable note and verify it disappears.
7. Drag a card and confirm dropping it does not accidentally open the editor.
8. Test Tab/Enter navigation, small-screen layout, and save failure with the server stopped.

## Comment actions and compact editor

Each comment has a three-dot disclosure in its upper-right corner. Open it to
choose Edit comment or Remove comment. Edit opens an inline textarea with Save
and Cancel buttons; saving updates the text while retaining the original
timestamp and history position. Removing asks for confirmation and permanently
deletes only that comment. Deleting the final comment restores the empty-history
message. Failed operations retain the existing comment and any edit draft.

Closing the editor with an unsaved comment edit also triggers the discard prompt.
Menus and inline forms support keyboard navigation; Escape closes an open menu
before closing the note editor. No database migration or packages are needed for
these actions. The API checks that a comment belongs to the specified note,
validates its ID and text, and commits each edit/delete in a transaction.

The week title uses an ASCII hyphen (for example, October 12 - 16). The note dialog
has a compact header without the large title, and a narrower, rounded comments
panel. On small screens the panel remains below the note form.

Additional verification: edit a comment, reopen the note, then remove comments
including the final one. Try Cancel, blank edits, keyboard menus, and a save with
the server stopped. Automated tests cover persistence, ordering, preserved
timestamps, validation, missing comments, and comment ownership.

## Automatic weekly rollover

At the start of each Monday, unfinished notes from earlier weeks move to Monday
of the current week. Completed notes stay on their original dates. Notes already
in the current week and future notes are untouched. Comments, note IDs, completion
state and creation timestamps are preserved.

Carried notes are placed after Monday's existing unfinished notes. Their previous
date and saved order determine their order within the carried group. New notes
still appear first, and you can manually reorder everything afterward.

Rollover runs once per week. A persistent app_state record and an immediate
SQLite transaction make repeated or simultaneous checks safe. The state and note
moves commit together; if a write fails, no partial rollover is saved and the next
check retries. The app_state table is created automatically without losing notes.

The running server checks every 30 seconds, even with no browser open. It also
checks at startup and before API requests. If the server was stopped for several
weeks, the next startup carries all unfinished notes from earlier weeks directly
to the current Monday. The first startup after this upgrade also carries existing
overdue unfinished notes. Nothing can run while the computer/server is off.

After that week's rollover, notes intentionally created, moved or reopened in a
past week remain there until the next weekly rollover. Navigating past or future
weeks does not change the rollover target: it is always the real current week.

The calendar checks its date every minute and when the tab regains focus. If you
were viewing the current week it advances to the new week; browsing another week
keeps that view. Refreshing waits while an editor, note form, save or drag is
active, preserving drafts. When saving a note left open across rollover, its
rolled date is retained unless you explicitly changed its date.

### Timezone

The default timezone is Europe/Rome, including daylight-saving changes.
Configure another IANA timezone when starting the service:

    PPLANNER_TIMEZONE=America/New_York python3 server.py

The calendar uses the server's planner date so its current-day highlight and week
agree with rollover even if the browser uses a different timezone. Creation
timestamps remain UTC and are displayed in the browser's timezone. The Linux/WSL
system timezone database supplies timezone rules; no new packages were installed.

Tests use a controlled date and temporary databases. They cover Sunday/Monday,
catch-up after missed weeks, year boundaries, completed and future notes, order,
comments and timestamps, once-per-week persistence, concurrent checks, background
checking, and the Rome/UTC date boundary. Browser refresh and draft preservation
still require manual browser verification.

## Autosave and comment shortcuts

The note editor has no Save changes button. Description and date changes are
debounced for 600 milliseconds. The small status below the note shows Unsaved
changes, Saving..., Saved, or Not saved. Empty descriptions and invalid/weekend
dates are not saved. Failed saves retain your text and show Retry saving.

Only one note save runs at a time. Typing remains possible during autosave;
a response acknowledges only its saved snapshot and cannot replace newer typing.
Pending changes are flushed before closing or submitting a comment action.
Browser refresh/close prompts when drafts or a save are still pending; wait for
Saved before leaving. A failed save can be retried or explicitly discarded.

The comment composer has a compact arrow button inside the bottom-right corner.
It is disabled for blank/whitespace-only comments. Enter sends a nonblank comment;
Shift+Enter creates a new line. Text-composition Enter presses do not send.
Comments remain explicit submissions rather than being autosaved, and a failed
submission retains the draft. Existing comment editing retains its Save/Cancel
controls. No server API changes or additional dependencies are needed.

Manual verification for this change:
1. Type quickly and confirm Saved appears after a pause; reopen to check persistence.
2. Continue typing while a save is in progress and verify the latest text remains.
3. Change the date, then close immediately and confirm the change is saved.
4. Stop the server, edit, confirm Not saved and retry after restarting it.
5. Try blank comments, Enter submission, Shift+Enter, and the inline send button.
6. Submit while a note autosave is pending and confirm one comment is added.
7. Close with a comment draft and confirm the discard prompt.

## Interface design

The interface uses a warm paper background with a deep ink header and lilac
accents. Each weekday has a soft accent color; today uses a filled date tile.
Week navigation is grouped beside the date heading. Cards use subtle elevation,
visible completion circles, and clear hover/focus and drag/drop states.

The note editor uses the same palette, rounded fields and a compact comments
panel. Autosave, Enter-to-send comments, comment menus, dragging, completion,
deletion and weekly rollover retain their existing behavior. The per-card
up/down controls and weekday dropdown remain removed.

The five-column calendar scrolls horizontally on smaller screens and each day
scrolls vertically. The editor stacks its comments panel below the note on
phones. Visible keyboard focus, reduced-motion support, forced-colors fallback,
accessible control names and the supplied local image icons are retained.
Typography uses system fonts and Georgia; no external assets or packages are
required. Theme colors and shared values live at the top of static/style.css.

For visual review, check the calendar with empty days, long notes, completed
notes, a full scrolling column and the editor. Also try narrow screens, keyboard
navigation, a dragged note, save failures, comment menus and reduced motion.
The presentation update preserves every existing HTML element ID used by the
JavaScript. Interactive browser verification requires a local browser.

## Calendar, Projects and Gantt

Use the navigation bar below the app header to switch pages. Calendar remains
the default. Projects and Gantt are now backed by the same local SQLite database.

Projects includes project creation/selection, open tasks, task and subtask
creation, related calendar notes and checkpoint lists. Gantt shows scheduled
tasks for one or all projects with project/phase colors, labels and tooltips.

See [Projects and Gantt documentation](docs/projects.md) for the data model,
endpoints, current scope, and manual verification checklist. Restart the server
after updating to create the new tables, then refresh the browser. No new
dependencies or configuration are required. The complete integration suite
contains 22 tests.

## Projects page: creation menu, tags and discussions

Use + beside Choose a project to create a project, task or subtask. Project/task
descriptions and name:value tags are optional; subtask descriptions are optional.
Tasks display the inherited project:project_name tag automatically.

Choose one project to see expandable task rows and subtasks. The right-hand
comment panel follows the selected project/task/subtask, with a labeled context
and a Project discussion shortcut. Existing note links, checkpoints and Gantt
schedules are preserved. Details and API documentation are in docs/projects.md.

Restart the server to create the additive tag/comment tables, then refresh.
No packages were installed. All 25 integration tests pass; interactive browser
verification remains manual.

## Task/subtask editing

Task rows now sit directly on the Projects page. Click a row to open a task editor
with autosaving information on the left and comments on the right; use its arrow
to expand the hierarchy independently. Top-level task editors include subtask
creation. Existing checkpoints and calendar-note links remain available.

All 27 integration tests pass. See docs/projects.md for editing behavior, API
details and the manual browser checklist. Restart the server and refresh after
upgrading; no new dependencies are required.

## Project lifecycle

Project summaries now include an autosaving status selector: Active, Suspended,
Completed, Rejected or Closed. New and existing projects default to Active unless
another status is chosen at creation. Status changes do not alter task completion.

Task and subtask editors explicitly indicate autosave, save after a typing pause,
and flush changes when leaving a field. Restart the server for the automatic
project-status migration, then refresh your browser. The full integration suite
now contains 30 tests. See docs/projects.md for details.

## Optional task dates fix

Task and subtask start/end dates are independently optional. Blank dates or only
one date now save normally. With both dates present, start must be <= end.

Restart the server, then refresh the browser. Startup automatically backs up and
migrates the old database constraint while preserving existing task relationships.
Gantt bars require a complete range; incomplete ranges remain saved in Projects.

All 32 integration tests and real-browser partial-date autosave checks pass.

## Restart after backend changes

Stop the running service with Ctrl+C and rerun python3 server.py after changes
to server.py or project_store.py. A browser refresh does not reload Python code.
The server detects changed backend files and refuses writes with a clear
restart-required message rather than applying stale validation. Pending drafts
remain in the editor. The regression suite currently contains 33 tests.

## Delete projects and work

Use Delete project beside the project's status, or Delete task / Delete subtask
inside its editor. Confirmations explain the records removed. Child work and its
discussion/checkpoints are deleted; linked calendar notes and note comments are
preserved. Deletion is permanent.

All 36 integration tests and real-browser delete/cancel/autosave checks pass.
See docs/projects.md for cascade behavior. Restart the backend after upgrading;
a browser refresh alone does not reload Python code.

### Note tags

Calendar notes support optional tags in the same `name:value` format as projects and tasks. Enter one tag per line when creating a note or editing it. Tags appear as chips on calendar cards and autosave with the note; clear the field to remove them. Whitespace and duplicate tags are normalized. Each note supports up to 30 tags (name: 80 characters, value: 200 characters).

Tags are stored locally in SQLite in the `note_tags` table, linked to notes with cascading deletion. Existing notes start without tags; moving, completing, or rolling notes into a new week preserves their tags. Restart the server after upgrading so the additive database migration runs. The note create/edit APIs accept a `tags` array of strings; omitting it during an edit preserves existing tags.

### Project colors and jumping to a week

Select an optional **Project** when creating or editing a calendar note. Each note links to one project and displays its name and a tint of its color; changing the selection autosaves. Other name:value tags remain independent. Project links survive note moves and rollover. Deleting a project removes the link while preserving the note and comments. The API accepts nullable `project_id`; omitted on edits preserves the link. The additive `note_projects` table stores links by project ID.

Click the calendar icon next to **This week** to choose a date using your browser's month/date picker. Any selected date opens its Monday?Friday week, including dates across month/year boundaries. The Calendar navigation button also uses `imgs/calendar.png`. Restart the server once after updating, then refresh the browser.

### Ordering project tasks

Drag task and subtask rows above or below another sibling to arrange them. A purple insertion line previews the drop position. Alt+Up/Down also reorders the focused row. Order saves immediately and persists across reloads. Top-level tasks remain in their project; subtasks remain under their existing parent. When completed tasks are hidden, drag and drop moves among visible siblings. New tasks and subtasks appear first. Existing order is preserved during the automatic migration on server restart.

SQLite stores a `position` on each task. `POST /api/tasks/:id/move` accepts `before_id` (a sibling task ID, or null to move last), validates sibling membership and saves the order atomically.

### Task status and priority

Tasks and subtasks have autosaved Status and Priority menus in their editor. Status values are Open (default, no icon), Locked, Update required, Loading, and Completed. Priority values are None (default, no icon), High, Medium, and Low. Priority icons appear beside the row title; status icons appear before the phase (subtasks) or subtask count (tasks). The supplied PNG assets also preview the selected menu value.

Completed status follows the existing Show completed filter. Other statuses remain open activities; Locked is a label, so editing remains available. Existing completed tasks migrate to Completed; all other existing tasks default to Open and None. Status and priority persist in SQLite; create/edit task APIs accept `status` and `priority`. The legacy completion API remains synchronized with status. Restart the server after updating to apply the additive migration.
