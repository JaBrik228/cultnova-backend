import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "tools" / "build_public_css.py"
SPEC = importlib.util.spec_from_file_location("build_public_css", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec from {MODULE_PATH}")
BUILD_PUBLIC_CSS_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILD_PUBLIC_CSS_MODULE
SPEC.loader.exec_module(BUILD_PUBLIC_CSS_MODULE)


class BuildPublicCssTests(unittest.TestCase):
    def test_build_public_css_fully_inlines_remote_imports_and_rebases_remote_urls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            css_root = Path(temp_dir) / "css"
            entries_dir = css_root / "entries"
            pages_dir = css_root / "pages"
            output_dir = css_root / "dist"

            entries_dir.mkdir(parents=True)
            pages_dir.mkdir(parents=True)

            (entries_dir / "simple.css").write_text(
                '@import url("/css/general.css");\n'
                '@import url("/css/loader.css");\n'
                '@import url("/css/style.css");\n',
                encoding="utf-8",
            )
            (entries_dir / "projects.css").write_text(
                '@import "./simple.css";\n'
                '@import "../pages/projects.css";\n',
                encoding="utf-8",
            )
            (pages_dir / "projects.css").write_text(
                '.projects { background: url("../images/card.svg"); display: grid; }\n',
                encoding="utf-8",
            )

            remote_sources = {
                "https://cultnova.ru/css/general.css": ".general { color: #111; }\n",
                "https://cultnova.ru/css/loader.css": ".loader { opacity: 1; }\n",
                "https://cultnova.ru/css/style.css": (
                    '@import url("fonts.css");'
                    '@import url("../css/blocks/trust.css");'
                    '.style { background-image: url("../images/bg.webp"); }\n'
                ),
                "https://cultnova.ru/css/fonts.css": (
                    '@font-face { src: url("../fonts/Geologica-Regular.woff2") format("woff2"); }\n'
                ),
                "https://cultnova.ru/css/blocks/trust.css": (
                    '.trust { background-image: url("../../icons/trust.svg"); }\n'
                ),
            }
            remote_calls = Counter()

            def remote_fetcher(url: str) -> str:
                remote_calls[url] += 1
                try:
                    return remote_sources[url]
                except KeyError as exc:
                    raise AssertionError(f"Unexpected remote CSS fetch: {url}") from exc

            built_paths = BUILD_PUBLIC_CSS_MODULE.build_public_css(
                entries_dir=entries_dir,
                output_dir=output_dir,
                public_origin="https://cultnova.ru",
                remote_fetcher=remote_fetcher,
            )

            self.assertEqual([path.name for path in built_paths], ["projects.css", "simple.css"])

            rendered = (output_dir / "projects.css").read_text(encoding="utf-8")
            self.assertTrue(rendered.startswith(BUILD_PUBLIC_CSS_MODULE.GENERATED_HEADER))
            self.assertIn(".general { color: #111; }", rendered)
            self.assertIn(".loader { opacity: 1; }", rendered)
            self.assertIn(".style { background-image: url(\"/images/bg.webp\"); }", rendered)
            self.assertIn("@font-face { src: url(\"/fonts/Geologica-Regular.woff2\") format(\"woff2\"); }", rendered)
            self.assertIn(".trust { background-image: url(\"/icons/trust.svg\"); }", rendered)
            self.assertIn('.projects { background: url("../images/card.svg"); display: grid; }', rendered)
            self.assertNotIn("@import", rendered)

            simple_rendered = (output_dir / "simple.css").read_text(encoding="utf-8")
            self.assertNotIn("@import", simple_rendered)

            self.assertEqual(
                remote_calls,
                Counter(
                    {
                        "https://cultnova.ru/css/general.css": 1,
                        "https://cultnova.ru/css/loader.css": 1,
                        "https://cultnova.ru/css/style.css": 1,
                        "https://cultnova.ru/css/fonts.css": 1,
                        "https://cultnova.ru/css/blocks/trust.css": 1,
                    }
                ),
            )

    def test_build_public_css_detects_remote_import_cycles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            css_root = Path(temp_dir) / "css"
            entries_dir = css_root / "entries"

            entries_dir.mkdir(parents=True)

            (entries_dir / "simple.css").write_text(
                '@import url("/css/general.css");\n',
                encoding="utf-8",
            )

            remote_sources = {
                "https://cultnova.ru/css/general.css": '@import url("style.css");\n',
                "https://cultnova.ru/css/style.css": '@import url("general.css");\n',
            }

            def remote_fetcher(url: str) -> str:
                return remote_sources[url]

            with self.assertRaisesRegex(ValueError, "CSS import cycle detected"):
                BUILD_PUBLIC_CSS_MODULE.build_public_css(
                    entries_dir=entries_dir,
                    output_dir=css_root / "dist",
                    public_origin="https://cultnova.ru",
                    remote_fetcher=remote_fetcher,
                )

    def test_build_public_css_is_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            css_root = Path(temp_dir) / "css"
            entries_dir = css_root / "entries"
            output_dir = css_root / "dist"

            entries_dir.mkdir(parents=True)

            (entries_dir / "b.css").write_text(".b { order: 2; }\n", encoding="utf-8")
            (entries_dir / "a.css").write_text(".a { order: 1; }\n", encoding="utf-8")

            first_paths = BUILD_PUBLIC_CSS_MODULE.build_public_css(
                entries_dir=entries_dir,
                output_dir=output_dir,
            )
            first_rendered = {
                path.name: path.read_text(encoding="utf-8")
                for path in first_paths
            }

            second_paths = BUILD_PUBLIC_CSS_MODULE.build_public_css(
                entries_dir=entries_dir,
                output_dir=output_dir,
            )
            second_rendered = {
                path.name: path.read_text(encoding="utf-8")
                for path in second_paths
            }

            self.assertEqual([path.name for path in first_paths], ["a.css", "b.css"])
            self.assertEqual([path.name for path in second_paths], ["a.css", "b.css"])
            self.assertEqual(first_rendered, second_rendered)


if __name__ == "__main__":
    unittest.main()
