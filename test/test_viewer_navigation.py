from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from raiv_app.viewer import SpreadWindow


class ViewerNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.pages = []
        for index in range(20):
            path = self.root / f"{index:04d}.png"
            Image.new("L", (120, 180), index * 8).save(path)
            self.pages.append(path)
        self.window = SpreadWindow(
            self.pages,
            "navigation test",
            processed_pages=list(self.pages),
            cover_single=False,
            auto_prefetch=False,
            settings_path=self.root / "settings.json",
        )
        self.window.resize(1200, 800)

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temporary_directory.cleanup()

    def test_back_and_forth_does_not_cancel_active_prefetch(self) -> None:
        self.window.prefetch_running = True
        generation = self.window.processing_generation

        for _ in range(10):
            self.window.move_by(2)
            self.window.move_by(-2)

        self.assertEqual(self.window.processing_generation, generation)
        self.assertIn(0, self.window.prefetch_target_indexes)

    def test_prefetch_worker_skips_pages_outside_latest_target(self) -> None:
        output_paths = {
            index: self.root / "outputs" / f"{index:04d}.png"
            for index in range(3)
        }
        self.window.prefetch_target_indexes = {2}
        processed_indexes: list[int] = []

        def fake_realcugan(source: Path, output: Path, **_settings):
            index = self.pages.index(source)
            processed_indexes.append(index)
            output.parent.mkdir(parents=True, exist_ok=True)
            Image.open(source).save(output)
            return SimpleNamespace(returncode=0, output_exists=True)

        settings = {"scale": 2, "noise": 0, "tile": 0, "model": "models-se", "tta": False}
        with patch("raiv_app.viewer.run_realcugan", side_effect=fake_realcugan):
            self.window._process_pages_worker(
                [0, 1, 2],
                output_paths,
                settings,
                self.window.processing_generation,
                self.window.current_parameter_key(),
                True,
            )

        self.assertEqual(processed_indexes, [2])

    def test_prefetch_tracks_active_outputs_before_worker_starts(self) -> None:
        self.window.prefetch_enabled = True
        self.window.prefetch_count_default = 2
        self.window.adaptive_prefetch_count = 2

        with (
            patch("raiv_app.viewer.realcugan_executable", return_value=self.root / "realcugan"),
            patch("raiv_app.viewer.threading.Thread") as thread,
        ):
            self.window.start_prefetch()

        self.assertTrue(self.window.prefetch_running)
        self.assertTrue(self.window.active_output_paths)
        thread.return_value.start.assert_called_once()

    def test_cache_pruning_never_deletes_external_processed_images(self) -> None:
        external_output = self.root / "external-processed.png"
        Image.new("L", (120, 180), 255).save(external_output)
        self.window.index = 15
        self.window.processed_pages[0] = external_output

        self.window.prune_revolving_correction_cache()

        self.assertTrue(external_output.exists())
        self.assertIsNone(self.window.processed_pages[0])


if __name__ == "__main__":
    unittest.main()
