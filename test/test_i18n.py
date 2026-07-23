from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QLabel

from raiv_app.bookshelf import BookshelfWindow
from raiv_app.i18n import (
    load_language_preference,
    save_language_preference,
    set_language,
    tr,
)
from raiv_app.library import LibraryPaths, LibraryService, save_library_settings
from raiv_app.viewer import SpreadWindow, viewer_shortcuts_text


JAPANESE_TEXT = re.compile(r"[ぁ-んァ-ン一-龯]")


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def visible_widget_texts(window) -> list[str]:
    texts: list[str] = []
    for label in window.findChildren(QLabel):
        if label.isVisible():
            texts.append(label.text())
    for button in window.findChildren(QAbstractButton):
        if button.isVisible():
            texts.append(button.text())
    for combo in window.findChildren(QComboBox):
        if combo.isVisible():
            texts.extend(combo.itemText(index) for index in range(combo.count()))
    return texts


def test_language_preference_round_trip(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    save_language_preference("ja", settings_path)
    assert load_language_preference(settings_path) == "ja"
    save_language_preference("en", settings_path)
    assert load_language_preference(settings_path) == "en"


def test_basic_translation_switches_languages() -> None:
    set_language("en")
    assert tr("本棚から削除") == "Remove"
    set_language("ja")
    assert tr("本棚から削除") == "本棚から削除"


def test_bookshelf_and_reader_have_no_visible_japanese_in_english_mode(tmp_path: Path) -> None:
    app = application()
    set_language("en")
    paths = LibraryPaths.for_base_dir(tmp_path / "state")
    save_library_settings(paths, library_dir_confirmed=True)
    library = LibraryService.open(paths)
    bookshelf = BookshelfWindow(library)
    bookshelf.show()
    app.processEvents()

    page_dir = tmp_path / "pages"
    page_dir.mkdir()
    pages = []
    for number in range(2):
        page = page_dir / f"{number + 1:02d}.png"
        Image.new("RGB", (600, 900), "white").save(page)
        pages.append(page)
    reader = SpreadWindow(
        pages=pages,
        title="Demo",
        reading_direction="ltr",
        spread_order="ltr",
        cover_single=False,
        auto_prefetch=False,
        settings_path=paths.settings_path,
    )
    reader.show()
    app.processEvents()

    visible_text = visible_widget_texts(bookshelf) + visible_widget_texts(reader)
    reader.apply_settings_mode("manual", persist=False)
    app.processEvents()
    visible_text.extend(visible_widget_texts(reader))
    visible_text.extend(
        [
            viewer_shortcuts_text(reader.reading_direction),
            reader.correction_state_text(),
            reader.prefetch_state_text(),
        ]
    )
    unexpected = [text for text in visible_text if JAPANESE_TEXT.search(text)]

    reader.close()
    bookshelf.close()
    library.close()
    set_language("en")
    assert unexpected == []
