from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.injectivelens.server import InjectiveLensRequestHandler


ROOT = Path(__file__).resolve().parents[1]


class InjectiveAzureDeploymentTest(unittest.TestCase):
    def test_azure_deployment_artifacts_replace_vercel_railway_path(self) -> None:
        dockerfile = ROOT / "Dockerfile"
        deploy_script = ROOT / "scripts" / "azure_deploy_containerapp.sh"
        start_script = ROOT / "scripts" / "azure_start.sh"
        azure_doc = ROOT / "docs" / "azure_deployment.md"

        self.assertTrue(dockerfile.exists())
        self.assertTrue(deploy_script.exists())
        self.assertTrue(start_script.exists())
        self.assertTrue(os.access(deploy_script, os.X_OK))
        self.assertTrue(os.access(start_script, os.X_OK))
        self.assertFalse((ROOT / "frontend" / "app" / "vercel.json").exists())
        self.assertFalse((ROOT / "scripts" / "railway_start.sh").exists())

        docker_text = dockerfile.read_text()
        deploy_text = deploy_script.read_text()
        doc_text = azure_doc.read_text()
        self.assertIn("INJECTIVELENS_STATIC_DIR", docker_text)
        self.assertIn("python -m backend.injectivelens.server", docker_text)
        self.assertIn("az containerapp", deploy_text)
        self.assertIn("Azure Container Apps", doc_text)

    def test_no_live_vercel_or_railway_url_remains_in_deployable_surface(self) -> None:
        paths = [
            ROOT / "README.md",
            ROOT / ".env.example",
            ROOT / "Dockerfile",
            ROOT / "docs" / "azure_deployment.md",
            ROOT / "frontend" / "app" / "public" / "demo-video" / "index.html",
        ]
        rendered = "\n".join(path.read_text() for path in paths)
        self.assertNotIn("up.railway.app", rendered)
        self.assertNotIn("vercel.app", rendered)

    def test_server_serves_frontend_static_bundle_when_configured(self) -> None:
        original_static_dir = os.environ.get("INJECTIVELENS_STATIC_DIR")
        with tempfile.TemporaryDirectory() as tmpdir:
            static_dir = Path(tmpdir)
            (static_dir / "index.html").write_text("<html><body>InjectiveLens Azure Shell</body></html>")
            (static_dir / "assets").mkdir()
            (static_dir / "assets" / "app.js").write_text("console.log('azure');")
            os.environ["INJECTIVELENS_STATIC_DIR"] = str(static_dir)

            with _ServerHarness() as harness:
                root = harness.get_text("/")
                spa = harness.get_text("/audit")
                asset = harness.get_text("/assets/app.js")
                health = harness.get_json("/api/health")
                missing_status, missing_payload = harness.get_status("/assets/missing.js")

        if original_static_dir is None:
            os.environ.pop("INJECTIVELENS_STATIC_DIR", None)
        else:
            os.environ["INJECTIVELENS_STATIC_DIR"] = original_static_dir

        self.assertIn("InjectiveLens Azure Shell", root)
        self.assertIn("InjectiveLens Azure Shell", spa)
        self.assertIn("console.log('azure')", asset)
        self.assertEqual(health["service"], "injectivelens-agent-guard")
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_payload["error"], "not_found")


class _ServerHarness:
    def __enter__(self) -> "_ServerHarness":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), InjectiveLensRequestHandler)
        self.server.quiet = True  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def get_text(self, path: str) -> str:
        with self.opener.open(self.base_url + path, timeout=3) as response:
            return response.read().decode("utf-8")

    def get_json(self, path: str) -> dict[str, object]:
        return json.loads(self.get_text(path))

    def get_status(self, path: str) -> tuple[int, dict[str, object]]:
        try:
            with self.opener.open(self.base_url + path, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            finally:
                exc.close()


if __name__ == "__main__":
    unittest.main()
