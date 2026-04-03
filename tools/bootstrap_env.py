#!/usr/bin/env python3
"""Bootstrap a local development environment for the Cultnova backend."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
import venv


ROOT_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT_DIR / ".venv"
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
ENV_EXAMPLE_FILE = ROOT_DIR / ".env.example"
ENV_FILE = ROOT_DIR / ".env"


def venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(str(part) for part in cmd))
    subprocess.run(cmd, cwd=ROOT_DIR, check=True)


def create_virtualenv(recreate: bool) -> Path:
    if recreate and VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)

    python_exe = venv_python_path(VENV_DIR)
    if not python_exe.exists():
        if VENV_DIR.exists():
            print(f"Existing virtual environment at {VENV_DIR} looks incomplete; recreating it.")
            shutil.rmtree(VENV_DIR)
        print(f"Creating virtual environment at {VENV_DIR}")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    else:
        print(f"Reusing existing virtual environment at {VENV_DIR}")

    python_exe = venv_python_path(VENV_DIR)
    if not python_exe.exists():
        raise RuntimeError(f"Virtual environment python not found: {python_exe}")
    return python_exe


def ensure_env_file() -> None:
    if ENV_FILE.exists() or not ENV_EXAMPLE_FILE.exists():
        return
    shutil.copy2(ENV_EXAMPLE_FILE, ENV_FILE)
    print(f"Created {ENV_FILE.name} from {ENV_EXAMPLE_FILE.name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate .venv before installing dependencies.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not REQUIREMENTS_FILE.exists():
        raise FileNotFoundError(f"Requirements file not found: {REQUIREMENTS_FILE}")

    ensure_env_file()
    python_exe = create_virtualenv(args.recreate)

    run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python_exe), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])

    if os.name == "nt":
        activation = r".\.venv\Scripts\activate"
    else:
        activation = "source .venv/bin/activate"

    print()
    print("Bootstrap finished.")
    print(f"Activate the environment with: {activation}")
    print("Then run: python manage.py migrate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
