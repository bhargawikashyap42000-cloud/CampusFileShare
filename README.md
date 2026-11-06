# Campus File Share

A Flask + SQLite campus document-sharing starter project with separate Student, Faculty and Admin workspaces.

## Included features

- Student, Faculty and Admin sign-in with hashed passwords
- Student/Faculty self-registration (Admin accounts are not publicly registerable)
- Role-specific dashboard summaries
- Upload and download academic files
- Campus-visible and private file access
- Share a file directly with another registered email
- Search available files by name, subject or description
- Faculty/Admin subject catalogue
- Admin user list, role management and platform reports
- Profile editing
- Responsive blue campus/cloud dashboard UI

## Requirements

- Python 3.10 or newer
- Windows, macOS or Linux

## Windows setup

Open this folder in VS Code. Open Terminal and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, run the app without activating:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Student | student@campus.edu | Student@123 |
| Faculty | faculty@campus.edu | Faculty@123 |
| Admin | admin@campus.edu | Admin@123 |

Change demo passwords and `SECRET_KEY` before any real deployment.

## Notes

- The SQLite database is created automatically at `database/campus.db`.
- Uploaded files are stored in `uploads/`.
- Allowed upload types: PDF, DOC/DOCX, PPT/PPTX, XLS/XLSX, TXT, PNG, JPG/JPEG and ZIP.
- Maximum upload size is 25 MB.
- This is a local development starter. For public deployment, add HTTPS, CSRF protection, stronger secret management, malware scanning, backups, and production server configuration.
- Sample academic records are seeded automatically on first run. No fake personal documents are included.


## File visibility and sharing rules

Each uploaded file can use one of three access levels:

- **Campus:** student uploads are visible to faculty and admins; faculty uploads are visible to students and admins; admin uploads are visible to students and faculty. Students do not see other students' Campus uploads.
- **Public:** visible to all signed-in users. A student who chooses Public makes the file visible to other students too.
- **Private:** visible only to the uploader and users explicitly added through Share. Admins do not automatically get access; they can review a private file only while a report about it is pending. Private files are excluded from other users' lists and direct downloads are blocked unless access is granted.

The same access check is applied to file listings and downloads.

## Private-file moderation and admin privacy

- Admins can browse public and campus files under the normal role rules.
- Admins do **not** automatically see private file contents or download private files.
- A private file becomes visible to admins only after an authorized viewer submits a report; it remains available for admin review while that report is pending.
- Admins can mark a pending report as reviewed. Once resolved, the private file is no longer available to admins unless it is their own upload, explicitly shared with them, or a new pending report is submitted.
- Reporting is available to signed-in users who can already access the file. The report reason is stored for moderation review.

## Runtime integration tests

After installing dependencies, run the Flask integration tests from this project folder:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests cover the campus visibility matrix, public access, private-file denial, explicit sharing, and admin review access while a report is pending. They use a temporary SQLite database and temporary upload folder; your normal project database is not modified.

## Production hardening notes

Before deploying this app for real users, configure a strong random `SECRET_KEY` in the environment, use a production WSGI server (not Flask's development server), enable HTTPS, and set `COOKIE_SECURE=1`. Debug mode is off by default; only set `FLASK_DEBUG=1` for local development.

CSRF protection and audit/activity logging are included in this version. Before a public deployment, set a long random `SECRET_KEY`, set `COOKIE_SECURE=1` behind HTTPS, configure a persistent database and upload storage, and run with Waitress (or another production WSGI server) rather than Flask's development server. The included `Procfile` uses Waitress. Activity logs retain event metadata and IP addresses; do not log passwords, session tokens or file contents.

## CSRF protection and activity logs

All POST/PUT/PATCH/DELETE requests require the session CSRF token. The HTML forms include the token automatically; custom API clients must send the form field `csrf_token` or the `X-CSRF-Token` header. A rejected request receives HTTP 400. Logout uses POST so it is protected too.

Admins can open **Activity Logs** from the sidebar. Logs show the latest 300 events with actor, role, event, target, timestamp and request IP. They deliberately exclude passwords, session tokens and file contents.

## Production deployment checklist

1. Generate a unique secret with `python -c "import secrets; print(secrets.token_hex(32))"` and set it as `SECRET_KEY`.
2. Serve behind HTTPS and set `COOKIE_SECURE=1`.
3. Install dependencies with `pip install -r requirements.txt`.
4. Start the WSGI server with `waitress-serve --listen=0.0.0.0:8080 app:app` (adjust host/port for your host).
5. Configure persistent storage, database backups, upload backups and malware scanning before accepting untrusted public uploads.
6. Change the seeded demo passwords or remove demo accounts before launch.
