from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

import raiv_app.viewer as viewer_module
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
        self.window.resize_quality_timer.stop()
        self.window.display_warm_timer.stop()
        self.window.cache_maintenance_timer.stop()
        self.window.clear_queued_display_requests()
        self.window.visible_display_pool.waitForDone(2000)
        self.window.warm_display_pool.waitForDone(2000)
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

    def test_h_opens_help_without_shift(self) -> None:
        with patch.object(self.window, "show_shortcuts_help") as show_help:
            handled = self.window.handle_navigation_key(Qt.Key_H)

        self.assertTrue(handled)
        show_help.assert_called_once_with()

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

    def test_slow_image_decode_does_not_block_page_navigation(self) -> None:
        self.window.clear_queued_display_requests()
        self.window.visible_display_pool.waitForDone(1000)
        self.window.warm_display_pool.waitForDone(1000)
        self.application.processEvents()
        self.window.display_pixmap_cache.clear()
        self.window.resize_quality_timer.stop()
        self.window.fast_resize_render = False
        original_decode = viewer_module.decode_scaled_display_image

        def slow_decode(*args, **kwargs):
            time.sleep(0.25)
            return original_decode(*args, **kwargs)

        with patch("raiv_app.viewer.decode_scaled_display_image", side_effect=slow_decode):
            started = time.perf_counter()
            self.window.move_by(2)
            navigation_seconds = time.perf_counter() - started
            self.assertLess(navigation_seconds, 0.1)
            self.window.visible_display_pool.waitForDone(2000)
            self.application.processEvents()

        self.assertIsNotNone(self.window.left.pixmap())
        self.assertFalse(self.window.left.pixmap().isNull())
        self.assertIsNotNone(self.window.right.pixmap())
        self.assertFalse(self.window.right.pixmap().isNull())

    def test_spread_is_revealed_only_after_both_async_images_are_ready(self) -> None:
        self.window.clear_queued_display_requests()
        self.window.visible_display_pool.waitForDone(1000)
        self.window.warm_display_pool.waitForDone(1000)
        self.application.processEvents()
        self.window.display_pixmap_cache.clear()
        self.window.resize_quality_timer.stop()
        self.window.fast_resize_render = False
        original_decode = viewer_module.decode_scaled_display_image
        decode_count = 0

        def uneven_decode(*args, **kwargs):
            nonlocal decode_count
            decode_count += 1
            time.sleep(0.05 if decode_count == 1 else 0.3)
            return original_decode(*args, **kwargs)

        with patch("raiv_app.viewer.decode_scaled_display_image", side_effect=uneven_decode):
            self.window.move_by(2)
            self.window.display_warm_timer.stop()
            self.window.cache_maintenance_timer.stop()
            deadline = time.perf_counter() + 0.15
            while time.perf_counter() < deadline:
                self.application.processEvents()
                time.sleep(0.01)
            self.assertTrue(self.window.left.pixmap() is None or self.window.left.pixmap().isNull())
            self.assertTrue(self.window.right.pixmap() is None or self.window.right.pixmap().isNull())
            self.window.visible_display_pool.waitForDone(2000)
            deadline = time.perf_counter() + 0.2
            while time.perf_counter() < deadline:
                self.application.processEvents()
                if (
                    self.window.left.pixmap() is not None
                    and not self.window.left.pixmap().isNull()
                    and self.window.right.pixmap() is not None
                    and not self.window.right.pixmap().isNull()
                ):
                    break
                time.sleep(0.01)

        self.assertFalse(self.window.left.pixmap().isNull())
        self.assertFalse(self.window.right.pixmap().isNull())

    def test_original_fallback_is_visible_while_corrected_images_decode(self) -> None:
        corrected_pages = []
        for index, source in enumerate(self.pages):
            corrected = self.root / f"corrected-{index:04d}.png"
            Image.open(source).save(corrected)
            corrected_pages.append(corrected)
        self.window.processed_pages = corrected_pages
        self.window.clear_queued_display_requests()
        self.window.visible_display_pool.waitForDone(1000)
        self.window.warm_display_pool.waitForDone(1000)
        self.application.processEvents()
        self.window.display_pixmap_cache.clear()
        self.window.resize_quality_timer.stop()
        self.window.fast_resize_render = False
        original_decode = viewer_module.decode_scaled_display_image

        def corrected_is_slow(*args, **kwargs):
            force_grayscale = bool(args[4])
            time.sleep(0.25 if force_grayscale else 0.01)
            return original_decode(*args, **kwargs)

        with patch("raiv_app.viewer.decode_scaled_display_image", side_effect=corrected_is_slow):
            self.window.move_by(2)
            self.window.display_warm_timer.stop()
            self.window.cache_maintenance_timer.stop()
            deadline = time.perf_counter() + 0.1
            while time.perf_counter() < deadline:
                self.application.processEvents()
                time.sleep(0.005)

            self.assertFalse(self.window.left.pixmap().isNull())
            self.assertFalse(self.window.right.pixmap().isNull())
            desired_keys = [
                self.window.desired_display_keys[id(self.window.left)],
                self.window.desired_display_keys[id(self.window.right)],
            ]
            self.assertTrue(any(key not in self.window.display_pixmap_cache for key in desired_keys))

            self.window.visible_display_pool.waitForDone(2000)
            self.application.processEvents()

        self.assertTrue(all(key in self.window.display_pixmap_cache for key in desired_keys))
        self.assertFalse(self.window.left.pixmap().isNull())
        self.assertFalse(self.window.right.pixmap().isNull())

    def test_display_cache_remains_bounded(self) -> None:
        for index in range(self.window.display_pixmap_cache_limit + 10):
            self.window.cache_display_pixmap(("test", index), QPixmap(20, 20))

        self.assertEqual(
            len(self.window.display_pixmap_cache),
            self.window.display_pixmap_cache_limit,
        )

    def test_window_close_does_not_wait_for_active_decode(self) -> None:
        self.window.clear_queued_display_requests()
        self.window.visible_display_pool.waitForDone(1000)
        self.application.processEvents()
        self.window.display_pixmap_cache.clear()
        original_decode = viewer_module.decode_scaled_display_image

        def slow_decode(*args, **kwargs):
            time.sleep(0.5)
            return original_decode(*args, **kwargs)

        with patch("raiv_app.viewer.decode_scaled_display_image", side_effect=slow_decode):
            self.window.move_by(2)
            started = time.perf_counter()
            self.window.close()
            close_seconds = time.perf_counter() - started

        self.assertLess(close_seconds, 0.1)

    def test_reading_position_save_is_debounced_outside_navigation(self) -> None:
        saved_indexes: list[int] = []
        self.window.page_changed_callback = saved_indexes.append

        self.window.move_by(2)
        self.window.move_by(2)

        self.assertEqual(saved_indexes, [])
        deadline = time.perf_counter() + 0.45
        while time.perf_counter() < deadline:
            self.application.processEvents()
            time.sleep(0.01)
        self.assertEqual(saved_indexes, [4])

    def test_rapid_direction_reversals_stay_under_100ms(self) -> None:
        self.window.clear_queued_display_requests()
        self.window.visible_display_pool.waitForDone(1000)
        self.window.warm_display_pool.waitForDone(1000)
        self.window.display_pixmap_cache.clear()
        self.window.resize_quality_timer.stop()
        self.window.fast_resize_render = False
        original_decode = viewer_module.decode_scaled_display_image
        durations = []

        def slow_decode(*args, **kwargs):
            time.sleep(0.2)
            return original_decode(*args, **kwargs)

        with patch("raiv_app.viewer.decode_scaled_display_image", side_effect=slow_decode):
            for iteration in range(40):
                started = time.perf_counter()
                self.window.move_by(2 if iteration % 2 == 0 else -2)
                durations.append(time.perf_counter() - started)

        self.assertLess(max(durations), 0.1)


if __name__ == "__main__":
    unittest.main()
