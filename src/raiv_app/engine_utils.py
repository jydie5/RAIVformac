from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ENGINES_DIR = ROOT_DIR / "test" / "engines"


def bundled_root() -> Path | None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root) if bundle_root else None


@dataclass
class EngineRunResult:
    engine: str
    executable: str
    input: str
    output: str
    returncode: int
    elapsed_sec: float
    stdout: str
    output_exists: bool
    output_size: int


def realcugan_executable() -> Path | None:
    frozen_root = bundled_root()
    env_path = os.environ.get("RAIV_REALCUGAN_PATH")
    candidates = [
        Path(env_path).expanduser() if env_path else None,
        ENGINES_DIR / "realcugan-ncnn-vulkan" / "realcugan-ncnn-vulkan",
        ENGINES_DIR / "realcugan-ncnn-vulkan-20220728-macos" / "realcugan-ncnn-vulkan",
        ROOT_DIR / "engines" / "realcugan-ncnn-vulkan" / "realcugan-ncnn-vulkan",
        ROOT_DIR / "engines" / "realcugan-ncnn-vulkan-20220728-macos" / "realcugan-ncnn-vulkan",
        ROOT_DIR / "tools" / "realcugan-ncnn-vulkan" / "realcugan-ncnn-vulkan",
        ROOT_DIR / "tools" / "realcugan-ncnn-vulkan" / "realcugan-ncnn-vulkan.exe",
    ]
    if frozen_root is not None:
        candidates = [
            frozen_root / "engines" / "realcugan-ncnn-vulkan" / "realcugan-ncnn-vulkan",
            frozen_root / "engines" / "realcugan-ncnn-vulkan-20220728-macos" / "realcugan-ncnn-vulkan",
            *candidates,
        ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def run_realcugan(
    input_path: Path,
    output_path: Path,
    *,
    scale: int = 2,
    noise: int = 1,
    tile: int = 0,
    model: str = "models-se",
    tta: bool = False,
) -> EngineRunResult:
    executable = realcugan_executable()
    if executable is None:
        raise FileNotFoundError("realcugan-ncnn-vulkan executable was not found")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-s",
        str(scale),
        "-n",
        str(noise),
        "-t",
        str(tile),
        "-m",
        model,
        "-f",
        "png",
    ]
    if tta:
        command.append("-x")
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(executable.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    return EngineRunResult(
        engine="realcugan-ncnn-vulkan",
        executable=str(executable),
        input=str(input_path),
        output=str(output_path),
        returncode=completed.returncode,
        elapsed_sec=elapsed,
        stdout=completed.stdout.strip(),
        output_exists=output_path.exists(),
        output_size=output_path.stat().st_size if output_path.exists() else 0,
    )


def write_results_json(path: Path, results: list[EngineRunResult], extra: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "extra": extra or {},
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
