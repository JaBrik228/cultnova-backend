import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "ssh_run.py"
SPEC = importlib.util.spec_from_file_location("ssh_run_under_test", MODULE_PATH)
ssh_run = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(ssh_run)


class SshRunTests(unittest.TestCase):
    def test_read_key_value_config_strips_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / ".env.deploy"
            config_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "SSH_HOST=example.com",
                        'SSH_USER="demo"',
                        "SSH_PASS='secret'",
                        "EMPTY_LINE_OK=",
                    ]
                ),
                encoding="utf-8",
            )

            config = ssh_run.read_key_value_config(config_path)

        self.assertEqual(config["SSH_HOST"], "example.com")
        self.assertEqual(config["SSH_USER"], "demo")
        self.assertEqual(config["SSH_PASS"], "secret")
        self.assertEqual(config["EMPTY_LINE_OK"], "")

    def test_resolve_default_config_path_uses_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            config_path = repo_root / ".env.deploy"
            config_path.write_text("SSH_HOST=example.com\n", encoding="utf-8")

            with patch.object(ssh_run, "resolve_repo_root", return_value=repo_root):
                resolved = ssh_run.resolve_default_config_path()

        self.assertEqual(resolved, config_path)

    def test_load_ssh_settings_reads_default_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / ".env.deploy"
            config_path.write_text(
                "\n".join(
                    [
                        "SSH_HOST=host.example",
                        "SSH_USER=user1",
                        "SSH_PASS=pass1",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.object(ssh_run, "resolve_default_config_path", return_value=config_path):
                with patch.dict(os.environ, {}, clear=True):
                    settings = ssh_run.load_ssh_settings()

        self.assertEqual(
            settings,
            {
                "SSH_HOST": "host.example",
                "SSH_USER": "user1",
                "SSH_PASS": "pass1",
            },
        )

    def test_load_ssh_settings_env_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / ".env.deploy"
            config_path.write_text(
                "\n".join(
                    [
                        "SSH_HOST=config-host",
                        "SSH_USER=config-user",
                        "SSH_PASS=config-pass",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"SSH_USER": "env-user", "SSH_PASS": "env-pass"},
                clear=True,
            ):
                settings = ssh_run.load_ssh_settings(str(config_path))

        self.assertEqual(settings["SSH_HOST"], "config-host")
        self.assertEqual(settings["SSH_USER"], "env-user")
        self.assertEqual(settings["SSH_PASS"], "env-pass")

    def test_load_ssh_settings_reports_checked_sources_on_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / ".env.deploy"
            config_path.write_text(
                "\n".join(
                    [
                        "SSH_HOST=config-host",
                        "SSH_USER=config-user",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as error:
                    ssh_run.load_ssh_settings(str(config_path))

        message = str(error.exception)
        self.assertIn("Missing SSH settings.", message)
        self.assertIn(str(config_path.resolve()), message)
        self.assertIn("SSH_HOST, SSH_USER, SSH_PASS", message)

    def test_main_uses_explicit_config_and_preserves_remote_command(self):
        with patch.object(
            ssh_run,
            "load_ssh_settings",
            return_value={
                "SSH_HOST": "host.example",
                "SSH_USER": "demo",
                "SSH_PASS": "secret",
            },
        ) as load_settings:
            with patch.object(ssh_run, "run_remote_command", return_value=0) as run_command:
                exit_code = ssh_run.main(["--config", ".env.deploy", "echo", "connected", "&&", "whoami"])

        self.assertEqual(exit_code, 0)
        load_settings.assert_called_once_with(".env.deploy")
        run_command.assert_called_once_with(
            {
                "SSH_HOST": "host.example",
                "SSH_USER": "demo",
                "SSH_PASS": "secret",
            },
            "echo connected && whoami",
        )


if __name__ == "__main__":
    unittest.main()
