import os
import sqlite3
import uuid
import secrets
import hmac
from functools import wraps
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "png", "jpg", "jpeg", "zip"}

def db():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL COLLATE NOCASE,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','faculty','student')),
        department TEXT DEFAULT 'General',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT NOT NULL UNIQUE,
        faculty_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(faculty_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_name TEXT NOT NULL,
        stored_name TEXT NOT NULL,
        description TEXT DEFAULT '',
        subject_id INTEGER,
        uploader_id INTEGER NOT NULL,
        visibility TEXT NOT NULL DEFAULT 'campus',
        size INTEGER NOT NULL DEFAULT 0,
        downloads INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
        FOREIGN KEY(uploader_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(file_id, user_id),
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS file_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        reporter_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','reviewed','dismissed')),
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
        FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER,
        action TEXT NOT NULL,
        target_type TEXT DEFAULT '',
        target_id INTEGER,
        details TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_activity_logs_created ON activity_logs(created_at DESC);
    """)
    conn.commit()

    demo_users = [
        ("Campus Admin", "admin@campus.edu", "Admin@123", "admin", "Administration"),
        ("Aarav Verma", "student@campus.edu", "Student@123", "student", "Computer Science"),
        ("Dr. Sharma", "faculty@campus.edu", "Faculty@123", "faculty", "Computer Science"),
    ]
    for name, email, password, role, dept in demo_users:
        exists = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users(name,email,password,role,department) VALUES(?,?,?,?,?)",
                (name, email, generate_password_hash(password), role, dept)
            )
    conn.commit()

    if conn.execute("SELECT COUNT(*) AS n FROM subjects").fetchone()["n"] == 0:
        faculty = conn.execute("SELECT id FROM users WHERE email='faculty@campus.edu'").fetchone()
        fid = faculty["id"] if faculty else None
        conn.executemany(
            "INSERT INTO subjects(name,code,faculty_id) VALUES(?,?,?)",
            [("Database Management Systems","CS301",fid),("Python Programming","CS202",fid),
             ("Computer Networks","CS305",fid),("Software Engineering","CS401",fid),
             ("Data Structures","CS203",fid)]
        )
        conn.commit()

    if conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"] == 0:
        faculty = conn.execute("SELECT id FROM users WHERE email='faculty@campus.edu'").fetchone()
        faculty_id = faculty["id"] if faculty else 1
        sample_dir = os.path.join(os.path.dirname(__file__), "sample_materials")
        samples = [
            ("DBMS_Study_Notes.txt", "Quick reference covering relational databases, keys, normalization and SQL.", "CS301"),
            ("Python_Programming_Notes.txt", "Starter notes on Python syntax, data types, functions and file handling.", "CS202"),
            ("Computer_Networks_Notes.txt", "Introductory notes on network models, protocols and addressing.", "CS305"),
        ]
        for filename, description, subject_code in samples:
            source = os.path.join(sample_dir, filename)
            if os.path.exists(source):
                stored = "sample_" + filename
                destination = os.path.join(app.config["UPLOAD_FOLDER"], stored)
                if not os.path.exists(destination):
                    import shutil
                    shutil.copy2(source, destination)
                subject = conn.execute("SELECT id FROM subjects WHERE code=?", (subject_code,)).fetchone()
                conn.execute(
                    "INSERT INTO files(original_name,stored_name,description,subject_id,uploader_id,visibility,size) VALUES(?,?,?,?,?,?,?)",
                    (filename, stored, description, subject["id"] if subject else None, faculty_id, "campus", os.path.getsize(destination))
                )
        conn.commit()
    conn.close()

def csrf_token():
    """Return a per-session CSRF token for HTML forms."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_state_changing_requests():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        supplied = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            abort(400, description="Invalid or missing CSRF token.")


def log_activity(action, target_type="", target_id=None, details="", actor_id=None):
    """Write an audit event without storing passwords, tokens or file contents."""
    actor_id = actor_id if actor_id is not None else session.get("user_id")
    conn = db()
    conn.execute(
        "INSERT INTO activity_logs(actor_id,action,target_type,target_id,details,ip_address) VALUES(?,?,?,?,?,?)",
        (actor_id, action, target_type, target_id, str(details)[:500], request.remote_addr or "")
    )
    conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def current_user():
    if "user_id" not in session:
        return None
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return user

def file_access_filter(role, user_id, alias="f"):
    """Build the visibility rule used by listings, dashboards and downloads.

    public: every signed-in user can view the file.
    campus: student uploads -> faculty/admin; faculty uploads -> students/admin;
            admin uploads -> students/faculty. Students do not see other students' campus files.
    private: uploader, admin, and explicitly shared recipients only.
    """
    shared_or_owned = (
        f"{alias}.uploader_id=? OR "
        f"EXISTS (SELECT 1 FROM shares sh_access "
        f"WHERE sh_access.file_id={alias}.id AND sh_access.user_id=?)"
    )
    if role == "admin":
        # Admin sees normal campus/public files, own uploads, and private files
        # only when a user has reported them for moderation review.
        role_visibility = (
            f"({alias}.visibility IN ('public','campus') OR "
            f"EXISTS (SELECT 1 FROM file_reports fr WHERE fr.file_id={alias}.id "
            f"AND fr.status='pending'))"
        )
    elif role == "faculty":
        role_visibility = (
            f"({alias}.visibility='public' OR "
            f"({alias}.visibility='campus' AND EXISTS ("
            f"SELECT 1 FROM users owner WHERE owner.id={alias}.uploader_id "
            f"AND owner.role IN ('student','admin'))))"
        )
    else:  # student
        role_visibility = (
            f"({alias}.visibility='public' OR "
            f"({alias}.visibility='campus' AND EXISTS ("
            f"SELECT 1 FROM users owner WHERE owner.id={alias}.uploader_id "
            f"AND owner.role IN ('faculty','admin'))))"
        )
    return f"(({shared_or_owned}) OR {role_visibility})", [user_id, user_id]

def human_size(size):
    size = float(size or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return "0 B"

@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "human_size": human_size, "csrf_token": csrf_token}

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            csrf_token()
            log_activity("login", "user", user["id"], "User signed in", actor_id=user["id"])
            flash("Welcome back! You are signed in.", "success")
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        role = request.form.get("role", "student")
        department = request.form.get("department", "General").strip() or "General"
        if not name or not email or not password:
            flash("Please complete all required fields.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        elif len(password) < 8:
            flash("Use a password with at least 8 characters.", "error")
        elif role not in ("student", "faculty"):
            flash("Choose a valid account type.", "error")
        else:
            conn = db()
            try:
                conn.execute(
                    "INSERT INTO users(name,email,password,role,department) VALUES(?,?,?,?,?)",
                    (name, email, generate_password_hash(password), role, department)
                )
                conn.commit()
                new_user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                conn.close()
                log_activity("register", "user", new_user["id"] if new_user else None, "New account registered", actor_id=new_user["id"] if new_user else None)
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email address is already registered.", "error")
            finally:
                conn.close()
    return render_template("register.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    log_activity("logout", "user", session.get("user_id"), "User signed out")
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = db()
    role = session["role"]
    uid = session["user_id"]
    if role == "admin":
        total_users = conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        students = conn.execute("SELECT COUNT(*) n FROM users WHERE role='student'").fetchone()["n"]
        faculty = conn.execute("SELECT COUNT(*) n FROM users WHERE role='faculty'").fetchone()["n"]
        total_files = conn.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
        used = conn.execute("SELECT COALESCE(SUM(size),0) n FROM files").fetchone()["n"]
        recent_users = conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT 6").fetchall()
        admin_access, admin_args = file_access_filter(role, uid)
        recent_files = conn.execute(f"SELECT f.*,u.name uploader FROM files f JOIN users u ON u.id=f.uploader_id WHERE {admin_access} ORDER BY f.id DESC LIMIT 6", admin_args).fetchall()
        data = dict(total_users=total_users, students=students, faculty=faculty, total_files=total_files,
                    used=used, recent_users=recent_users, recent_files=recent_files)
    else:
        access_sql, access_args = file_access_filter(role, uid)
        total_files = conn.execute(f"SELECT COUNT(*) n FROM files f WHERE {access_sql}", access_args).fetchone()["n"]
        used = conn.execute("SELECT COALESCE(SUM(size),0) n FROM files WHERE uploader_id=?", (uid,)).fetchone()["n"]
        recent_files = conn.execute(f"""SELECT DISTINCT f.*,u.name uploader,s.name subject FROM files f
            JOIN users u ON u.id=f.uploader_id LEFT JOIN subjects s ON s.id=f.subject_id
            WHERE {access_sql} ORDER BY f.id DESC LIMIT 6""", access_args).fetchall()
        if role == "faculty":
            students = conn.execute("SELECT COUNT(*) n FROM users WHERE role='student'").fetchone()["n"]
            subjects = conn.execute("SELECT COUNT(*) n FROM subjects").fetchone()["n"]
            data = dict(total_files=total_files, students=students, subjects=subjects, used=used, recent_files=recent_files)
        else:
            shared = conn.execute("SELECT COUNT(*) n FROM shares WHERE user_id=?", (uid,)).fetchone()["n"]
            downloads = conn.execute("SELECT COALESCE(SUM(downloads),0) n FROM files").fetchone()["n"]
            data = dict(total_files=total_files, shared=shared, downloads=downloads, used=used, recent_files=recent_files)
    conn.close()
    return render_template("dashboard.html", data=data)

@app.route("/files")
@login_required
def files_page():
    q = request.args.get("q", "").strip()
    conn = db()
    access_sql, args = file_access_filter(session["role"], session["user_id"])
    sql = f"""SELECT DISTINCT f.*,u.name uploader,s.name subject FROM files f
             JOIN users u ON u.id=f.uploader_id LEFT JOIN subjects s ON s.id=f.subject_id
             WHERE {access_sql}"""
    if q:
        sql += " AND (f.original_name LIKE ? OR f.description LIKE ? OR s.name LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY f.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return render_template("files.html", files=rows, q=q)

@app.route("/shared-with-me")
@login_required
def shared_with_me():
    """Show only files explicitly shared with the signed-in user."""
    q = request.args.get("q", "").strip()
    conn = db()
    sql = """SELECT f.*, u.name AS uploader, s.name AS subject
             FROM shares sh
             JOIN files f ON f.id = sh.file_id
             JOIN users u ON u.id = f.uploader_id
             LEFT JOIN subjects s ON s.id = f.subject_id
             WHERE sh.user_id = ?"""
    args = [session["user_id"]]
    if q:
        sql += " AND (f.original_name LIKE ? OR f.description LIKE ? OR s.name LIKE ?)"
        args.extend([f"%{q}%"] * 3)
    sql += " ORDER BY sh.created_at DESC, f.id DESC"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return render_template("shared_with_me.html", files=rows, q=q)


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        description = request.form.get("description", "").strip()
        visibility = request.form.get("visibility", "campus")
        subject_id = request.form.get("subject_id") or None
        if not file or not file.filename:
            flash("Choose a file to upload.", "error")
            return redirect(url_for("upload"))
        safe_name = secure_filename(file.filename)
        if "." not in safe_name or safe_name.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS:
            flash("This file type is not allowed.", "error")
            return redirect(url_for("upload"))
        if visibility not in ("public", "campus", "private"):
            visibility = "campus"
        stored = f"{uuid.uuid4().hex}_{safe_name}"
        path = os.path.join(app.config["UPLOAD_FOLDER"], stored)
        file.save(path)
        size = os.path.getsize(path)
        conn = db()
        conn.execute("""INSERT INTO files(original_name,stored_name,description,subject_id,uploader_id,visibility,size)
                        VALUES(?,?,?,?,?,?,?)""",
                     (safe_name, stored, description, subject_id, session["user_id"], visibility, size))
        conn.commit()
        file_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.close()
        log_activity("upload", "file", file_id, f"Uploaded {safe_name} ({visibility})")
        flash("File uploaded successfully.", "success")
        return redirect(url_for("files_page"))
    conn = db()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    conn.close()
    return render_template("upload.html", subjects=subjects)

@app.route("/download/<int:file_id>")
@login_required
def download(file_id):
    conn = db()
    uid = session["user_id"]
    access_sql, access_args = file_access_filter(session["role"], uid)
    row = conn.execute(f"SELECT f.* FROM files f WHERE f.id=? AND {access_sql}",
                       [file_id] + access_args).fetchone()
    if row:
        conn.execute("UPDATE files SET downloads=downloads+1 WHERE id=?", (file_id,))
        conn.commit()
    conn.close()
    if row:
        log_activity("download", "file", file_id, f"Downloaded {row['original_name']}")
    if not row:
        abort(404)
    return send_from_directory(app.config["UPLOAD_FOLDER"], row["stored_name"], as_attachment=True, download_name=row["original_name"])

@app.route("/share/<int:file_id>", methods=["POST"])
@login_required
def share_file(file_id):
    email = request.form.get("email", "").strip().lower()
    conn = db()
    file_row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    target = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if not file_row or (file_row["uploader_id"] != session["user_id"] and session["role"] != "admin"):
        conn.close()
        abort(403)
    if not target:
        flash("No account found with that email.", "error")
    else:
        try:
            conn.execute("INSERT INTO shares(file_id,user_id) VALUES(?,?)", (file_id,target["id"]))
            conn.commit()
            log_activity("share", "file", file_id, f"Shared with {email}")
            flash("File shared with " + email + ".", "success")
        except sqlite3.IntegrityError:
            flash("This file is already shared with that user.", "info")
    conn.close()
    return redirect(url_for("files_page"))

@app.route("/report/<int:file_id>", methods=["POST"])
@login_required
def report_file(file_id):
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Please provide a reason for reporting this file.", "error")
        return redirect(url_for("files_page"))
    conn = db()
    access_sql, access_args = file_access_filter(session["role"], session["user_id"])
    visible = conn.execute(f"SELECT f.id FROM files f WHERE f.id=? AND {access_sql}", [file_id] + access_args).fetchone()
    if not visible:
        conn.close()
        abort(404)
    conn.execute("INSERT INTO file_reports(file_id,reporter_id,reason) VALUES(?,?,?)",
                 (file_id, session["user_id"], reason[:500]))
    conn.commit()
    conn.close()
    log_activity("report", "file", file_id, "File reported for moderation")
    flash("File reported to the admin team for review.", "success")
    return redirect(url_for("files_page"))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "").strip()
        if name:
            conn.execute("UPDATE users SET name=?, department=? WHERE id=?", (name,department,session["user_id"]))
            conn.commit()
            session["name"] = name
            log_activity("profile_update", "user", session["user_id"], "Profile details updated")
            flash("Profile updated.", "success")
    user = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return render_template("profile.html", user=user)

@app.route("/users")
@roles_required("admin")
def users_page():
    conn = db()
    users = conn.execute("SELECT id,name,email,role,department,created_at FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("users.html", users=users)

@app.route("/users/<int:user_id>/role", methods=["POST"])
@roles_required("admin")
def change_role(user_id):
    role = request.form.get("role")
    if role not in ("student", "faculty", "admin"):
        abort(400)
    if user_id == session["user_id"]:
        flash("You cannot change your own role.", "error")
    else:
        conn = db()
        conn.execute("UPDATE users SET role=? WHERE id=?", (role,user_id))
        conn.commit()
        conn.close()
        log_activity("role_change", "user", user_id, f"Role changed to {role}")
        flash("User role updated.", "success")
    return redirect(url_for("users_page"))

@app.route("/subjects", methods=["GET", "POST"])
@roles_required("faculty", "admin")
def subjects_page():
    conn = db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        if name and code:
            try:
                conn.execute("INSERT INTO subjects(name,code,faculty_id) VALUES(?,?,?)", (name,code,session["user_id"]))
                conn.commit()
                subject_row = conn.execute("SELECT id FROM subjects WHERE code=?", (code,)).fetchone()
                log_activity("subject_create", "subject", subject_row["id"] if subject_row else None, f"Created subject {code}")
                flash("Subject created.", "success")
            except sqlite3.IntegrityError:
                flash("That subject code already exists.", "error")
    subjects = conn.execute("SELECT s.*,u.name faculty FROM subjects s LEFT JOIN users u ON u.id=s.faculty_id ORDER BY s.name").fetchall()
    conn.close()
    return render_template("subjects.html", subjects=subjects)

@app.route("/reports/<int:report_id>/resolve", methods=["POST"])
@roles_required("admin")
def resolve_report(report_id):
    status = request.form.get("status")
    if status not in ("reviewed", "dismissed"):
        abort(400)
    conn = db()
    conn.execute("UPDATE file_reports SET status=? WHERE id=?", (status, report_id))
    conn.commit()
    conn.close()
    log_activity("report_resolve", "report", report_id, f"Report marked {status}")
    flash("Report marked as " + status + ".", "success")
    return redirect(url_for("reports"))

@app.route("/reports")
@roles_required("admin")
def reports():
    conn = db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
        "files": conn.execute("SELECT COUNT(*) n FROM files").fetchone()["n"],
        "downloads": conn.execute("SELECT COALESCE(SUM(downloads),0) n FROM files").fetchone()["n"],
        "storage": conn.execute("SELECT COALESCE(SUM(size),0) n FROM files").fetchone()["n"],
    }
    reports = conn.execute("""SELECT fr.*, f.original_name, f.visibility, u.name reporter
        FROM file_reports fr JOIN files f ON f.id=fr.file_id
        JOIN users u ON u.id=fr.reporter_id
        WHERE fr.status='pending' ORDER BY fr.id DESC""").fetchall()
    conn.close()
    return render_template("reports.html", stats=stats, reports=reports)

@app.route("/activity-logs")
@roles_required("admin")
def activity_logs():
    conn = db()
    rows = conn.execute("""SELECT al.*, COALESCE(u.name, 'System / deleted user') AS actor_name,
        COALESCE(u.role, 'system') AS actor_role
        FROM activity_logs al LEFT JOIN users u ON u.id=al.actor_id
        ORDER BY al.id DESC LIMIT 300""").fetchall()
    conn.close()
    return render_template("activity_logs.html", logs=rows)


@app.errorhandler(403)
def forbidden(error):
    return render_template("message.html", title="Access restricted", message="Your account does not have permission to open this page."), 403

@app.errorhandler(400)
def bad_request(error):
    return render_template("message.html", title="Request rejected", message="The request could not be verified. Refresh the page and try again."), 400

@app.errorhandler(404)
def not_found(error):
    return render_template("message.html", title="Not found", message="The requested item is unavailable or you do not have access to it."), 404

# Initialize schema for both `python app.py` and production WSGI servers.
init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
