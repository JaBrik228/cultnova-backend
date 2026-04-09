from __future__ import annotations

from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "static" / "images" / "projects"

OUTPUTS = (
    {
        "source": "projects.png",
        "targets": (
            {"output": "projects-768.webp", "width": 768, "quality": 76},
            {"output": "projects-1170.webp", "width": 1170, "quality": 78},
            {"output": "projects-1600.webp", "width": 1600, "quality": 80},
        ),
    },
    {
        "source": "projects-mobile.png",
        "targets": (
            {"output": "projects-mobile-640.webp", "width": 640, "quality": 76},
            {"output": "projects-mobile-1200.webp", "width": 1200, "quality": 80},
        ),
    },
)


def _resize_to_width(image: Image.Image, width: int) -> Image.Image:
    if image.width <= width:
        return image.copy()

    height = round(image.height * (width / image.width))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _build_asset(source_path: Path, output_path: Path, width: int, quality: int) -> None:
    with Image.open(source_path) as image:
        converted = image.convert("RGBA")
        resized = _resize_to_width(converted, width)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        resized.save(
            output_path,
            format="WEBP",
            quality=quality,
            method=6,
        )


def main() -> None:
    for asset in OUTPUTS:
        source_path = ASSETS_DIR / asset["source"]
        if not source_path.exists():
            raise FileNotFoundError(f"Source asset not found: {source_path}")

        for target in asset["targets"]:
            output_path = ASSETS_DIR / target["output"]
            _build_asset(
                source_path=source_path,
                output_path=output_path,
                width=target["width"],
                quality=target["quality"],
            )
            print(f"Built {output_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
