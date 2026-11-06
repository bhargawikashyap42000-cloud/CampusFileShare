"""Flask integration tests. Run with: python -m unittest discover -s tests -v"""
import os
import tempfile
import unittest

import app as campus_app
from werkzeug.security import generate_password_hash


class CampusFileShareRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.upload_dir = os.path.join(self.temp_dir.name, "uploads")
        os.makedirs(self.upload_dir)
        campus_app.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key",
            DATABASE=self.db_path,
            UPLOAD_FOLDER=self.upload_dir,
        )
        campus_app.init_db()
        self.conn = campus_app.db()
        self.users = {}
        for role in ("student", "faculty", "admin", "student2", "faculty2"):
            actual_role = "student" if role == "student2" else ("faculty" if role == "faculty2" else role)
            cur = self.conn.execute(
                "INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
                (role, role + "@test.edu", generate_password_hash("Password123"), actual_role),
            )
            self.users[role] = cur.lastrowid
        self.files = {}
        # Create one campus, one public and one private file per uploader role.
        for owner_role in ("student", "faculty", "admin"):
            for visibility in ("campus", "public", "private"):
                filename = f"{owner_role}_{visibility}.txt"
                stored = filename
                with open(os.path.join(self.upload_dir, stored), "w", encoding="utf-8") as f:
                    f.write("runtime test file")
                cur = self.conn.execute(
                    "INSERT INTO files(original_name,stored_name,uploader_id,visibility,size) VALUES(?,?,?,?,?)",
                    (filename, stored, self.users[owner_role], visibility, 17),
                )
                self.files[(owner_role, visibility)] = cur.lastrowid
        self.conn.commit()
        self.conn.close()
        self.client = campus_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = "test-csrf-token"

    def tearDown(self):
        self.temp_dir.cleanup()

    def login_as(self, role):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.users[role]
            sess["role"] = "student" if role == "student2" else ("faculty" if role == "faculty2" else role)
            sess["name"] = role

    def can_download(self, role, file_id):
        self.login_as(role)
        response = self.client.get(f"/download/{file_id}")
        return response.status_code == 200

    def test_campus_visibility_matrix(self):
        # Student campus files -> faculty/admin; faculty campus files -> students/admin.
        self.assertFalse(self.can_download("student2", self.files[("student", "campus")]))
        self.assertTrue(self.can_download("faculty2", self.files[("student", "campus")]))
        self.assertTrue(self.can_download("admin", self.files[("student", "campus")]))
        self.assertTrue(self.can_download("student2", self.files[("faculty", "campus")]))
        self.assertFalse(self.can_download("faculty2", self.files[("faculty", "campus")]))
        self.assertTrue(self.can_download("admin", self.files[("faculty", "campus")]))
        self.assertTrue(self.can_download("student2", self.files[("admin", "campus")]))
        self.assertTrue(self.can_download("faculty2", self.files[("admin", "campus")]))

    def test_public_files_are_available_to_signed_in_roles(self):
        for role in ("student", "faculty", "admin", "student2", "faculty2"):
            for owner in ("student", "faculty", "admin"):
                self.assertTrue(self.can_download(role, self.files[(owner, "public")]))

    def test_private_files_are_not_public(self):
        for owner in ("student", "faculty", "admin"):
            file_id = self.files[(owner, "private")]
            for viewer in ("student", "faculty", "admin", "student2", "faculty2"):
                if viewer == owner:
                    self.assertTrue(self.can_download(viewer, file_id))
                else:
                    self.assertFalse(self.can_download(viewer, file_id))

    def test_explicit_share_grants_private_access(self):
        file_id = self.files[("student", "private")]
        conn = campus_app.db()
        conn.execute("INSERT INTO shares(file_id,user_id) VALUES(?,?)", (file_id, self.users["faculty"]))
        conn.commit()
        conn.close()
        self.assertTrue(self.can_download("faculty", file_id))



    def test_file_listing_obeys_same_visibility_rules(self):
        self.login_as("student2")
        response = self.client.get("/files")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("faculty_campus.txt", page)
        self.assertNotIn("student_campus.txt", page)
        self.assertNotIn("student_private.txt", page)

        self.login_as("faculty2")
        response = self.client.get("/files")
        page = response.get_data(as_text=True)
        self.assertIn("student_campus.txt", page)
        self.assertNotIn("faculty_campus.txt", page)

    def test_shared_with_me_shows_only_explicitly_shared_files(self):
        private_file = self.files[("student", "private")]
        campus_file = self.files[("faculty", "campus")]
        conn = campus_app.db()
        conn.execute("INSERT INTO shares(file_id,user_id) VALUES(?,?)", (private_file, self.users["student2"]))
        conn.commit()
        conn.close()

        self.login_as("student2")
        response = self.client.get("/shared-with-me")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("student_private.txt", page)
        self.assertNotIn("faculty_campus.txt", page)
        self.assertIn("Shared With Me", page)

    def test_shared_with_me_does_not_leak_other_users_shares(self):
        private_file = self.files[("student", "private")]
        conn = campus_app.db()
        conn.execute("INSERT INTO shares(file_id,user_id) VALUES(?,?)", (private_file, self.users["faculty"]))
        conn.commit()
        conn.close()

        self.login_as("student2")
        response = self.client.get("/shared-with-me")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("student_private.txt", response.get_data(as_text=True))

    def test_profile_change_is_written_to_activity_log(self):
        self.login_as("student")
        response = self.client.post("/profile", data={
            "name": "Updated Student", "department": "Computing",
            "csrf_token": "test-csrf-token"
        })
        self.assertEqual(response.status_code, 200)
        conn = campus_app.db()
        row = conn.execute("SELECT action FROM activity_logs WHERE actor_id=? ORDER BY id DESC LIMIT 1",
                           (self.users["student"],)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "profile_update")

    def test_csrf_rejects_missing_token(self):
        self.login_as("student")
        response = self.client.post("/profile", data={"name": "Changed", "department": "CS"})
        self.assertEqual(response.status_code, 400)

    def test_csrf_accepts_valid_token(self):
        self.login_as("student")
        response = self.client.post("/profile", data={"name": "Changed", "department": "CS", "csrf_token": "test-csrf-token"})
        self.assertIn(response.status_code, (200, 302))

    def test_admin_activity_log_page_is_restricted_and_loads(self):
        self.login_as("admin")
        response = self.client.get("/activity-logs")
        self.assertEqual(response.status_code, 200)
        self.login_as("student")
        response = self.client.get("/activity-logs")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_review_private_file_only_while_report_pending(self):
        file_id = self.files[("student", "private")]
        self.login_as("student2")
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.users["student"]
            sess["role"] = "student"
        report_response = self.client.post(f"/report/{file_id}", data={"reason": "Please review", "csrf_token": "test-csrf-token"})
        self.assertIn(report_response.status_code, (302, 303))
        self.assertTrue(self.can_download("admin", file_id))
        conn = campus_app.db()
        conn.execute("UPDATE file_reports SET status='reviewed' WHERE file_id=?", (file_id,))
        conn.commit()
        conn.close()
        self.assertFalse(self.can_download("admin", file_id))


if __name__ == "__main__":
    unittest.main()
