import os
import sys
import paramiko


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def main() -> int:
    host = _get_env("SSH_HOST")
    user = _get_env("SSH_USER")
    password = _get_env("SSH_PASS")
    cmd = " ".join(sys.argv[1:]).strip()
    if not cmd:
        raise SystemExit("Usage: python tools/ssh_run.py <remote command...>")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, password=password, timeout=20)
    try:
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=False)
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


if __name__ == "__main__":
    raise SystemExit(main())

