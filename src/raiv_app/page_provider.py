from __future__ import annotations

import shutil
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from raiv_app.archive_utils import (
    archive_display_name,
    archive_member_output_path,
    collect_folder_images,
    is_archive,
    is_archive_image_member,
    is_image,
    load_sample_pages,
    natural_sort_key,
)


class LazyZipPageList(Sequence[Path]):
    def __init__(self, archive_path: Path, temp_dir: Path, members: list[zipfile.ZipInfo]) -> None:
        self.archive_path = archive_path
        self.temp_dir = temp_dir
        self.members = members
        self.extracted: dict[int, Path] = {}

    def __len__(self) -> int:
        return len(self.members)

    def __getitem__(self, index: int | slice) -> Path | list[Path]:
        if isinstance(index, slice):
            return [self.materialize(item) for item in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self.members)
        if index < 0 or index >= len(self.members):
            raise IndexError(index)
        return self.materialize(index)

    def materialize(self, index: int) -> Path:
        cached = self.extracted.get(index)
        if cached is not None:
            return cached
        member = self.members[index]
        output = archive_member_output_path(self.temp_dir, member.filename)
        if output is None:
            raise RuntimeError(f"unsafe archive member: {member.filename}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.archive_path) as archive:
            with archive.open(member) as source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        resolved = output.resolve()
        self.extracted[index] = resolved
        return resolved


def open_pages_for_viewer(source_path: Path) -> tuple[Sequence[Path], Path | None]:
    source_path = source_path.expanduser().resolve()
    if source_path.is_dir():
        return collect_folder_images(source_path), None
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if is_image(source_path):
        return [source_path], None
    if not is_archive(source_path):
        raise RuntimeError(f"unsupported sample type: {source_path.suffix}")
    suffix = source_path.suffix.lower()
    if suffix in {".zip", ".cbz"}:
        return open_zip_pages_for_viewer(source_path)
    return load_sample_pages(source_path)


def open_zip_pages_for_viewer(archive_path: Path) -> tuple[LazyZipPageList, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="raiv_pages_"))
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = sorted(
                [info for info in archive.infolist() if not info.is_dir() and is_archive_image_member(info.filename)],
                key=lambda info: natural_sort_key(archive_display_name(info.filename)),
            )
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return LazyZipPageList(archive_path, temp_dir, members), temp_dir
