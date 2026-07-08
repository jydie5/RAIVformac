from __future__ import annotations

import json
import re
import sqlite3
import uuid
import shutil
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image

from .archive_utils import (
    ArchiveVolumeGroup,
    archive_display_name,
    collect_folder_images,
    discover_archive_volume_groups,
    extract_external_archive_images,
    is_archive,
    is_archive_image_member,
    is_image,
    list_archive_image_members,
    natural_sort_key,
)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Book:
    id: str
    title: str
    source_uri: str
    local_path: str
    source_kind: str
    file_kind: str
    page_count: int | None = None
    cover_page_index: int = 0
    cover_thumbnail_path: str | None = None
    reading_status: str = "unread"
    last_opened_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def with_updates(self, **updates: Any) -> Book:
        return replace(self, **updates)


@dataclass(frozen=True)
class ReadingState:
    book_id: str
    page_index: int
    spread_mode: str = "spread"
    reading_direction: str = "rtl"
    cover_single: bool = True
    fit_mode: str = "page"
    zoom: float | None = None
    pan_x: float | None = None
    pan_y: float | None = None
    correction_preset: str = "標準"
    updated_at: str | None = None


@dataclass(frozen=True)
class Bookmark:
    id: str
    book_id: str
    page_index: int
    label: str
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ImportResult:
    book_id: str
    book_dir: Path
    original_path: Path
    pages_dir: Path
    page_paths: list[Path]
    page_count: int


@dataclass(frozen=True)
class LibraryPaths:
    base_dir: Path
    database_path: Path
    library_dir: Path
    cache_dir: Path
    legacy_library_dir: Path | None = None
    settings_path: Path | None = None

    @classmethod
    def for_base_dir(cls, base_dir: Path) -> LibraryPaths:
        root = base_dir.expanduser()
        return cls(
            base_dir=root,
            database_path=root / "raiv.sqlite3",
            library_dir=root / "Library",
            cache_dir=root / "Cache",
            settings_path=root / "settings.json",
        )

    @classmethod
    def default(cls) -> LibraryPaths:
        app_support = Path.home() / "Library" / "Application Support" / "RAIV"
        settings_path = app_support / "settings.json"
        settings = load_library_settings(settings_path)
        return cls(
            base_dir=app_support,
            database_path=app_support / "raiv.sqlite3",
            library_dir=Path(settings.get("library_dir") or Path.home() / "RAIV Library").expanduser(),
            cache_dir=Path.home() / "Library" / "Caches" / "RAIV",
            legacy_library_dir=app_support / "Library",
            settings_path=settings_path,
        )

    def ensure(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def with_library_dir(self, library_dir: Path) -> LibraryPaths:
        return replace(self, library_dir=library_dir.expanduser())


def load_library_settings(settings_path: Path) -> dict[str, Any]:
    try:
        with settings_path.expanduser().open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_library_settings(paths: LibraryPaths, *, library_dir_confirmed: bool) -> None:
    settings_path = paths.settings_path or paths.base_dir / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings = load_library_settings(settings_path)
    settings["library_dir"] = str(paths.library_dir.expanduser())
    settings["library_dir_confirmed"] = library_dir_confirmed
    with settings_path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def is_library_dir_confirmed(paths: LibraryPaths) -> bool:
    settings_path = paths.settings_path or paths.base_dir / "settings.json"
    return bool(load_library_settings(settings_path).get("library_dir_confirmed"))


class LibraryDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                local_path TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                file_kind TEXT NOT NULL,
                page_count INTEGER,
                cover_page_index INTEGER NOT NULL DEFAULT 0,
                cover_thumbnail_path TEXT,
                reading_status TEXT NOT NULL DEFAULT 'unread',
                last_opened_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reading_state (
                book_id TEXT PRIMARY KEY,
                page_index INTEGER NOT NULL,
                spread_mode TEXT NOT NULL,
                reading_direction TEXT NOT NULL,
                cover_single INTEGER NOT NULL,
                fit_mode TEXT NOT NULL,
                zoom REAL,
                pan_x REAL,
                pan_y REAL,
                correction_preset TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS bookmarks (
                id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL,
                page_index INTEGER NOT NULL,
                label TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_books_last_opened_at
                ON books(last_opened_at DESC, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bookmarks_book_page
                ON bookmarks(book_id, page_index, created_at);
            """
        )
        self.connection.commit()


class LibraryService:
    def __init__(self, paths: LibraryPaths, db: LibraryDatabase) -> None:
        self.paths = paths
        self.db = db
        self.books = BookshelfRepository(db)
        self.reading_states = ReadingStateService(db)
        self.bookmarks = BookmarkRepository(db)
        self.scanner = BookScanner()
        self.importer = LibraryImportService(paths, self.books)

    @classmethod
    def open(cls, paths: LibraryPaths | None = None) -> LibraryService:
        resolved_paths = paths or LibraryPaths.default()
        resolved_paths.ensure()
        service = cls(resolved_paths, LibraryDatabase(resolved_paths.database_path))
        service.migrate_legacy_library_storage()
        return service

    def close(self) -> None:
        self.db.close()

    def register_local_book(self, source_path: Path) -> Book:
        book = self.scanner.scan(source_path)
        return self.books.upsert(book)

    def register_local_books(self, source_path: Path) -> list[Book]:
        books = self.scanner.scan_many(source_path)
        return [self.books.upsert(book) for book in books]

    def delete_book(self, book_id: str, remove_managed_storage: bool = True) -> bool:
        if remove_managed_storage:
            self.importer.delete_managed_storage(book_id)
        return self.books.delete(book_id)

    def migrate_legacy_library_storage(self) -> int:
        return LibraryStorageMigrator(self.paths, self.books).migrate()


class BookshelfRepository:
    def __init__(self, db: LibraryDatabase) -> None:
        self.db = db

    def upsert(self, book: Book) -> Book:
        now = utc_now_iso()
        created_at = book.created_at or self._existing_created_at(book.id) or now
        updated = replace(book, created_at=created_at, updated_at=now)
        self.db.connection.execute(
            """
            INSERT INTO books (
                id, title, source_uri, local_path, source_kind, file_kind,
                page_count, cover_page_index, cover_thumbnail_path, reading_status,
                last_opened_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                source_uri=excluded.source_uri,
                local_path=excluded.local_path,
                source_kind=excluded.source_kind,
                file_kind=excluded.file_kind,
                page_count=excluded.page_count,
                cover_page_index=excluded.cover_page_index,
                cover_thumbnail_path=excluded.cover_thumbnail_path,
                reading_status=excluded.reading_status,
                last_opened_at=excluded.last_opened_at,
                updated_at=excluded.updated_at
            """,
            (
                updated.id,
                updated.title,
                updated.source_uri,
                updated.local_path,
                updated.source_kind,
                updated.file_kind,
                updated.page_count,
                updated.cover_page_index,
                updated.cover_thumbnail_path,
                updated.reading_status,
                updated.last_opened_at,
                updated.created_at,
                updated.updated_at,
            ),
        )
        self.db.connection.commit()
        return updated

    def get(self, book_id: str) -> Book | None:
        row = self.db.connection.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return _book_from_row(row) if row else None

    def list_books(self) -> list[Book]:
        rows = self.db.connection.execute(
            """
            SELECT * FROM books
            ORDER BY
                last_opened_at IS NULL,
                last_opened_at DESC,
                updated_at DESC,
                title COLLATE NOCASE
            """
        ).fetchall()
        return [_book_from_row(row) for row in rows]

    def delete(self, book_id: str) -> bool:
        cursor = self.db.connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self.db.connection.commit()
        return cursor.rowcount > 0

    def _existing_created_at(self, book_id: str) -> str | None:
        row = self.db.connection.execute("SELECT created_at FROM books WHERE id = ?", (book_id,)).fetchone()
        return row["created_at"] if row else None


class LibraryStorageMigrator:
    def __init__(self, paths: LibraryPaths, books: BookshelfRepository) -> None:
        self.paths = paths
        self.books = books

    def migrate(self) -> int:
        legacy_dir = self.paths.legacy_library_dir
        target_dir = self.paths.library_dir
        if legacy_dir is None:
            return self.rename_managed_book_directories()
        legacy_dir = legacy_dir.expanduser()
        target_dir = target_dir.expanduser()
        if legacy_dir == target_dir or not legacy_dir.exists():
            return self.rename_managed_book_directories()

        target_dir.mkdir(parents=True, exist_ok=True)
        moved_count = self._move_book_directories(legacy_dir, target_dir)
        updated_count = self._rewrite_book_paths(legacy_dir, target_dir)
        renamed_count = self.rename_managed_book_directories()
        self._remove_empty_legacy_dir(legacy_dir)
        return max(moved_count, updated_count, renamed_count)

    def rename_managed_book_directories(self) -> int:
        renamed_count = 0
        for book in self.books.list_books():
            current_book_dir = managed_book_dir_from_book(book, self.paths.library_dir)
            if current_book_dir is None or not current_book_dir.exists():
                continue
            desired_book_dir = managed_book_dir_for_book(book, self.paths.library_dir)
            if current_book_dir == desired_book_dir:
                continue
            if desired_book_dir.exists():
                continue
            current_book_dir.rename(desired_book_dir)
            local_path = rewrite_path_prefix(book.local_path, current_book_dir, desired_book_dir)
            cover_path = (
                rewrite_path_prefix(book.cover_thumbnail_path, current_book_dir, desired_book_dir)
                if book.cover_thumbnail_path
                else book.cover_thumbnail_path
            )
            self.books.upsert(book.with_updates(local_path=local_path, cover_thumbnail_path=cover_path))
            renamed_count += 1
        return renamed_count

    def _move_book_directories(self, legacy_dir: Path, target_dir: Path) -> int:
        moved_count = 0
        for source in sorted(legacy_dir.iterdir(), key=lambda path: natural_sort_key(path.name)):
            if not source.is_dir():
                continue
            destination = target_dir / source.name
            if destination.exists():
                continue
            shutil.move(str(source), str(destination))
            moved_count += 1
        return moved_count

    def _rewrite_book_paths(self, legacy_dir: Path, target_dir: Path) -> int:
        updated_count = 0
        for book in self.books.list_books():
            local_path = rewrite_path_prefix(book.local_path, legacy_dir, target_dir)
            cover_path = (
                rewrite_path_prefix(book.cover_thumbnail_path, legacy_dir, target_dir)
                if book.cover_thumbnail_path
                else book.cover_thumbnail_path
            )
            if local_path != book.local_path or cover_path != book.cover_thumbnail_path:
                self.books.upsert(book.with_updates(local_path=local_path, cover_thumbnail_path=cover_path))
                updated_count += 1
        return updated_count

    def _remove_empty_legacy_dir(self, legacy_dir: Path) -> None:
        try:
            next(legacy_dir.iterdir())
        except StopIteration:
            legacy_dir.rmdir()
        except FileNotFoundError:
            return


def rewrite_path_prefix(path_text: str, old_root: Path, new_root: Path) -> str:
    old = str(old_root.expanduser())
    new = str(new_root.expanduser())
    if path_text == old:
        return new
    prefix = old + "/"
    if path_text.startswith(prefix):
        return new + "/" + path_text[len(prefix):]
    return path_text


class ReadingStateService:
    def __init__(self, db: LibraryDatabase) -> None:
        self.db = db

    def save(self, state: ReadingState) -> ReadingState:
        updated = replace(state, updated_at=utc_now_iso())
        self.db.connection.execute(
            """
            INSERT INTO reading_state (
                book_id, page_index, spread_mode, reading_direction, cover_single,
                fit_mode, zoom, pan_x, pan_y, correction_preset, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                page_index=excluded.page_index,
                spread_mode=excluded.spread_mode,
                reading_direction=excluded.reading_direction,
                cover_single=excluded.cover_single,
                fit_mode=excluded.fit_mode,
                zoom=excluded.zoom,
                pan_x=excluded.pan_x,
                pan_y=excluded.pan_y,
                correction_preset=excluded.correction_preset,
                updated_at=excluded.updated_at
            """,
            (
                updated.book_id,
                updated.page_index,
                updated.spread_mode,
                updated.reading_direction,
                int(updated.cover_single),
                updated.fit_mode,
                updated.zoom,
                updated.pan_x,
                updated.pan_y,
                updated.correction_preset,
                updated.updated_at,
            ),
        )
        self.db.connection.commit()
        return updated

    def get(self, book_id: str) -> ReadingState | None:
        row = self.db.connection.execute(
            "SELECT * FROM reading_state WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        return _reading_state_from_row(row) if row else None


class BookmarkRepository:
    def __init__(self, db: LibraryDatabase) -> None:
        self.db = db

    def add(self, book_id: str, page_index: int, label: str, note: str | None = None) -> Bookmark:
        now = utc_now_iso()
        bookmark = Bookmark(
            id=str(uuid.uuid4()),
            book_id=book_id,
            page_index=page_index,
            label=label,
            note=note,
            created_at=now,
            updated_at=now,
        )
        self.db.connection.execute(
            """
            INSERT INTO bookmarks (
                id, book_id, page_index, label, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bookmark.id,
                bookmark.book_id,
                bookmark.page_index,
                bookmark.label,
                bookmark.note,
                bookmark.created_at,
                bookmark.updated_at,
            ),
        )
        self.db.connection.commit()
        return bookmark

    def list_for_book(self, book_id: str) -> list[Bookmark]:
        rows = self.db.connection.execute(
            """
            SELECT * FROM bookmarks
            WHERE book_id = ?
            ORDER BY page_index, created_at
            """,
            (book_id,),
        ).fetchall()
        return [_bookmark_from_row(row) for row in rows]

    def delete(self, bookmark_id: str) -> bool:
        cursor = self.db.connection.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        self.db.connection.commit()
        return cursor.rowcount > 0


class LibraryImportService:
    def __init__(self, paths: LibraryPaths, books: BookshelfRepository) -> None:
        self.paths = paths
        self.books = books

    def book_dir_for_id(self, book_id: str) -> Path:
        return self.paths.library_dir / book_id.replace(":", "_")

    def book_dir_for_book(self, book: Book) -> Path:
        return managed_book_dir_for_book(book, self.paths.library_dir)

    def delete_managed_storage(self, book_id: str) -> None:
        book = self.books.get(book_id)
        if book is not None:
            current_dir = managed_book_dir_from_book(book, self.paths.library_dir)
            if current_dir is not None:
                shutil.rmtree(current_dir, ignore_errors=True)
        shutil.rmtree(self.book_dir_for_id(book_id), ignore_errors=True)

    def import_book(self, book: Book) -> ImportResult:
        source = Path(book.local_path).expanduser()
        group_key = archive_group_key_from_source_uri(book.source_uri)
        book_dir = self.book_dir_for_book(book)
        original_dir = book_dir / "original"
        pages_dir = book_dir / "pages"
        cover_dir = book_dir / "cover"
        original_dir.mkdir(parents=True, exist_ok=True)
        pages_dir.mkdir(parents=True, exist_ok=True)
        cover_dir.mkdir(parents=True, exist_ok=True)
        original_path = original_dir / source.name
        if source.is_file() and not group_key:
            shutil.copy2(source, original_path)
        elif source.is_file():
            original_path = source
        else:
            raise RuntimeError(f"library import currently supports archive files only: {source}")
        member_names = None
        if group_key:
            member_names = archive_member_names_for_group(source, group_key)
        if book.file_kind in {"zip", "cbz"}:
            page_paths = self._extract_zip_pages(original_path, pages_dir, member_names=member_names)
        elif book.file_kind in {"rar", "cbr"}:
            page_paths = self._extract_rar_pages(original_path, pages_dir, member_names=member_names)
        elif book.file_kind in {"7z", "cb7"}:
            page_paths = self._extract_7z_pages(original_path, pages_dir, member_names=member_names)
        else:
            raise RuntimeError(f"library import does not support {book.file_kind} yet")
        cover_path = self._generate_cover(page_paths, cover_dir)
        updated = book.with_updates(
            local_path=str(pages_dir),
            file_kind="folder",
            page_count=len(page_paths),
            cover_thumbnail_path=str(cover_path) if cover_path else book.cover_thumbnail_path,
        )
        self.books.upsert(updated)
        return ImportResult(
            book_id=book.id,
            book_dir=book_dir,
            original_path=original_path,
            pages_dir=pages_dir,
            page_paths=page_paths,
            page_count=len(page_paths),
        )

    def _generate_cover(self, page_paths: list[Path], cover_dir: Path) -> Path | None:
        if not page_paths:
            return None
        cover_path = cover_dir / "cover.jpg"
        try:
            with Image.open(page_paths[0]) as image:
                image.thumbnail((360, 540))
                image.convert("RGB").save(cover_path, format="JPEG", quality=88)
            return cover_path.resolve()
        except Exception:
            return None

    def _extract_zip_pages(self, archive_path: Path, pages_dir: Path, member_names: set[str] | None = None) -> list[Path]:
        self._clear_page_dir(pages_dir)
        page_paths: list[Path] = []
        with zipfile.ZipFile(archive_path) as archive:
            members = sorted(
                [
                    info
                    for info in archive.infolist()
                    if not info.is_dir()
                    and is_archive_image_member(info.filename)
                    and (member_names is None or archive_display_name(info.filename) in member_names)
                ],
                key=lambda info: natural_sort_key(archive_display_name(info.filename)),
            )
            for index, info in enumerate(members, start=1):
                suffix = Path(archive_display_name(info.filename)).suffix.lower() or ".img"
                output = pages_dir / f"{index:06d}{suffix}"
                with archive.open(info) as source, output.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                page_paths.append(output.resolve())
        return page_paths

    def _extract_rar_pages(self, archive_path: Path, pages_dir: Path, member_names: set[str] | None = None) -> list[Path]:
        try:
            import rarfile
            self._clear_page_dir(pages_dir)
            page_paths: list[Path] = []
            with rarfile.RarFile(archive_path) as archive:
                members = sorted(
                    [
                        info
                        for info in archive.infolist()
                        if not info.isdir()
                        and is_archive_image_member(info.filename)
                        and (member_names is None or archive_display_name(info.filename) in member_names)
                    ],
                    key=lambda info: natural_sort_key(archive_display_name(info.filename)),
                )
                for index, info in enumerate(members, start=1):
                    suffix = Path(archive_display_name(info.filename)).suffix.lower() or ".img"
                    output = pages_dir / f"{index:06d}{suffix}"
                    with archive.open(info) as source, output.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    page_paths.append(output.resolve())
            return page_paths
        except Exception as exc:
            return self._extract_external_pages(archive_path, pages_dir, member_names=member_names, primary_error=exc)

    def _extract_7z_pages(self, archive_path: Path, pages_dir: Path, member_names: set[str] | None = None) -> list[Path]:
        try:
            import py7zr
            self._clear_page_dir(pages_dir)
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=pages_dir)
            return self._normalize_extracted_pages(pages_dir, member_names=member_names)
        except Exception as exc:
            return self._extract_external_pages(archive_path, pages_dir, member_names=member_names, primary_error=exc)

    def _extract_external_pages(
        self,
        archive_path: Path,
        pages_dir: Path,
        member_names: set[str] | None = None,
        primary_error: Exception | None = None,
    ) -> list[Path]:
        self._clear_page_dir(pages_dir)
        extract_external_archive_images(archive_path, pages_dir, member_names=member_names, primary_error=primary_error)
        return self._normalize_extracted_pages(pages_dir, member_names=None)

    def _normalize_extracted_pages(self, pages_dir: Path, member_names: set[str] | None = None) -> list[Path]:
        image_paths = [
            path
            for path in collect_folder_images(pages_dir)
            if member_names is None or archive_display_name(str(path.relative_to(pages_dir))) in member_names
        ]
        normalized_paths: list[Path] = []
        for index, path in enumerate(image_paths, start=1):
            suffix = path.suffix.lower() or ".img"
            output = pages_dir / f"{index:06d}{suffix}"
            if path.resolve() != output.resolve():
                output.parent.mkdir(parents=True, exist_ok=True)
                path.replace(output)
            normalized_paths.append(output.resolve())
        for item in sorted(pages_dir.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            if item.is_file() and item not in normalized_paths:
                item.unlink(missing_ok=True)
            elif item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass
        return normalized_paths

    def _clear_page_dir(self, pages_dir: Path) -> None:
        for old_page in pages_dir.iterdir():
            if old_page.is_file():
                old_page.unlink()
            elif old_page.is_dir():
                shutil.rmtree(old_page, ignore_errors=True)


class BookScanner:
    def scan(self, source_path: Path) -> Book:
        path = source_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_dir():
            return self._scan_folder(path)
        if path.is_file() and is_image(path):
            return self._scan_image(path)
        if path.is_file() and is_archive(path):
            return self._scan_archive(path)
        raise RuntimeError(f"unsupported book source: {path}")

    def scan_many(self, source_path: Path) -> list[Book]:
        path = source_path.expanduser().resolve()
        if path.is_file() and is_archive(path):
            groups = discover_archive_volume_groups(path)
            if len(groups) >= 2:
                return [self._book_for_archive_group(path, group) for group in groups]
        return [self.scan(path)]

    def _scan_folder(self, path: Path) -> Book:
        pages = collect_folder_images(path)
        return self._book_for_path(path, file_kind="folder", page_count=len(pages))

    def _scan_image(self, path: Path) -> Book:
        return self._book_for_path(path, file_kind="image", page_count=1)

    def _scan_archive(self, path: Path) -> Book:
        suffix = path.suffix.lower()
        if suffix in {".zip", ".cbz"}:
            page_count = _count_zip_pages(path)
        elif suffix in {".rar", ".cbr"}:
            page_count = _count_rar_pages(path)
        elif suffix in {".7z", ".cb7"}:
            page_count = _count_7z_pages(path)
        else:
            page_count = None
        return self._book_for_path(path, file_kind=suffix.lstrip("."), page_count=page_count)

    def _book_for_archive_group(self, path: Path, group: ArchiveVolumeGroup) -> Book:
        suffix = path.suffix.lower()
        source_uri = archive_group_source_uri(path, group.key)
        return Book(
            id=local_archive_group_content_id(path, group),
            title=group.title,
            source_uri=source_uri,
            local_path=str(path),
            source_kind="local",
            file_kind=suffix.lstrip("."),
            page_count=group.page_count,
        )

    def _book_for_path(self, path: Path, file_kind: str, page_count: int | None) -> Book:
        local_path = str(path)
        return Book(
            id=local_content_id(path),
            title=path.stem if path.is_file() else path.name,
            source_uri=local_path,
            local_path=local_path,
            source_kind="local",
            file_kind=file_kind,
            page_count=page_count,
        )


def local_content_id(path: Path) -> str:
    stat = path.stat()
    digest = sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    if path.is_file():
        _update_partial_file_hash(path, digest)
    return "local:" + digest.hexdigest()[:32]


def local_archive_group_content_id(path: Path, group: ArchiveVolumeGroup) -> str:
    stat = path.stat()
    digest = sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    digest.update(group.key.encode("utf-8"))
    digest.update(str(group.page_count).encode("ascii"))
    for member in group.members[:3] + group.members[-3:]:
        digest.update(member.name.encode("utf-8"))
        if member.size is not None:
            digest.update(str(member.size).encode("ascii"))
    return "local-archive-group:" + digest.hexdigest()[:32]


def archive_group_source_uri(path: Path, group_key: str) -> str:
    return f"{path.resolve()}#raiv-group={group_key}"


def archive_group_key_from_source_uri(source_uri: str) -> str:
    marker = "#raiv-group="
    if marker not in source_uri:
        return ""
    return source_uri.split(marker, 1)[1]


def archive_member_names_for_group(archive_path: Path, group_key: str) -> set[str]:
    groups = discover_archive_volume_groups(archive_path)
    for group in groups:
        if group.key == group_key:
            return {member.name for member in group.members}
    if not group_key:
        return {member.name for member in list_archive_image_members(archive_path)}
    raise RuntimeError(f"archive group not found: {group_key}")


def managed_book_dir_for_book(book: Book, library_dir: Path) -> Path:
    return library_dir / managed_book_dir_name(book.title, book.id)


def managed_book_dir_from_book(book: Book, library_dir: Path) -> Path | None:
    local_path = Path(book.local_path).expanduser()
    try:
        relative = local_path.relative_to(library_dir.expanduser())
    except ValueError:
        return None
    parts = relative.parts
    if not parts:
        return None
    return library_dir.expanduser() / parts[0]


def managed_book_dir_name(title: str, book_id: str) -> str:
    prefix = sanitize_path_component(title)[:80].strip(" ._") or "Untitled"
    suffix = book_id.replace(":", "_")[:18]
    return f"{prefix}__{suffix}"


def sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "Untitled"


def _update_partial_file_hash(path: Path, digest: Any) -> None:
    chunk_size = 65536
    size = path.stat().st_size
    with path.open("rb") as handle:
        digest.update(handle.read(chunk_size))
        if size > chunk_size:
            handle.seek(max(0, size - chunk_size))
            digest.update(handle.read(chunk_size))


def _count_zip_pages(path: Path) -> int:
    import zipfile

    with zipfile.ZipFile(path) as archive:
        return len(
            [
                info
                for info in archive.infolist()
                if not info.is_dir() and is_archive_image_member(info.filename)
            ]
        )


def _count_rar_pages(path: Path) -> int | None:
    try:
        import rarfile
    except ImportError:
        return None

    with rarfile.RarFile(path) as archive:
        return len(
            [
                info
                for info in archive.infolist()
                if not info.isdir() and is_archive_image_member(info.filename)
            ]
        )


def _count_7z_pages(path: Path) -> int | None:
    try:
        import py7zr
    except ImportError:
        return None

    with py7zr.SevenZipFile(path, mode="r") as archive:
        names = archive.getnames()
    return len(
        [
            name
            for name in sorted(names, key=lambda value: natural_sort_key(archive_display_name(value)))
            if is_archive_image_member(name)
        ]
    )


def _book_from_row(row: sqlite3.Row) -> Book:
    return Book(
        id=row["id"],
        title=row["title"],
        source_uri=row["source_uri"],
        local_path=row["local_path"],
        source_kind=row["source_kind"],
        file_kind=row["file_kind"],
        page_count=row["page_count"],
        cover_page_index=row["cover_page_index"],
        cover_thumbnail_path=row["cover_thumbnail_path"],
        reading_status=row["reading_status"],
        last_opened_at=row["last_opened_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _reading_state_from_row(row: sqlite3.Row) -> ReadingState:
    return ReadingState(
        book_id=row["book_id"],
        page_index=row["page_index"],
        spread_mode=row["spread_mode"],
        reading_direction=row["reading_direction"],
        cover_single=bool(row["cover_single"]),
        fit_mode=row["fit_mode"],
        zoom=row["zoom"],
        pan_x=row["pan_x"],
        pan_y=row["pan_y"],
        correction_preset=row["correction_preset"],
        updated_at=row["updated_at"],
    )


def _bookmark_from_row(row: sqlite3.Row) -> Bookmark:
    return Bookmark(
        id=row["id"],
        book_id=row["book_id"],
        page_index=row["page_index"],
        label=row["label"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
