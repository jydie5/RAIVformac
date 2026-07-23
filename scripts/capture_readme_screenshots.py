from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from PySide6.QtWidgets import QApplication

from raiv_app.bookshelf import BookshelfWindow
from raiv_app.i18n import set_language
from raiv_app.library import LibraryPaths, LibraryService, save_library_settings
from raiv_app.viewer import SpreadWindow


def process_events(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


def capture(demo_dir: Path, output_dir: Path, language: str = "en") -> None:
    archives = sorted(demo_dir.glob("*.zip"))
    if not archives:
        raise RuntimeError(f"no demo ZIP files found in {demo_dir}")

    set_language(language)
    app = QApplication.instance() or QApplication([])
    output_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="raiv-readme-") as temporary_directory:
        paths = LibraryPaths.for_base_dir(Path(temporary_directory))
        save_library_settings(paths, library_dir_confirmed=True)
        library = LibraryService.open(paths)
        try:
            for archive in archives:
                for book in library.register_local_books(archive):
                    library.importer.import_book(book)

            bookshelf = BookshelfWindow(library)
            bookshelf.resize(1400, 900)
            bookshelf.library_location_label.setText(
                "デモ本棚: Pepper&Carrot (CC BY 4.0)    3冊"
                if language == "ja"
                else "Demo library: Pepper&Carrot (CC BY 4.0)    3 books"
            )
            bookshelf.show()
            process_events(app, 0.8)
            if not bookshelf.grab().save(str(output_dir / "bookshelf.png")):
                raise RuntimeError("failed to save bookshelf screenshot")
            bookshelf.hide()

            books = sorted(library.books.list_books(), key=lambda item: item.title)
            selected = books[-1]
            pages = sorted(Path(selected.local_path).glob("*"))
            reader = SpreadWindow(
                pages=pages,
                title=selected.title,
                reading_direction="ltr",
                spread_order="ltr",
                cover_single=False,
                auto_prefetch=False,
                settings_path=paths.settings_path,
            )
            reader.index = min(1, max(0, len(pages) - 2))
            reader.resize(1600, 1000)
            reader.show()
            reader.render_spread()
            process_events(app, 1.5)
            if not reader.grab().save(str(output_dir / "reader.png")):
                raise RuntimeError("failed to save reader screenshot")
            reader.close()
            process_events(app, 0.2)
        finally:
            library.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture README screenshots with free demo books.")
    parser.add_argument("--demo-dir", type=Path, default=REPOSITORY_ROOT / "demo")
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY_ROOT / "docs" / "images")
    parser.add_argument("--language", choices=("en", "ja"), default="en")
    args = parser.parse_args()
    capture(args.demo_dir.resolve(), args.output_dir.resolve(), args.language)


if __name__ == "__main__":
    main()
