"""Exercise first-device configuration and private/shared repository installs."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "agent-logger" / "scripts" / "logger_setup.py"
spec = importlib.util.spec_from_file_location("logger_setup", SCRIPT)
logger_setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logger_setup)


class LoggerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "project"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.log_root = self.repo / "private-logs"
        self.log_root.mkdir()
        self.routes = self.base / "routes.json"
        route_patch = patch.object(logger_setup, "ROUTES_FILE", self.routes)
        route_patch.start()
        self.addCleanup(route_patch.stop)
        self.environment = patch.dict(os.environ, {
            "CONVERSATION_LOG_ROOT": str(self.base / "ignored"),
            "CONVERSATION_LOG_CONFIG_FILE": str(self.base / "ignored.json"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_new_device_requires_route(self):
        with self.assertRaisesRegex(ValueError, "请询问用户路径"):
            logger_setup.resolve()
        settings = logger_setup.configure(str(self.log_root), excluded_fields=["device", "model"])
        self.assertEqual(settings["excluded_fields"], ["device", "model"])
        data = json.loads(self.routes.read_text(encoding="utf-8"))
        self.assertEqual(data["log_root_by_host"][logger_setup.hostname()], str(self.log_root))
        self.assertEqual(data["excluded_fields_by_host"][logger_setup.hostname()], ["device", "model"])
        with self.assertRaisesRegex(ValueError, "未知记录字段"):
            logger_setup.configure(str(self.log_root), excluded_fields=["secret"])

    def test_local_install_ignores_rules_and_logs(self):
        logger_setup.configure(str(self.log_root), excluded_fields=[])
        first = logger_setup.install(str(self.repo), "local", "local")
        second = logger_setup.install(str(self.repo), "local", "local")
        self.assertEqual(first["repository"], second["repository"])
        self.assertTrue((self.repo / "AGENTS.override.md").is_file())
        self.assertTrue((self.repo / "CLAUDE.local.md").is_file())
        self.assertTrue((self.repo / ".agents/skills/agent-logger/SKILL.md").is_file())
        self.assertTrue((self.repo / ".agents/skills/agent-logger/routes.example.json").is_file())
        self.assertTrue((self.repo / ".agents/skills/agent-logger/routes.json").is_file())
        self.assertEqual(json.loads((self.repo / ".agents/skills/agent-logger/routes.json").read_text(encoding="utf-8"))["log_root_by_host"][logger_setup.hostname()], str(self.log_root))
        target_resolve = subprocess.run(
            [sys.executable, str(self.repo / ".agents/skills/agent-logger/scripts/logger_setup.py"), "resolve"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(target_resolve.stdout)["log_root"], str(self.log_root))
        self.assertEqual(
            (self.repo / "AGENTS.override.md").read_text(encoding="utf-8").count(
                "<!-- agent-logger:begin -->"
            ), 1,
        )
        ignored = subprocess.run(
            ["git", "-C", str(self.repo), "check-ignore", "-v", "AGENTS.override.md", "private-logs/test.md"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("AGENTS.override.md", ignored)
        self.assertIn("private-logs", ignored)

    def test_only_current_device_route_and_invalid_route(self):
        other_root = self.base / "other-logs"
        other_root.mkdir()
        host = logger_setup.hostname()
        self.routes.write_text(json.dumps({
            "log_root_by_host": {host: str(self.log_root)},
        }), encoding="utf-8")
        self.assertEqual(logger_setup.resolve()["log_root"], str(self.log_root))
        self.assertEqual(logger_setup.resolve()["source"], "route")
        self.routes.write_text(json.dumps({
            "log_root_by_host": {host: str(self.base / "missing")},
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "日志目录无效"):
            logger_setup.resolve()
        self.routes.write_text(json.dumps({
            "log_root_by_host": {"another-device": str(other_root)},
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "请询问用户路径"):
            logger_setup.resolve()

    def test_shared_rules_with_private_logs(self):
        logger_setup.configure(str(self.log_root), excluded_fields=[])
        logger_setup.install(str(self.repo), "shared", "local")
        self.assertNotIn("/AGENTS.override.md", (self.repo / ".git/info/exclude").read_text(encoding="utf-8"))
        self.assertIn("/private-logs/", (self.repo / ".git/info/exclude").read_text(encoding="utf-8"))
        ignored = subprocess.run(
            ["git", "-C", str(self.repo), "check-ignore", "-v", ".agents/skills/agent-logger/routes.json"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("routes.json", ignored)

    def test_tracked_log_is_not_claimed_to_be_ignored(self):
        logger_setup.configure(str(self.log_root), excluded_fields=[])
        (self.log_root / "old.md").write_text("private", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "private-logs/old.md"], check=True)
        with self.assertRaisesRegex(ValueError, "已跟踪"):
            logger_setup.install(str(self.repo), "local", "local")
        self.assertFalse((self.repo / "AGENTS.override.md").exists())

    def test_tracked_agents_rule_blocks_local_install(self):
        logger_setup.configure(str(self.log_root), excluded_fields=[])
        (self.repo / "AGENTS.md").write_text(
            "Every turn must run agent-logger.\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(self.repo), "add", "AGENTS.md"], check=True)
        with self.assertRaisesRegex(ValueError, r"AGENTS\.md（含对话日志规则）"):
            logger_setup.install(str(self.repo), "local", "local")
        self.assertFalse((self.repo / "AGENTS.override.md").exists())


if __name__ == "__main__":
    unittest.main()
