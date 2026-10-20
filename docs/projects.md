# Projects and Gantt foundation

This release adds functional starting points for the project workflow. Detailed
project management behavior can evolve independently of the existing calendar.

## Navigation

A bar directly below the app header links Calendar, Projects and Gantt.
Calendar is the default when opening the root URL. Pages use local hash routes:
#calendar, #projects and #gantt. Back/forward navigation works without a full page
reload. Hidden calendar DOM is retained, preserving its note forms and existing
state. No external router or framework is required.

## Projects

The upper-right + button sits immediately left of Choose a project. Its menu
opens New project, New task and New subtask dialogs. Names/titles are required;
all descriptions are optional. Switching projects shows exactly one project.

Projects can have optional tags. Enter one name:value pair per line, for example:

    priority:high
    team:engineering

Tasks reference a required project and can have a description and custom tags.
The inherited project:project_name chip is generated from the current project
name, not copied into custom tags. The reserved project tag cannot be overridden.
Project tags do not otherwise automatically copy to tasks.

New subtask asks for a related top-level task and supports an optional
description. Project membership is validated on the server. Existing deeper
subtask hierarchies remain visible, and phases and optional schedule dates are
retained for Gantt compatibility.

Tasks appear as expandable rows. Expanding a task shows subtasks and their
descriptions. Clicking a row opens a task/subtask editor with information on the left and its discussion on the right. The separate arrow expands subtasks without opening the editor.
Completed parent rows stay visible when they contain open descendants. Show
completed reveals other finished rows.

The right panel shows project discussion until a task is selected. Its heading
states Project, Task or Subtask and the item's name. Use Project discussion or
click the project heading to return to project-level comments. Comments support
add, edit and remove. Enter sends nonblank text; Shift+Enter inserts a newline.
Drafts, including comment edit drafts, are retained in memory when changing
selection within the same browser session. They are not saved until submitted
and do not survive a page reload. A creation draft prompts before being discarded.

Tasks can be completed or reopened. Checkpoints and linked calendar notes remain
available. Completing a parent does not automatically complete children.
Task and note completion are independent. Linking a note does not copy it, so
calendar edits, comments and weekly rollover retain the link. Deleting a calendar
note removes the link, not the task. Project discussions are separate from
calendar-note comment history.

## Gantt

Select one project or All projects. Tasks with both start and end dates appear
as SVG bars; start and end are inclusive. Unscheduled tasks remain in Projects
and their count is shown below the chart.

Project colors identify the main bars. A phase-colored strip and phase labels
distinguish phases, with project/phase legends above the chart. Hover a bar for
its native tooltip; bars have keyboard-accessible names and can be opened with
Enter/Space to navigate to that task in Projects. Completed bars are muted.

Rows are grouped by project and phase, then start date. Subtasks have an indent
marker. The chart scales to the date range and scrolls horizontally on small
screens. Calendar weekends are allowed in project schedules; weekly note
rollover does not move project tasks.

## Data model

All tables share the existing local SQLite file.

| Table | Main fields and relationships |
| --- | --- |
| projects | id, name, description, color, status, created_at |
| project_phases | id, project_id, name; unique name within a project |
| project_tasks | id, project_id, parent_id, phase_id, title, description, start_date, end_date, completed, created_at |
| task_checkpoints | id, task_id, title, completed |
| task_notes | task_id + note_id composite primary key; many-to-many link to calendar notes |
| project_tags | project_id, name, value composite key |
| task_tags | task_id, name, value composite key; custom tags only |
| project_comments | id, project_id, nullable task_id, body, created_at; null task_id means project discussion |

Project deletion would cascade to phases/tasks, task deletion would cascade to
children/checkpoints/note links, and note deletion removes only note links.
Project and task deletion APIs are available with explicit UI confirmation. Calendar notes and
their comments are separate entities and are never deleted by project cascading.

Start and end dates are independently optional. Each provided date must be valid YYYY-MM-DD. When both exist, start must be on or before end. Titles and names must be nonblank; project names and
phases allow 120 characters, task titles 200, checkpoints 500, descriptions 10,000.
Colors use six-digit hex. Tags accept up to 30 pairs, with an 80-character name and 200-character value. Both sides must be nonblank and single-line; splitting uses the first colon, allowing colons in values. Exact duplicate tags are removed. The API validates parent project membership and
checkpoint ownership. Writes are transactional and parameterized.

Schema creation is additive and idempotent. Restart the server to create missing
tables. Existing calendar notes are preserved. Existing backup instructions apply
to all new project data. No packages, database services, or build tools are added.

## API

All endpoints are same-origin JSON APIs, with the existing request-size and
cross-origin write restrictions.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | /api/projects | List projects |
| POST | /api/projects | Create with name, optional description/color/tags |
| GET | /api/projects/{id} | Project, task list and phases |
| POST | /api/projects/{id}/delete | Permanently delete the project and its child work; calendar notes are kept |
| POST | /api/projects/{id}/status | Set status to active, suspended, completed, rejected or closed |
| POST | /api/tasks | Create with project_id/title, optional description/tags/parent_id/phase/start_date/end_date |
| GET | /api/tasks/{id} | Task, direct subtasks, related notes and checkpoints |
| POST | /api/tasks/{id}/delete | Permanently delete task/subtask and descendants; calendar notes are kept |
| POST | /api/tasks/{id}/edit | Save title, description, tags, phase, start_date and end_date; project and parent are fixed |
| POST | /api/tasks/{id}/update | Set completed boolean |
| POST | /api/tasks/{id}/checkpoints | Add checkpoint with title |
| POST | /api/tasks/{id}/checkpoint-update | Set checkpoint_id and completed boolean |
| POST | /api/tasks/{id}/notes | Link existing note_id; repeated links are safe |
| GET | /api/projects/{id}/comments | Project-level history; optional ?task_id= for task/subtask discussion |
| POST | /api/projects/{id}/comments | Add body, optional task_id (or null for project) |
| POST | /api/projects/{id}/comment-edit | Update comment_id/body in the specified task_id context |
| POST | /api/projects/{id}/comment-delete | Remove comment_id in the specified task_id context |
| GET | /api/timeline | All projects/tasks with project and phase labels/colors |
| GET | /api/timeline?project_id={id} | Filter tasks to one project |

Invalid input returns 400, missing records or wrong ownership 404, storage
failures 503. Creation returns 201; other successful writes return 200.

## Scope for the next iteration

The initial pages support creating and exploring work, not full project
administration. Unlinking notes, dependencies, recurring tasks, progress aggregation, drag
scheduling, zoom controls and a persisted phase ordering are deferred. This
provides a working foundation for the next detailed requirements.

## Files and checks

- project_store.py: schema, project validation and persistence.
- static/workspace.js: page navigation, project interactions and SVG timeline.
- static/index.html and static/style.css: shared navigation and workspace layouts.
- server.py: same-origin API dispatch using the existing HTTP service.

The test suite now contains 27 tests. New coverage includes project/task
persistence, phase inheritance, schedule validation, parent isolation, checkpoint
ownership, duplicate note links, link cleanup, timeline filtering, and navigation
markup/static serving. Existing calendar tests remain passing.

Manual browser checklist:
1. Open / and confirm Calendar is selected; navigate all three tabs and use Back.
2. Create two projects, tasks with phases/dates, and an unscheduled task.
3. Add a subtask, checkpoints and a linked note; reopen the task to check persistence.
4. Complete/reopen tasks and toggle Show completed.
5. Filter Gantt by project, inspect tooltips, and open a task from a bar.
6. Verify project and phase colors, narrow-screen scrolling, and keyboard controls.
7. Confirm calendar autosave, comments, dragging and rollover remain usable.

A browser/JavaScript runtime is unavailable in the execution environment, so
visual and interactive verification remains manual.

## Metadata and discussion responses

Project and task responses contain a tags array of name:value strings. Task
responses additionally contain inherited_tags, including project:project_name.
Inherited tags are derived on read, so they remain consistent if project names
change later. Tasks still reference project IDs, not names.

Project detail includes project comments. Task detail includes comments for that
task alone. Dedicated comment reads/writes validate both the project and task
context, including when editing/deleting comments. Timestamps and history order
are preserved on edit. Deleting a task or project cascades its discussion; these deletion APIs are now available. Tags and comments live in additive SQLite tables
and are included in the normal database backup.

New automated tests cover optional metadata, tag validation and atomic rejection,
duplicate tags, derived inheritance after a project-name change, optional subtask
descriptions, discussion isolation, edit/delete and persistence across startup.

Manual checks for this version:
1. Use all three + menu items and cancel a creation draft.
2. Create a project with optional description/tags; switch between two projects.
3. Create a task and verify its inherited project tag and optional custom tags.
4. Create a subtask with description, expand its parent, and select the child.
5. Add separate project/task/subtask comments and check the context heading.
6. Edit/remove a comment and switch contexts with an unfinished draft.
7. Verify completed-task filtering, notes, checkpoints, and Gantt still work.

Browser interaction testing remains manual because no browser/JavaScript runtime
is installed in the execution environment.

## Task and subtask editors

The task list no longer has an outer background panel. Each task/subtask row
remains a separate card. Clicking a row or its title opens a note-style editor.
The small arrow is an independent expansion control, with an accessible expanded
state for keyboard users.

The editor has task information on the left and the same contextual comments
panel on the right. It edits title, optional description, custom tags, phase,
and schedule dates. The inherited project tag and parent/project references
remain fixed. Either or both dates may be cleared. A single date is accepted; only an inverted range or an invalid provided date is rejected. Comments can be added, edited, or removed.

Changes autosave after a 600ms pause and show Saved, Saving, or an error with a
retry action. Title cannot be blank. In-flight saves are serialized; newer
typing is not overwritten by earlier responses. Closing first flushes pending
edits and asks before discarding invalid or failed changes. Browser refresh
prompts while task edits remain unsaved.

Top-level task editors have a Subtasks section with an Add subtask form, including
title and optional description. Open a subtask from that list to edit/comment on
it independently. Checkpoint creation/completion and related calendar-note links
remain available in both kinds of editor. Project discussion closes the task
editor after flushing edits and restores the project-level discussion panel.

The new edit endpoint accepts a full field snapshot, validates tags/dates before
writing, and updates the existing task record. It preserves IDs, hierarchy,
completion, comments, note links and checkpoints. Task edits also appear in
Gantt on the next visit. No database migration or new packages are needed.

Two new tests cover persisted parent/subtask edits, timeline updates, link/history
preservation, invalid fields and atomic rollback. Manual checks should include
row expansion versus editing, autosave during typing, adding a subtask, comments,
checkpoints, linked notes, close/retry behavior, narrow layouts and keyboard use.

## Autosave and project status

Task and subtask editors save valid information automatically after a 600ms pause
and when leaving a field. The editor explicitly indicates autosave and shows
Saving/Saved or Not saved with a retry action. Text composition is allowed to
finish before saving. Pending changes flush before closing or switching records;
failed changes remain available for correction/retry or explicit discard.

Projects have a status selector in the project summary. Status options are active,
suspended, completed, rejected and closed. A selection saves immediately and
disables only that selector until the request completes. Failure restores the
previous saved value. Project creation also offers the status, defaulting to active.

Statuses are independent labels: all projects remain selectable and all
transitions are permitted. Marking a project completed/closed/rejected does not
complete tasks, hide work, or change calendar notes. No task status changes or
project filtering are inferred.

The projects.status column is added automatically on startup, defaulting existing
records to active. A database CHECK and API validation restrict its values.
The additive migration can be repeated safely and preserves project metadata.
POST /api/projects/{id}/status accepts a status string and returns the updated
project. Creation accepts an optional status; project detail/list and timeline
project responses include it.

The complete suite now has 30 integration tests, covering status transitions,
validation, persistence, legacy migration and independence from task completion,
alongside existing task/subtask edit and save APIs. Browser autosave interaction
still requires manual verification.

## Independently optional task dates

Task and subtask creation/editing accept blank dates, start only, end only, or
both. The only ordering rule is start <= end when both dates are present.
Invalid date strings are still rejected. This removes the validation error that
previously prevented autosave when only one date was entered.

Existing databases have a stricter SQLite CHECK as well as the old API rule.
Startup therefore backs up the database to data/backups/ and rebuilds that
constraint transactionally. The migration preserves task IDs, hierarchy,
completion, tags, checkpoints, linked notes, discussions, indexes and the
autoincrement sequence, then checks foreign keys. Repeated startup does not
repeat the migration. The original database remains unchanged if migration fails.

Gantt bars still require both endpoints to represent an actual duration.
Single-date tasks save normally and remain in Projects; the timeline footer
explains why those tasks have no bar. No duration is invented.

Verification: all 32 integration tests pass, including partial dates for parent
tasks/subtasks and legacy migration preservation. Real-time Edge checks passed
for start-only, end-only and blank-date autosave using temporary copies of
Read documentation, Request access and Read RTP documentation.

## Deleting projects, tasks and subtasks

The project summary has a Delete project button beside its status. Task and
subtask editors have Delete task / Delete subtask beside their completion button.
Every delete asks for explicit confirmation naming the record and explaining the
cascade. Cancel leaves data unchanged. Deletion is permanent; there is no trash.

- Project deletion removes its tasks, subtasks, phases, tags, discussions,
  checkpoints and note links.
- Task deletion removes that task and every descendant, including their tags,
  discussions, checkpoints and note links. Other project tasks remain.
- Subtask deletion removes the selected subtask and its descendants. Its parent
  and siblings remain.
- Calendar notes and their own comments always remain; only project/task links
  are removed.

Deleting a task cancels its pending autosave timer and waits for an in-flight
save before deleting, preventing a late save from racing the delete. Its confirmed
unsaved draft is discarded with the record. Failed deletes leave the editor
and draft available. Successful deletion closes the editor and refreshes rows.
Project deletion resets the project selection and removes the deleted project
from both project and Gantt pickers.

The API uses existing same-origin restrictions and transactional foreign-key
cascades. Missing records return 404; repeated deletion cannot affect another
record. No schema migration or packages are required.

Verification: all 36 integration tests pass, including nested cascade cleanup,
unrelated project/sibling preservation, note/comment preservation and foreign-key
integrity. The real-browser fixture also passes cancellation, subtask deletion,
task deletion with an autosave draft, and project-picker refresh. All deletion
tests operate on disposable records, not the user's original projects.

## Task editor scrolling

On desktop the task dialog is bounded by the viewport and has no outer scrollbar.
Task information scrolls independently in the left column, with its scrollbar
between the information and discussion columns. The right discussion panel
fills the available height. Its header and comment composer stay in place while
comment history scrolls inside the panel.

On narrow screens information and discussion stack into two bounded areas with
independent scrolling. The close control and save status remain outside those
scroll regions. Autosave and comment interactions are unchanged.

The browser fixture accepts ?layout=1 at desktop viewport sizes to verify panel
heights, left-column scrolling, stationary comments and a visible composer.

Real-browser verification passed at a 1440x1000 viewport for both task and
subtask editors: matching column heights, no outer dialog scrolling, independent
left scrolling, stationary comments and visible composer. The same run passed
autosave, partial-date saves and deletion interactions.
