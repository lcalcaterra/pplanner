# Pplanner

A private, single-user planner for weekly notes, projects, tasks and timelines.
It runs locally in your browser and works without an internet connection.

## Run with Docker (recommended)

Install Docker Engine with the Compose plugin, or Docker Desktop. On Windows,
start Docker Desktop and enable integration for your Ubuntu distribution under
**Settings > Resources > WSL Integration**.
See [Docker's WSL setup instructions](https://docs.docker.com/desktop/features/wsl/).

From the project folder:

```sh
docker compose up -d --build
```

Open **http://localhost:8000**. The app runs in the background and restarts when
Docker starts, unless you explicitly stopped it. The first build needs internet
access; the running app does not.

Useful commands:

```sh
docker compose logs -f
docker compose stop
docker compose up -d
```

After updating the project files, rebuild with:

```sh
docker compose up -d --build
```

Data and automatic recovery backups are stored in the **pplanner-data** Docker
volume, separate from the image. Stopping or replacing the container preserves
them. `docker compose down` also preserves the volume; **do not add `-v`**, which
deletes the stored data. See [Docker's Compose volume documentation](https://docs.docker.com/reference/compose-file/volumes/).

For a different port or timezone, create a `.env` file next to `compose.yaml`:

```dotenv
PPLANNER_PORT=8080
PPLANNER_TIMEZONE=America/New_York
```

Run `docker compose up -d` to apply it, then open **http://localhost:8080**.

The Docker volume starts empty. To bring your existing local data into Docker,
export it through **Settings > Export data** in the existing app, stop that app,
start Docker and use **Settings > Import data**. The same workflow transfers
data between Docker and a direct or systemd installation.

### Run an image from Docker Hub

Once an image built from this project's Dockerfile has been published to Docker
Hub, no source checkout or local build is needed. Replace
`YOUR_DOCKERHUB_USERNAME/pplanner:latest` with the real repository and tag:

```sh
docker run -d --name pplanner --restart unless-stopped --init -p 127.0.0.1:8000:8000 -e PPLANNER_TIMEZONE=Europe/Rome -v pplanner-data:/data YOUR_DOCKERHUB_USERNAME/pplanner:latest
```

Docker downloads the image automatically if it is not already present. Open
**http://localhost:8000**. Change the first `8000` in the port mapping to use a
different local port, for example `127.0.0.1:8080:8000`.

Manage this container with:

```sh
docker logs -f pplanner
docker stop pplanner
docker start pplanner
```

To update to a newer published image, export a backup first, then run:

```sh
docker pull YOUR_DOCKERHUB_USERNAME/pplanner:latest
docker stop pplanner
docker rm pplanner
```

Repeat the `docker run` command above. Reusing `pplanner-data` preserves your
saved workspace. The image name is a placeholder, not a claim that an image
has already been published.

Choose either Compose or the standalone Docker Hub command. Both use the same
data volume; stop the previous instance before switching.

## Run locally

### Requirements

- Python 3.12 or newer.
- A modern web browser.

No additional Python packages, Node.js, build tools or separate database service are required.

### Start and stop

Open a terminal in the project folder and run:

```sh
python3 server.py
```

Open **http://localhost:8000**. Keep the server running while using the app.
Press **Ctrl+C** in its terminal to stop it.

From Windows PowerShell with the project in Ubuntu/WSL:

```powershell
wsl -d Ubuntu-24.04 --cd /home/lcalcaterra/personal-projects/pplanner python3 server.py
```

If port 8000 is already in use, the app may already be running. Open its address,
stop the existing server before restarting, or choose another port:

```sh
python3 server.py --port 8080
```

Then open **http://localhost:8080**.

After updating the app, stop and restart the server, then refresh the browser.

### Local data and timezone

Data is saved automatically in `data/planner.sqlite3` and remains available
after restarting the app. The database folder is created on first run.

To use a different database location in Ubuntu/WSL:

```sh
PPLANNER_DB=/absolute/path/to/planner.sqlite3 python3 server.py
```

The default planner timezone is **Europe/Rome**. To change it:

```sh
PPLANNER_TIMEZONE=America/New_York python3 server.py
```

The app listens on `127.0.0.1` by default and is intended for local use by one
person. It has no login.

## Run as a systemd service (Linux)

This starts Pplanner in the background at boot without a terminal. Use Linux
with systemd and Python 3.12 or newer installed at `/usr/bin/python3`.
Check the version with `/usr/bin/python3 --version`.

From the project folder, install the app and supplied service:

```sh
sudo install -d -m 755 /opt/pplanner
sudo install -m 644 server.py project_store.py backup_store.py /opt/pplanner/
sudo cp -r static imgs /opt/pplanner/
sudo install -m 644 deploy/pplanner.service /etc/systemd/system/pplanner.service
sudo systemctl daemon-reload
sudo systemctl enable --now pplanner
```

Open **http://localhost:8000**. Stop any manually started or Docker instance using
port 8000 before starting this service.

The service uses its own account managed by systemd. Data and recovery backups
are stored in **/var/lib/pplanner/** and remain when the service stops.
Use the app's export/import controls to transfer an existing workspace.
This uses systemd's [persistent state directory support](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#StateDirectory=).

Manage the service with:

```sh
sudo systemctl status pplanner
sudo journalctl -u pplanner -f
sudo systemctl restart pplanner
sudo systemctl stop pplanner
```

To disable automatic startup:

```sh
sudo systemctl disable --now pplanner
```

For a different port or timezone, run `sudo systemctl edit pplanner` and add:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 /opt/pplanner/server.py --host 127.0.0.1 --port 8080
Environment=PPLANNER_TIMEZONE=America/New_York
```

Then run `sudo systemctl daemon-reload` and `sudo systemctl restart pplanner`.

To update the installed application, export a backup, stop the service, repeat
the app-file installation commands above and restart the service. Keep
`/var/lib/pplanner/` in place.

On WSL, systemd must be enabled first; follow
[Microsoft's systemd instructions](https://learn.microsoft.com/windows/wsl/systemd).
The service starts when the WSL distribution starts, rather than guaranteeing
startup at Windows sign-in.

## Calendar and notes

Calendar is the default page and shows Monday through Friday.

- Move one week at a time with the arrows, return with **This week**, or choose
  a date with the calendar icon to open that date's week.
- Click **+** on a day to create a note with a required title, optional
  description, date, project and tags.
- Click a note to edit it. Changes save automatically; wait for **Saved**
  before leaving. Descriptions appear only in the note editor.
- Assign a project to display its name and color on the note card.
- Enter optional tags as `name:value`, one per line.
- Drag notes to reorder them within a day or move them between weekdays of
  the same week. Change the date in the editor to move to another week.
- Click a note's circle to complete or reopen it. Completed notes appear
  muted below unfinished notes.
- Delete a note using its bin icon and confirm. This also deletes its comments.
- Scroll within a day to see more notes. On smaller screens, scroll
  horizontally to reach the other days.

### Weekly rollover

Every Monday, unfinished notes from earlier weeks move to the current Monday.
Completed notes stay on their original dates. Comments, descriptions, tags and
project links are preserved.

If the server was stopped, rollover happens when it starts again.
Notes in the current week and future weeks remain on their selected dates.

## Projects, tasks and subtasks

Use **Projects** in the navigation bar to manage one project at a time.

- The most recently viewed unfinished project opens automatically in the same
  browser. If unavailable, the newest unfinished project opens instead.
- Use **+** beside the project selector to create a project, task or subtask.
- Projects support optional descriptions, tags and a project color.
- Tasks belong to a project and support descriptions, tags, phases and dates.
  Tasks automatically inherit a `project:project_name` tag.
- Subtasks belong to a parent task and support descriptions and editable
  activity information.
- Expand a task using its arrow to view subtasks. Click a task or subtask to
  open its editor, where changes autosave.
- Drag task rows to reorder them. Subtasks can be reordered only within the
  same parent. **Alt+Up/Down** also reorders a focused row.
- Add checkpoints and link calendar notes from a task editor.
- Start and end dates are independently optional. When both are supplied,
  the start date must be on or before the end date.
- Task lists and discussion history scroll independently.

### Activity status and priority

Task and subtask editors have autosaved menus:

- **Status:** Open, Locked, Update required, Loading or Completed.
- **Priority:** None, High, Medium or Low.

Status icons appear before the phase or subtask count; priority icons appear
beside the title. Open and None have no icon. Locked is a label and does not
prevent editing. Enable **Show completed** to include completed activities.

### Project status and restoration

Projects can be **Active**, **Suspended**, **Completed**, **Rejected** or **Closed**.

Completed projects are hidden from the Projects selector and task/subtask
creation choices. Other project statuses remain selectable.

To bring a completed project back:

1. Open **Settings > Restore projects**.
2. Select a completed project.
3. Choose **Restore as Active** and confirm.

The project opens in Projects with all its related data preserved.

### Deletion

Delete a project, task or subtask from its corresponding controls and confirm.
Deletion is permanent. Deleting a project removes its tasks and subtasks;
deleting a task removes its subtasks. Associated discussions, checkpoints and
links are removed, but linked calendar notes and their own comments are kept.

## Gantt

Use **Gantt** to view schedules for one project or all projects.

- Project colors and phase indicators distinguish activities.
- Hover over or focus a bar to see its details.
- Select a bar to open the task. For a completed project, this opens the
  restoration page.
- A task needs both start and end dates to appear as a timeline bar.

## Comments

Notes, projects, tasks and subtasks have their own comment histories.

- Type a comment and click the send icon or press **Enter**.
- Use **Shift+Enter** for a new line.
- Select text and use the formatting toolbar for **bold**, italic, underline,
  strikethrough, highlighting, bulleted or numbered lists. The more menu adds
  quotes, code, links and clear formatting.
- Formatting uses lightweight text markers while editing; choose **Preview**
  to see the formatted result before sending. Saved comments display formatting.
- **Ctrl+B**, **Ctrl+I** and **Ctrl+U** (or Cmd on macOS) format selected text.
- Formatting is available for new comments and comment edits on notes, projects,
  tasks and subtasks. Existing text and formatting are preserved in backups.
- Blank comments cannot be submitted.
- Use a comment's three-dot menu to edit or remove it.
- Comment submission is explicit; comment drafts do not autosave.
- History scrolls while the comment input remains available.

## Export and import

Open **Settings** in the upper bar.

### Export data

Choose **Export data** to download a `.pplanner` backup containing all saved
planner data, including notes, projects, tasks, subtasks, schedules, comments,
tags, statuses, priorities, checkpoints, links and ordering.

Unsaved drafts, browser-local preferences, application files and images are not
included. Backup files contain readable private content, so store them securely.

### Import data

1. Choose **Import data**.
2. Select a previous Pplanner export or drag it into the upload area.
3. Review the summary and check the replacement confirmation.
4. Choose **Replace data**.
5. After success, choose **Open restored planner**.

Import replaces all current planner data rather than merging it. The app
validates the backup before replacement and rejects incompatible or invalid
files. The upload limit is 64 MiB including the request wrapper.

A recovery backup is saved automatically in `data/backups/` before replacement,
or in `backups/` beside a custom database location. Recovery files can be imported
through the same dialog. Validation or storage failures leave current data
unchanged. Normal weekly rollover applies when restored data is opened.
