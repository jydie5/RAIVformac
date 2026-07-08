from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

from raiv_app.archive_utils import natural_sort_key
from raiv_app.library import (
    Book,
    LibraryPaths,
    LibraryService,
    ReadingState,
    is_library_dir_confirmed,
    save_library_settings,
    utc_now_iso,
)
from raiv_app.page_provider import open_pages_for_viewer
from raiv_app.viewer import (
    PYSIDE_IMPORT_ERROR,
    SpreadWindow,
    collect_processed_pages,
    default_spread_order,
)

if PYSIDE_IMPORT_ERROR is None:
    from PySide6.QtCore import QEvent, QTimer, QObject, QSize, Qt, Signal
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import (
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )
else:
    QEvent = QTimer = QObject = QSize = Qt = Signal = QIcon = QFileDialog = QHBoxLayout = QLabel = QListWidget = QListWidgetItem = QMessageBox = QPushButton = QStackedWidget = QVBoxLayout = QWidget = None
    QMainWindow = object


class BookshelfSignals(QObject):
    register_progress = Signal(object, object)
    register_done = Signal(object, object)


READING_STATUS_LABELS = {
    "unread": "未読",
    "reading": "読書中",
    "completed": "完了",
}


def volume_badge(title: str) -> str:
    match = re.search(r"第\s*([0-9０-９]+)\s*巻", title)
    if match:
        return f"第{match.group(1)}巻"
    match = re.search(r"\bv(?:ol(?:ume)?\.?)?\s*(\d+[a-zA-Z]?)\b", title, flags=re.IGNORECASE)
    if match:
        return f"v{match.group(1)}"
    return ""


def compact_book_title(title: str, badge: str) -> str:
    compact = title
    if badge:
        compact = compact.replace(badge, "")
        compact = re.sub(r"\bv(?:ol(?:ume)?\.?)?\s*" + re.escape(badge[1:]) + r"\b", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"[_\s]+", " ", compact).strip(" -_")
    if len(compact) > 19:
        compact = compact[:18] + "…"
    return compact or title[:19]


def bookshelf_label(book: Book, state: ReadingState | None) -> str:
    pages = "未解析" if book.page_count is None else f"{book.page_count}ページ"
    status = READING_STATUS_LABELS.get(book.reading_status, book.reading_status)
    parts = [book.title, pages, status]
    if state is not None:
        parts.append(f"p.{state.page_index + 1}")
    return "    ".join(parts)


def bookshelf_grid_label(book: Book, state: ReadingState | None) -> str:
    badge = volume_badge(book.title)
    title = compact_book_title(book.title, badge)
    page_text = "未解析" if book.page_count is None else f"{book.page_count}"
    lines = [badge or title]
    if badge:
        lines.append(title)
    if state is not None:
        lines.append(f"p.{state.page_index + 1} / {page_text}")
    else:
        lines.append(READING_STATUS_LABELS.get(book.reading_status, book.reading_status))
    return "\n".join(lines)


def books_in_folder_display_order(books: list[Book]) -> list[Book]:
    return sorted(
        books,
        key=lambda book: (natural_sort_key(book.title), natural_sort_key(str(Path(book.local_path).parent)), book.id),
    )


def next_book_after_reading(current_book_id: str, books: list[Book]) -> Book | None:
    ordered_books = books_in_folder_display_order(books)
    for index, book in enumerate(ordered_books):
        if book.id == current_book_id:
            if index + 1 >= len(ordered_books):
                return None
            return ordered_books[index + 1]
    return None


def reading_state_from_window(book_id: str, window: SpreadWindow) -> ReadingState:
    return ReadingState(
        book_id=book_id,
        page_index=window.index,
        spread_mode="spread",
        reading_direction=window.reading_direction,
        cover_single=window.cover_single,
        fit_mode="page",
        correction_preset="標準",
    )


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def library_location_label(paths: LibraryPaths) -> str:
    return f"保存先: {paths.library_dir}    使用量: {format_bytes(directory_size(paths.library_dir))}"


def preferred_reader_size(screen_geometry) -> QSize:
    if screen_geometry is None:
        return QSize(1400, 900)
    width = screen_geometry.width()
    height = screen_geometry.height()
    target_width = min(1600, max(1200, int(width * 0.88)))
    target_height = min(1000, max(820, int(height * 0.88)))
    return QSize(min(target_width, width), min(target_height, height))


def bookshelf_shortcuts_text() -> str:
    return "\n".join(
        [
            "ファイル/フォルダをドロップ: 本棚へ登録",
            "ダブルクリック: 読む",
            "読む: 選択中の本を開く",
            "Delete: 選択中の本を本棚から削除。元ZIP/RARは残す",
            "本棚から削除: 確認後、RAIV管理フォルダを削除。元ZIP/RARは残す",
            "保存先を開く: FinderでRAIV Libraryを表示",
            "?: このヘルプを表示",
        ]
    )


def dropped_local_paths(mime_data) -> list[Path]:
    if mime_data is None or not mime_data.hasUrls():
        return []
    paths: list[Path] = []
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        local_path = url.toLocalFile()
        if local_path:
            paths.append(Path(local_path))
    return paths


class BookshelfWindow(QMainWindow):
    def __init__(self, library: LibraryService | None = None) -> None:
        super().__init__()
        self.library = library or LibraryService.open()
        self.active_reader: SpreadWindow | None = None
        self.suppress_reader_return = False
        self.register_queue: list[Path] = []
        self.register_total = 0
        self.register_done_count = 0
        self.register_running = False
        self.signals = BookshelfSignals()
        self.signals.register_progress.connect(self.on_register_progress)
        self.signals.register_done.connect(self.on_register_done)
        self.setWindowTitle("RAIV Bookshelf")
        self.setMinimumSize(900, 620)
        self.resize(1180, 760)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QMainWindow, QWidget { background: #151515; color: #eeeeee; font-size: 16px; } "
            "QListWidget { background: #101010; border: 1px solid #333333; font-size: 13px; } "
            "QListWidget::item { padding: 8px; } "
            "QListWidget::item:selected { background: #26384f; color: #ffffff; border: 1px solid #6c93c2; } "
            "QPushButton { min-height: 34px; font-size: 16px; padding: 6px 12px; } "
            "QLabel#subtitle { color: #bbbbbb; font-size: 14px; }"
        )

        self.stack = QStackedWidget(self)
        root = QWidget(self.stack)
        self.bookshelf_page = root
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header = QLabel("RAIV Bookshelf", root)
        header.setStyleSheet("font-size: 24px; font-weight: bold;")
        header_row.addWidget(header, 1)
        help_button = QPushButton("?", root)
        help_button.setFixedWidth(36)
        help_button.setToolTip("ショートカットを表示")
        help_button.clicked.connect(self.show_shortcuts_help)
        header_row.addWidget(help_button)
        layout.addLayout(header_row)

        subtitle = QLabel("ローカルの画像フォルダ、単画像、zip/cbz/rar/cbr/7z/cb7 を本棚へ登録します。", root)
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        self.library_location_label = QLabel("", root)
        self.library_location_label.setObjectName("subtitle")
        self.library_location_label.setWordWrap(True)
        layout.addWidget(self.library_location_label)

        self.list_widget = QListWidget(root)
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setWordWrap(True)
        self.list_widget.setIconSize(QSize(132, 192))
        self.list_widget.setGridSize(QSize(190, 292))
        self.list_widget.setSpacing(16)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.viewport().setAcceptDrops(True)
        self.list_widget.installEventFilter(self)
        self.list_widget.viewport().installEventFilter(self)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.open_selected_book())
        layout.addWidget(self.list_widget, 1)

        buttons = QHBoxLayout()
        self.add_file_button = QPushButton("ファイルを追加", root)
        self.add_file_button.clicked.connect(self.add_file)
        buttons.addWidget(self.add_file_button)

        self.add_folder_button = QPushButton("フォルダを追加", root)
        self.add_folder_button.clicked.connect(self.add_folder)
        buttons.addWidget(self.add_folder_button)

        self.open_button = QPushButton("読む", root)
        self.open_button.clicked.connect(self.open_selected_book)
        buttons.addWidget(self.open_button)

        self.delete_button = QPushButton("本棚から削除", root)
        self.delete_button.clicked.connect(self.delete_selected_book)
        buttons.addWidget(self.delete_button)

        self.open_library_button = QPushButton("保存先を開く", root)
        self.open_library_button.clicked.connect(self.open_library_folder)
        buttons.addWidget(self.open_library_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.status_label = QLabel("", root)
        self.status_label.setObjectName("subtitle")
        layout.addWidget(self.status_label)

        self.stack.addWidget(self.bookshelf_page)
        self.setCentralWidget(self.stack)
        self.reload_books()
        QTimer.singleShot(0, self.confirm_library_location_if_needed)

    def reload_books(self) -> None:
        self.list_widget.clear()
        books = books_in_folder_display_order(self.library.books.list_books())
        for book in books:
            state = self.library.reading_states.get(book.id)
            item = QListWidgetItem(bookshelf_grid_label(book, state))
            item.setToolTip(bookshelf_label(book, state))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setSizeHint(QSize(190, 292))
            if book.cover_thumbnail_path and Path(book.cover_thumbnail_path).exists():
                item.setIcon(QIcon(book.cover_thumbnail_path))
            item.setData(Qt.UserRole, book.id)
            self.list_widget.addItem(item)
        self.library_location_label.setText(library_location_label(self.library.paths))
        self.status_label.setText(f"{len(books)}冊 / タイトル昇順")

    def confirm_library_location_if_needed(self) -> None:
        if is_library_dir_confirmed(self.library.paths):
            return
        message = QMessageBox(self)
        message.setWindowTitle("本棚保存先")
        message.setIcon(QMessageBox.Information)
        message.setText("RAIVの本棚保存先を確認してください。")
        message.setInformativeText(
            "展開済み漫画は容量が大きくなるため、Finderで見つけやすい場所に保存します。\n\n"
            f"現在の保存先:\n{self.library.paths.library_dir}"
        )
        use_button = message.addButton("この場所を使う", QMessageBox.AcceptRole)
        change_button = message.addButton("変更...", QMessageBox.ActionRole)
        message.addButton("後で", QMessageBox.RejectRole)
        message.exec()
        clicked = message.clickedButton()
        if clicked == use_button:
            save_library_settings(self.library.paths, library_dir_confirmed=True)
            self.reload_books()
        elif clicked == change_button:
            self.choose_library_location()

    def eventFilter(self, watched, event) -> bool:
        if watched in {self.list_widget, self.list_widget.viewport()} and self.handle_drop_event(event):
            return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event) -> None:
        self.accept_drag_event_if_supported(event)

    def dragMoveEvent(self, event) -> None:
        self.accept_drag_event_if_supported(event)

    def dropEvent(self, event) -> None:
        self.accept_drop_event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Question:
            self.show_shortcuts_help()
            return
        if event.key() in {Qt.Key_Delete, Qt.Key_Backspace} and self.stack.currentWidget() is self.bookshelf_page:
            self.delete_selected_book()
            return
        super().keyPressEvent(event)

    def show_shortcuts_help(self) -> None:
        QMessageBox.information(self, "ショートカット", bookshelf_shortcuts_text())

    def handle_drop_event(self, event) -> bool:
        if event.type() in {QEvent.DragEnter, QEvent.DragMove}:
            self.accept_drag_event_if_supported(event)
            return event.isAccepted()
        if event.type() == QEvent.Drop:
            self.accept_drop_event(event)
            return event.isAccepted()
        return False

    def accept_drag_event_if_supported(self, event) -> None:
        if dropped_local_paths(event.mimeData()):
            event.acceptProposedAction()

    def accept_drop_event(self, event) -> None:
        paths = dropped_local_paths(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        if self.confirm_register_paths(paths, "ドロップしたファイル/フォルダ"):
            self.enqueue_register_paths(paths)

    def confirm_register_paths(self, paths: list[Path], source_label: str) -> bool:
        if not paths:
            return False
        archive_suffixes = {".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7"}
        archive_count = sum(1 for path in paths if path.suffix.lower() in archive_suffixes)
        folder_count = sum(1 for path in paths if path.is_dir())
        file_count = len(paths) - folder_count - archive_count
        examples = "\n".join(f"- {path.name}" for path in paths[:5])
        if len(paths) > 5:
            examples += f"\n- ほか {len(paths) - 5} 件"
        detail = (
            f"{source_label}を本棚へ登録します。\n\n"
            f"対象: {len(paths)}件"
            f"（圧縮ファイル {archive_count}件 / フォルダ {folder_count}件 / ファイル {file_count}件）\n\n"
            f"{examples}\n\n"
            "圧縮ファイルは本棚保存先へ展開し、表紙サムネイルを作成します。\n"
            "元のZIP/RAR/7zファイルは削除しません。"
        )
        message = QMessageBox(self)
        message.setWindowTitle("本棚へ登録")
        message.setIcon(QMessageBox.Question)
        message.setText("展開して本棚へ登録しますか？")
        message.setInformativeText(detail)
        message.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        message.setDefaultButton(QMessageBox.Yes)
        if message.exec() != QMessageBox.Yes:
            self.status_label.setText("登録をキャンセルしました。")
            return False
        self.status_label.setText(detail.splitlines()[0])
        return True

    def choose_library_location(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "本棚保存先を選択", str(self.library.paths.library_dir))
        if not path:
            return
        new_library_dir = Path(path).expanduser()
        try:
            self.move_library_storage(new_library_dir)
        except Exception as exc:
            self.status_label.setText(f"保存先を変更できません: {exc}")
            return
        save_library_settings(self.library.paths, library_dir_confirmed=True)
        self.reload_books()
        self.status_label.setText(f"保存先を変更しました: {self.library.paths.library_dir}")

    def move_library_storage(self, new_library_dir: Path) -> None:
        old_paths = self.library.paths
        old_library_dir = old_paths.library_dir.expanduser()
        new_paths = old_paths.with_library_dir(new_library_dir)
        if old_library_dir == new_paths.library_dir:
            self.library.paths.ensure()
            return
        new_paths.library_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(old_library_dir.iterdir(), key=lambda item: item.name) if old_library_dir.exists() else []:
            destination = new_paths.library_dir / source.name
            if destination.exists():
                continue
            source.replace(destination)
        for book in self.library.books.list_books():
            local_path = rewrite_visible_library_path(book.local_path, old_library_dir, new_paths.library_dir)
            cover_path = (
                rewrite_visible_library_path(book.cover_thumbnail_path, old_library_dir, new_paths.library_dir)
                if book.cover_thumbnail_path
                else book.cover_thumbnail_path
            )
            if local_path != book.local_path or cover_path != book.cover_thumbnail_path:
                self.library.books.upsert(book.with_updates(local_path=local_path, cover_thumbnail_path=cover_path))
        try:
            old_library_dir.rmdir()
        except OSError:
            pass
        self.library.paths = new_paths
        self.library.importer.paths = new_paths

    def add_file(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "本棚に追加",
            str(Path.home()),
            "Images and archives (*.zip *.cbz *.rar *.cbr *.7z *.cb7 *.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.avif);;All files (*)",
        )
        self.enqueue_register_paths([Path(path) for path in paths])

    def add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "画像フォルダを本棚に追加", str(Path.home()))
        if path:
            self.enqueue_register_paths([Path(path)])

    def enqueue_register_paths(self, paths: list[Path]) -> None:
        if not paths:
            return
        self.register_queue.extend(paths)
        self.register_total += len(paths)
        self.status_label.setText(f"取り込み待ち {len(self.register_queue)}件")
        self.start_next_register()

    def register_path(self, path: Path) -> None:
        self.enqueue_register_paths([path])

    def start_next_register(self) -> None:
        if self.register_running:
            return
        if not self.register_queue:
            self.register_total = 0
            self.register_done_count = 0
            return
        path = self.register_queue.pop(0)
        self.register_running = True
        position = self.register_done_count + 1
        total = self.register_done_count + 1 + len(self.register_queue)
        self.status_label.setText(f"取り込み中 {position}/{total}: {path.name}")
        threading.Thread(target=self._register_worker, args=(path,), daemon=True).start()

    def _register_worker(self, path: Path) -> None:
        worker_library = LibraryService.open(self.library.paths)
        try:
            books = worker_library.register_local_books(path)
            self.signals.register_progress.emit(books, f"本棚に追加しました。展開中: {path.name}")
            imported_books: list[Book] = []
            for index, book in enumerate(books, start=1):
                if book.file_kind in {"zip", "cbz", "rar", "cbr", "7z", "cb7"}:
                    worker_library.importer.import_book(book)
                imported_books.append(worker_library.books.get(book.id) or book)
                self.signals.register_progress.emit(
                    imported_books.copy(),
                    f"展開中 {index}/{len(books)}: {book.title}",
                )
            self.signals.register_done.emit(imported_books, None)
        except Exception as exc:
            self.signals.register_done.emit(None, exc)
        finally:
            worker_library.close()

    def on_register_progress(self, books: list[Book] | None, message: str | None) -> None:
        self.reload_books()
        if message:
            self.status_label.setText(message)

    def on_register_done(self, books: list[Book] | None, error: Exception | None) -> None:
        self.register_running = False
        self.register_done_count += 1
        if error is not None:
            self.status_label.setText(f"登録失敗: {error}")
            self.start_next_register()
            return
        self.reload_books()
        label = "、".join(book.title for book in (books or [])[:2])
        if books and len(books) > 2:
            label += f" ほか{len(books) - 2}冊"
        if self.register_queue:
            self.status_label.setText(f"登録しました: {label}")
            self.start_next_register()
        else:
            self.status_label.setText(f"登録しました: {label}")
            self.register_total = 0
            self.register_done_count = 0

    def set_register_buttons_enabled(self, enabled: bool) -> None:
        self.add_file_button.setEnabled(enabled)
        self.add_folder_button.setEnabled(enabled)

    def open_library_folder(self) -> None:
        self.library.paths.library_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["open", str(self.library.paths.library_dir)])
        except Exception as exc:
            self.status_label.setText(f"保存先を開けません: {exc}")

    def selected_book(self) -> Book | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        book_id = item.data(Qt.UserRole)
        return self.library.books.get(book_id)

    def delete_selected_book(self) -> None:
        book = self.selected_book()
        if book is None:
            self.status_label.setText("削除する本を選んでください。")
            return
        title = book.title
        message = QMessageBox(self)
        message.setWindowTitle("本棚から削除")
        message.setIcon(QMessageBox.Warning)
        message.setText("この本を本棚から削除しますか？")
        message.setInformativeText(
            f"{title}\n\n"
            "RAIVが作成した展開済みフォルダ、読書位置、しおりを削除します。\n"
            "元のZIP/RAR/7zファイルは削除しません。"
        )
        message.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        message.setDefaultButton(QMessageBox.No)
        if message.exec() != QMessageBox.Yes:
            self.status_label.setText("削除をキャンセルしました。")
            return
        if self.library.delete_book(book.id):
            self.reload_books()
            self.status_label.setText(f"本棚から削除しました: {title}")
        else:
            self.status_label.setText(f"削除できませんでした: {title}")

    def open_selected_book(self) -> None:
        book = self.selected_book()
        if book is None:
            self.status_label.setText("読む本を選んでください。")
            return
        self.open_book(book.id)

    def open_book(self, book_id: str, fullscreen: bool = False) -> None:
        book = self.library.books.get(book_id)
        if book is None:
            self.status_label.setText("本が見つかりません。")
            return
        source = Path(book.local_path)
        try:
            pages, cleanup_dir = open_pages_for_viewer(source)
        except Exception as exc:
            self.status_label.setText(f"読み込み失敗: {exc}")
            return
        if not pages:
            self.status_label.setText(f"画像が見つかりません: {source}")
            return
        state = self.library.reading_states.get(book.id)
        next_book = next_book_after_reading(book.id, self.library.books.list_books())
        reading_direction = state.reading_direction if state else "rtl"
        self.close_active_reader(return_to_bookshelf=False)
        window = SpreadWindow(
            pages,
            book.title,
            cleanup_dir,
            processed_pages=collect_processed_pages(pages, None),
            reading_direction=reading_direction,
            spread_order=default_spread_order(reading_direction),
            cover_single=state.cover_single if state else True,
            auto_prefetch=True,
            prefetch_count=6,
            page_changed_callback=lambda _index: self.save_reading_state(book.id, window),
            bookmark_callback=lambda page_index: self.add_bookmark(book.id, page_index),
            next_book_callback=(lambda: self.open_next_book_from_window(book.id, window)) if next_book else None,
            next_book_label=next_book.title if next_book else None,
            close_callback=self.on_reader_closed,
            embedded=True,
            parent=self.stack,
        )
        if state is not None:
            window.index = min(max(0, state.page_index), len(pages) - 1)
            window.render_spread()
        self.active_reader = window
        self.stack.addWidget(window)
        self.stack.setCurrentWidget(window)
        self.setWindowTitle(f"RAIV - {book.title}")
        if fullscreen:
            window.is_fullscreen = True
            self.showFullScreen()
        elif not self.isMaximized():
            screen = self.screen()
            geometry = screen.availableGeometry() if screen is not None else None
            self.resize(preferred_reader_size(geometry))
        window.setFocus(Qt.ActiveWindowFocusReason)

    def open_next_book_from_window(self, current_book_id: str, window: SpreadWindow) -> None:
        next_book = next_book_after_reading(current_book_id, self.library.books.list_books())
        if next_book is None:
            window.statusBar().showMessage("次の巻はありません。")
            return
        self.save_reading_state(current_book_id, window)
        was_fullscreen = window.is_fullscreen
        self.suppress_reader_return = True
        window.close()
        self.suppress_reader_return = False
        self.open_book(next_book.id, fullscreen=was_fullscreen)

    def close_active_reader(self, return_to_bookshelf: bool = True) -> None:
        if self.active_reader is None:
            return
        self.suppress_reader_return = not return_to_bookshelf
        self.active_reader.close()
        self.suppress_reader_return = False

    def on_reader_closed(self, window: SpreadWindow) -> None:
        if self.active_reader is window:
            self.active_reader = None
        if self.stack.indexOf(window) >= 0:
            self.stack.removeWidget(window)
        window.deleteLater()
        self.reload_books()
        if not self.suppress_reader_return:
            self.stack.setCurrentWidget(self.bookshelf_page)
            self.setWindowTitle("RAIV Bookshelf")
            self.raise_()
            self.activateWindow()

    def save_reading_state(self, book_id: str, window: SpreadWindow) -> None:
        self.library.reading_states.save(reading_state_from_window(book_id, window))
        book = self.library.books.get(book_id)
        if book is not None:
            self.library.books.upsert(book.with_updates(reading_status="reading", last_opened_at=utc_now_iso()))

    def add_bookmark(self, book_id: str, page_index: int) -> None:
        self.library.bookmarks.add(book_id, page_index, label=f"p.{page_index + 1}")

    def closeEvent(self, event) -> None:
        if self.active_reader is not None:
            self.close_active_reader(return_to_bookshelf=False)
        self.library.close()
        super().closeEvent(event)


def rewrite_visible_library_path(path_text: str, old_root: Path, new_root: Path) -> str:
    old = str(old_root.expanduser())
    new = str(new_root.expanduser())
    if path_text == old:
        return new
    prefix = old + "/"
    if path_text.startswith(prefix):
        return new + "/" + path_text[len(prefix):]
    return path_text
