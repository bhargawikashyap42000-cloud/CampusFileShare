# CampusFileShare verification status

## Checks completed in the packaging environment

- Python syntax compilation: PASS (`app.py`, `config.py`, `tests/test_runtime.py`).
- SQLite schema execution: PASS, including the new `activity_logs` table and index.
- CSRF template coverage: PASS; every POST form contains a CSRF token field.
- ZIP archive integrity: checked after packaging.

## Flask integration test status

**NOT RUN / BLOCKED in the packaging environment.** Flask is not installed in the available Python environment. Installing it with pip was attempted, but outbound package access failed due to DNS/network restrictions. Running the integration suite therefore stops at `ModuleNotFoundError: No module named 'flask'` before any Flask test executes. This is not a passing runtime test result.

## Run the full runtime suite on Windows

Open PowerShell in this project folder and run:

```powershell
.\run_tests.ps1
```

Or run manually:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests use a temporary SQLite database and temporary upload directory. They do not modify the real project database or uploads. The suite covers the campus/public/private permission matrix, file listing and direct-download authorization, explicit private sharing, admin moderation access while a report is pending, CSRF enforcement, activity-log recording, and admin-only access to the activity log page.
