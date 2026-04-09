import argparse
import os
import sys
import time
from pathlib import Path

import paramiko


REQUIRED_SSH_KEYS = ("SSH_HOST", "SSH_USER", "SSH_PASS")
SSH_CONNECT_TIMEOUT_SECONDS = 45
SSH_CONNECT_ATTEMPTS = 4


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_default_config_path() -> Path | None:
    default_path = resolve_repo_root() / ".env.deploy"
    if default_path.exists():
        return default_path
    return None


def read_key_value_config(path: str | Path) -> dict[str, str]:
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    config: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        eq_index = line.find("=")
        if eq_index < 1:
            continue

        key = line[:eq_index].strip()
        value = line[eq_index + 1 :].strip()

        if (
            len(value) >= 2
            and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")))
        ):
            value = value[1:-1]

        config[key] = value

    return config


def load_ssh_settings(config_path: str | None = None) -> dict[str, str]:
    resolved_config_path: Path | None = None
    config: dict[str, str] = {}

    if config_path:
        resolved_config_path = Path(config_path).expanduser()
        if not resolved_config_path.is_absolute():
            resolved_config_path = (Path.cwd() / resolved_config_path).resolve()
        try:
            config = read_key_value_config(resolved_config_path)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc))
    else:
        resolved_config_path = resolve_default_config_path()
        if resolved_config_path:
            config = read_key_value_config(resolved_config_path)

    merged = dict(config)
    for key in REQUIRED_SSH_KEYS:
        env_value = os.environ.get(key)
        if env_value:
            merged[key] = env_value

    missing = [key for key in REQUIRED_SSH_KEYS if not merged.get(key)]
    if missing:
        checked_config = str(resolved_config_path) if resolved_config_path else "none"
        required = ", ".join(REQUIRED_SSH_KEYS)
        raise SystemExit(
            "Missing SSH settings. Checked config: "
            f"{checked_config} and environment variables. Required keys: {required}."
        )

    return {key: merged[key] for key in REQUIRED_SSH_KEYS}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--config", dest="config_path")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if not args.command:
        raise SystemExit("Usage: python tools/ssh_run.py [--config PATH] <remote command...>")

    return args


def run_remote_command(settings: dict[str, str], command: str) -> int:
    client: paramiko.SSHClient | None = None
    last_error: Exception | None = None

    for attempt in range(1, SSH_CONNECT_ATTEMPTS + 1):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=settings["SSH_HOST"],
                username=settings["SSH_USER"],
                password=settings["SSH_PASS"],
                timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            )
            break
        except Exception as exc:
            last_error = exc
            client.close()
            client = None
            if attempt == SSH_CONNECT_ATTEMPTS:
                raise
            time.sleep(attempt)

    if client is None:
        raise RuntimeError(f"SSH connection failed: {last_error}")

    try:
        stdin, stdout, stderr = client.exec_command(command, get_pty=False)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if out:
            sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        return rc
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    command = " ".join(args.command).strip()
    if not command:
        raise SystemExit("Usage: python tools/ssh_run.py [--config PATH] <remote command...>")

    settings = load_ssh_settings(args.config_path)
    return run_remote_command(settings, command)


if __name__ == "__main__":
    raise SystemExit(main())
