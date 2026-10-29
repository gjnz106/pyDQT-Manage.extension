# pyDQT usage log

Every pyDQT tool (pyDQT-Manage and pyDQT-Design) records each run in a
Firestore collection, so you can see how many people use pyDQT, who uses
which tools, and which installs are not from the official repositories
(copied, renamed or re-hosted).

## What is recorded

One record per tool run (`event = "tool"`) and one per Revit session that
loads a pyDQT extension (`event = "session"`, from the extension's
`startup.py`):

| Field | Example |
|---|---|
| `tool` | `pyDQT-Manage / 02 Inquiry / HealthCheck` |
| `extension`, `ext_commit` | `pyDQT-Manage`, the installed git commit |
| `install_path`, `git_remote` | the extension folder and its git `origin` URL |
| `revit_user`, `windows_user`, `domain`, `machine` | who and where |
| `revit_version`, `pyrevit_version`, `os` | versions |
| `session` | the same for every record of one Revit session |
| `time` | UTC |

No project names, model content or files are recorded.

The first time a tool runs for a Windows user, a notice says what is
recorded. It is shown once, and usage logging cannot be turned off.
Records wait in `%APPDATA%\pyDQT\usage_queue.jsonl` until the notice has
been shown, and while Firestore cannot be reached (offline, or not set up
yet). They are sent with the next record that goes out, so nothing is lost.
Logging never stops a tool: every failure is ignored, and sending happens
on a background thread.

The code is `lib/dqt_usage.py`. The same file is in both extensions; keep
the two identical.

## Setup (once)

pyDQT logs to the Firebase project `pydqt-usage`: its Project ID and Web API
key are in `lib/dqt_usage.py` and `dashboard.html`. These steps are for
setting it up again, or for moving the log to another project.

1. **Firebase project.** Open https://console.firebase.google.com. Either
   create a project or use an existing one, then add a **Web app** to it.
2. **Firestore.** Go to Build › Firestore Database › Create database, in
   production mode.
3. **Rules.** In Firestore › Rules, paste `firestore.rules` from this
   folder. Replace `OWNER_EMAIL` with your Google account, then Publish.
   Under these rules anyone running pyDQT can add a record of the expected
   shape, only you can read them, and no record can be changed or deleted.
4. **Sign-in.** Go to Build › Authentication › Sign-in method and enable
   **Google**.
5. **Keys in pyDQT.** In Project settings › General, copy the **Project ID**
   and the **Web API key**. Put them in `lib/dqt_usage.py` of **both**
   pyDQT-Manage and pyDQT-Design:

   ```python
   FIREBASE_PROJECT_ID = "your-project-id"
   FIREBASE_API_KEY = "AIza..."
   ```

   The Web API key only identifies the project and is safe to ship. What
   protects the data is the rules.
6. **Dashboard.** Paste the same web-app config (`apiKey`, `authDomain`,
   `projectId`) into `firebaseConfig` at the top of `dashboard.html`.
   Google sign-in does not work from a `file://` page, so open it in one
   of these ways:
   - **GitHub Pages** (no install): in the repository's Settings › Pages,
     deploy from the `main` branch, `/ (root)`. Then add
     `gjnz106.github.io` under Firebase › Authentication › Settings ›
     **Authorized domains** - without it, sign-in is refused. The page is
     https://gjnz106.github.io/pyDQT-Manage.extension/usage-tracking/dashboard.html;
   - **Firebase Hosting:** `firebase init hosting`, copy `dashboard.html`
     into the public folder, then `firebase deploy`;
   - **locally:** run `python -m http.server 8000` in this folder, keep
     that window open, and open http://localhost:8000/dashboard.html.

   Sign in with the owner account. If sign-in or reading fails, the
   status line under Period says why.

## Dashboard

- **Users:** every person and computer, with tool runs, Revit sessions,
  their three most-used tools, Revit version and when they were last seen.
- **Tools:** every tool, with its runs, distinct users and last run.
- **Installs not from the official repositories:** extension folders that
  run under an unknown name, have no git checkout (a copied folder), or
  point to another repository. Each one lists where it is installed, on
  which computer and by whom.

## Limits

pyDQT is Python source, so someone who reads the code can remove the
logging from a copy. The log shows copies that still contain it. It
deters copying and detects it, but cannot prevent it.
