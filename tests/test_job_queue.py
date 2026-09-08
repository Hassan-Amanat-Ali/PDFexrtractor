import importlib
import io
import os
import tempfile
import unittest


class JobQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["MEP_DATA_DIR"] = cls.temp.name
        os.environ["MEP_USER"] = "tester"
        os.environ["MEP_PASSWORD"] = "secret"
        cls.store = importlib.import_module("job_store")
        cls.web = importlib.import_module("web_app")
        cls.web.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        with self.store.connect() as db:
            db.execute("DELETE FROM jobs")
        self.client = self.web.app.test_client()
        self.client.post("/login", data={"username": "tester", "password": "secret"})

    def test_upload_persists_and_is_visible_after_new_request(self):
        response = self.client.post("/upload", data={
            "file": (io.BytesIO(b"%PDF-1.4\n"), "drawing.pdf"), "mode": "fast"
        }, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200)
        job_id = response.get_json()["job_id"]
        self.assertEqual(self.client.get(f"/status/{job_id}").get_json()["status"], "queued")
        self.assertIn(b"drawing.pdf", self.client.get("/").data)

    def test_queue_claim_cancel_save_and_delete(self):
        self.store.create_job("one", "tester", "one.pdf", ".pdf", "advanced")
        claimed = self.store.claim_next_job(999999)
        self.assertEqual(claimed["id"], "one")
        self.client.post("/jobs/one/cancel")
        self.assertEqual(self.store.get_job("one")["status"], "cancelled")
        self.client.post("/jobs/one/save")
        self.assertEqual(self.store.get_job("one")["saved"], 1)
        self.client.post("/jobs/one/delete")
        self.assertIsNone(self.store.get_job("one"))

    def test_external_login_redirect_is_rejected(self):
        client = self.web.app.test_client()
        response = client.post("/login?next=https://example.com", data={
            "username": "tester", "password": "secret"
        })
        self.assertEqual(response.headers["Location"], "/")


if __name__ == "__main__":
    unittest.main()
