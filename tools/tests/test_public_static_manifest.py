import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tools" / "public_static_manifest.json"


def normalize_relative_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    if not value:
        raise ValueError("path is empty")
    if value.startswith("/") or value.startswith("\\"):
        raise ValueError("path must be relative")
    while value.startswith("./"):
        value = value[2:]
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path contains invalid segments")
    return value


def targets_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


class PublicStaticManifestTests(unittest.TestCase):
    def test_manifest_is_valid(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual(manifest["version"], 1)
        self.assertIsInstance(manifest["entries"], list)
        self.assertGreater(len(manifest["entries"]), 0)

        seen_targets: list[str] = []
        for entry in manifest["entries"]:
            kind = entry["kind"]
            self.assertIn(kind, {"file", "directory"})

            source = normalize_relative_path(entry["source"])
            target = normalize_relative_path(entry["target"])

            source_path = (REPO_ROOT / source).resolve()
            self.assertTrue(source_path.exists(), f"missing source path: {source}")

            if kind == "file":
                self.assertTrue(source_path.is_file(), f"expected file source: {source}")
            else:
                self.assertTrue(source_path.is_dir(), f"expected directory source: {source}")

            for seen in seen_targets:
                self.assertFalse(
                    targets_overlap(target, seen),
                    f"manifest targets overlap: {target} vs {seen}",
                )
            seen_targets.append(target)


if __name__ == "__main__":
    unittest.main()
