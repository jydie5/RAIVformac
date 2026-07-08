from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif"}
ARCHIVE_EXTENSIONS = {".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7"}


@dataclass(frozen=True)
class ArchiveImageMember:
    name: str
    size: int | None = None


@dataclass(frozen=True)
class ArchiveVolumeGroup:
    key: str
    title: str
    members: tuple[ArchiveImageMember, ...]

    @property
    def page_count(self) -> int:
        return len(self.members)


def natural_sort_key(value: str) -> tuple:
    parts = re.split(r"(\d+)", value.casefold().replace("/", "\\"))
    key = []
    for part in parts:
        if part.isdigit():
            key.append((0, int(part), len(part)))
        else:
            key.append((1, part))
    return tuple(key)


def is_image(path: Path) -> bool:
    if path.name.startswith("._"):
        return False
    if "__MACOSX" in path.parts:
        return False
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXTENSIONS


def collect_folder_images(folder: Path) -> list[Path]:
    root = folder.resolve()
    return sorted(
        [path.resolve() for path in root.rglob("*") if path.is_file() and is_image(path)],
        key=lambda path: natural_sort_key(str(path.relative_to(root))),
    )


def archive_display_name(member_name: str) -> str:
    return member_name.replace("\\", "/").lstrip("/")


def is_archive_image_member(member_name: str) -> bool:
    display_name = archive_display_name(member_name)
    path = PurePosixPath(display_name)
    if any(part == "__MACOSX" for part in path.parts):
        return False
    if path.name.startswith("._"):
        return False
    return Path(display_name).suffix.lower() in IMAGE_EXTENSIONS


def archive_member_output_path(temp_dir: Path, member_name: str) -> Path | None:
    parts = PurePosixPath(archive_display_name(member_name)).parts
    safe = []
    for part in parts:
        if part in {"", ".", "/"}:
            continue
        if part == ".." or ":" in part:
            return None
        safe.append(re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", part))
    return temp_dir.joinpath(*safe) if safe else None


def list_archive_image_members(archive_path: Path) -> list[ArchiveImageMember]:
    suffix = archive_path.suffix.lower()
    if suffix in {".zip", ".cbz"}:
        return list_zip_image_members(archive_path)
    if suffix in {".rar", ".cbr"}:
        return list_rar_image_members(archive_path)
    if suffix in {".7z", ".cb7"}:
        return list_7z_image_members(archive_path)
    raise RuntimeError(f"unsupported archive type: {archive_path.suffix}")


def list_zip_image_members(archive_path: Path) -> list[ArchiveImageMember]:
    with zipfile.ZipFile(archive_path) as archive:
        return sorted(
            [
                ArchiveImageMember(archive_display_name(info.filename), info.file_size)
                for info in archive.infolist()
                if not info.is_dir() and is_archive_image_member(info.filename)
            ],
            key=lambda member: natural_sort_key(member.name),
        )


def list_rar_image_members(archive_path: Path) -> list[ArchiveImageMember]:
    try:
        import rarfile
        with rarfile.RarFile(archive_path) as archive:
            return sorted(
                [
                    ArchiveImageMember(archive_display_name(info.filename), getattr(info, "file_size", None))
                    for info in archive.infolist()
                    if not info.isdir() and is_archive_image_member(info.filename)
                ],
                key=lambda member: natural_sort_key(member.name),
            )
    except Exception as exc:
        return list_external_archive_image_members(archive_path, primary_error=exc)


def list_7z_image_members(archive_path: Path) -> list[ArchiveImageMember]:
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            names = archive.getnames()
        return sorted(
            [ArchiveImageMember(archive_display_name(name), None) for name in names if is_archive_image_member(name)],
            key=lambda member: natural_sort_key(member.name),
        )
    except Exception as exc:
        return list_external_archive_image_members(archive_path, primary_error=exc)


def list_external_archive_image_members(
    archive_path: Path,
    primary_error: Exception | None = None,
) -> list[ArchiveImageMember]:
    if shutil.which("bsdtar"):
        result = subprocess.run(
            ["bsdtar", "-tf", str(archive_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return sorted(
                [
                    ArchiveImageMember(archive_display_name(line.strip()), None)
                    for line in result.stdout.splitlines()
                    if line.strip() and is_archive_image_member(line.strip())
                ],
                key=lambda member: natural_sort_key(member.name),
            )
    if shutil.which("7zz"):
        result = subprocess.run(
            ["7zz", "l", "-slt", str(archive_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            names = [
                line.split("=", 1)[1].strip()
                for line in result.stdout.splitlines()
                if line.startswith("Path = ")
            ]
            return sorted(
                [ArchiveImageMember(archive_display_name(name), None) for name in names if is_archive_image_member(name)],
                key=lambda member: natural_sort_key(member.name),
            )
    message = f"no usable external archive lister found for {archive_path.suffix}"
    if primary_error is not None:
        raise RuntimeError(message) from primary_error
    raise RuntimeError(message)


def discover_archive_volume_groups(archive_path: Path, min_pages_per_group: int = 5) -> list[ArchiveVolumeGroup]:
    return group_archive_members(list_archive_image_members(archive_path), archive_path.stem, min_pages_per_group)


def group_archive_members(
    members: list[ArchiveImageMember],
    fallback_title: str,
    min_pages_per_group: int = 5,
) -> list[ArchiveVolumeGroup]:
    if not members:
        return []

    member_parts = [PurePosixPath(member.name).parts for member in members]
    root_depth = _common_root_depth(member_parts)
    candidate_groups: dict[str, list[ArchiveImageMember]] = {}
    for member, parts in zip(members, member_parts, strict=True):
        if len(parts) <= root_depth + 1:
            continue
        key = "/".join(parts[: root_depth + 1])
        candidate_groups.setdefault(key, []).append(member)

    volume_groups = [
        ArchiveVolumeGroup(
            key=key,
            title=PurePosixPath(key).name,
            members=tuple(sorted(group_members, key=lambda item: natural_sort_key(item.name))),
        )
        for key, group_members in candidate_groups.items()
        if len(group_members) >= min_pages_per_group
    ]
    if len(volume_groups) >= 2:
        return sorted(volume_groups, key=lambda group: natural_sort_key(group.key))

    return [
        ArchiveVolumeGroup(
            key="",
            title=fallback_title,
            members=tuple(sorted(members, key=lambda item: natural_sort_key(item.name))),
        )
    ]


def _common_root_depth(member_parts: list[tuple[str, ...]]) -> int:
    if not member_parts:
        return 0
    depth = 0
    shortest = min(len(parts) for parts in member_parts)
    while depth < shortest - 1:
        value = member_parts[0][depth]
        if all(parts[depth] == value for parts in member_parts):
            depth += 1
        else:
            break
    return depth


def extract_zip_images(archive_path: Path, temp_dir: Path) -> list[Path]:
    images: list[Path] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = sorted(
            [info for info in archive.infolist() if not info.is_dir() and is_archive_image_member(info.filename)],
            key=lambda info: natural_sort_key(archive_display_name(info.filename)),
        )
        for info in members:
            output = archive_member_output_path(temp_dir, info.filename)
            if output is None:
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, output.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            images.append(output.resolve())
    return images


def extract_rar_images(archive_path: Path, temp_dir: Path) -> list[Path]:
    try:
        import rarfile
        images: list[Path] = []
        with rarfile.RarFile(archive_path) as archive:
            members = sorted(
                [info for info in archive.infolist() if not info.isdir() and is_archive_image_member(info.filename)],
                key=lambda info: natural_sort_key(archive_display_name(info.filename)),
            )
            for info in members:
                output = archive_member_output_path(temp_dir, info.filename)
                if output is None:
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                images.append(output.resolve())
        return images
    except Exception as exc:
        return extract_external_archive_images(archive_path, temp_dir, primary_error=exc)


def extract_7z_images(archive_path: Path, temp_dir: Path) -> list[Path]:
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            archive.extractall(path=temp_dir)
        return collect_folder_images(temp_dir)
    except Exception as exc:
        return extract_external_archive_images(archive_path, temp_dir, primary_error=exc)


def extract_external_archive_images(
    archive_path: Path,
    temp_dir: Path,
    member_names: set[str] | None = None,
    primary_error: Exception | None = None,
) -> list[Path]:
    command = external_archive_extract_command(archive_path, temp_dir)
    if command is None:
        message = f"no usable external archive extractor found for {archive_path.suffix}"
        if primary_error is not None:
            raise RuntimeError(message) from primary_error
        raise RuntimeError(message)
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"external archive extractor failed: {command[0]}"
        if primary_error is not None:
            raise RuntimeError(message) from primary_error
        raise RuntimeError(message)
    images = collect_folder_images(temp_dir)
    if member_names is None:
        return images
    return [
        path
        for path in images
        if archive_display_name(str(path.relative_to(temp_dir))) in member_names
    ]


def external_archive_extract_command(archive_path: Path, output_dir: Path) -> list[str] | None:
    if shutil.which("bsdtar"):
        return ["bsdtar", "-xf", str(archive_path), "-C", str(output_dir)]
    if shutil.which("unar"):
        return ["unar", "-quiet", "-force-overwrite", "-output-directory", str(output_dir), str(archive_path)]
    if shutil.which("7zz"):
        return ["7zz", "x", "-y", f"-o{output_dir}", str(archive_path)]
    return None


def load_sample_pages(source_path: Path) -> tuple[list[Path], Path | None]:
    source_path = source_path.resolve()
    if source_path.is_dir():
        return collect_folder_images(source_path), None
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if is_image(source_path):
        return [source_path], None
    if not is_archive(source_path):
        raise RuntimeError(f"unsupported sample type: {source_path.suffix}")

    temp_dir = Path(tempfile.mkdtemp(prefix="raiv_sample_"))
    suffix = source_path.suffix.lower()
    try:
        if suffix in {".zip", ".cbz"}:
            pages = extract_zip_images(source_path, temp_dir)
        elif suffix in {".rar", ".cbr"}:
            pages = extract_rar_images(source_path, temp_dir)
        elif suffix in {".7z", ".cb7"}:
            pages = extract_7z_images(source_path, temp_dir)
        else:
            pages = []
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return pages, temp_dir


def discover_samples(sample_dir: Path) -> list[Path]:
    if not sample_dir.exists():
        return []
    candidates = [
        path.resolve()
        for path in sample_dir.iterdir()
        if path.is_dir() or is_archive(path) or is_image(path)
    ]
    return sorted(candidates, key=lambda path: natural_sort_key(path.name))
