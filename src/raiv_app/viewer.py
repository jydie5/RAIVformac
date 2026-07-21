from __future__ import annotations

import shutil
import sys
import threading
import time
from argparse import ArgumentParser, Namespace
from collections import OrderedDict
from collections.abc import Callable, Sequence
from hashlib import sha1
from pathlib import Path

from PIL import Image, ImageOps
from raiv_app.archive_utils import discover_samples, load_sample_pages
from raiv_app.engine_utils import realcugan_executable, run_realcugan

try:
    from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
    PYSIDE_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:
    QEvent = QObject = QTimer = Qt = Signal = QPixmap = QApplication = QCheckBox = QComboBox = QFormLayout = None
    QHBoxLayout = QLabel = QMessageBox = QProgressBar = QPushButton = QSpinBox = QVBoxLayout = QWidget = QFileDialog = None
    QMainWindow = object
    PYSIDE_IMPORT_ERROR = exc


ROOT_DIR = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT_DIR / "sample"


def default_upscale_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Caches" / "RAIV" / "upscale"
    return ROOT_DIR / "test" / "output" / "upscale"


DEFAULT_UPSCALE_DIR = default_upscale_dir()
DISPLAY_CACHE_DIR = DEFAULT_UPSCALE_DIR / "display_cache"
DEFAULT_PREVIOUS_PREFETCH_COUNT = 6
MODEL_NOISE_OPTIONS = {
    "models-pro": ["3"],
    "models-se": ["-1", "0", "1", "2", "3"],
}

PRESETS = [
    {
        "name": "原画",
        "mode": "original",
        "model": "models-se",
        "noise": "0",
        "description": "補正せず最速で表示します。画質比較の基準です。",
    },
    {
        "name": "標準補正",
        "mode": "corrected",
        "model": "models-se",
        "noise": "0",
        "description": "se/noise 0。線とトーンを自然に整えます。",
    },
    {
        "name": "補正強め",
        "mode": "corrected",
        "model": "models-se",
        "noise": "3",
        "description": "se/noise 3。古いスキャンの荒れを強く抑えます。",
    },
    {
        "name": "軽量",
        "mode": "corrected",
        "model": "models-se",
        "noise": "0",
        "description": "se/noise 0。軽めの設定で先読み速度を優先します。",
    },
]

NOISE_LABELS = {
    "-1": "弱め",
    "0": "自然",
    "1": "標準",
    "2": "やや強め",
    "3": "強め",
}


def navigation_help_text(reading_direction: str) -> str:
    if reading_direction == "rtl":
        return "Left/Space: next | Right: previous | Shift+Left/Right: +/-1p | F: fullscreen | P: panel | ?: help"
    return "Right/Space: next | Left: previous | Shift+Right/Left: +/-1p | F: fullscreen | P: panel | ?: help"


def viewer_shortcuts_text(reading_direction: str) -> str:
    if reading_direction == "rtl":
        next_keys = "← / ↓ / Space"
        previous_keys = "→ / ↑ / Backspace"
        one_page_next = "Shift+← / Shift+↓ / E"
        one_page_previous = "Shift+→ / Shift+↑ / Q"
    else:
        next_keys = "→ / ↓ / Space"
        previous_keys = "← / ↑ / Backspace"
        one_page_next = "Shift+→ / Shift+↓ / E"
        one_page_previous = "Shift+← / Shift+↑ / Q"
    return "\n".join(
        [
            f"{next_keys}: 次へ",
            f"{previous_keys}: 前へ",
            f"{one_page_next}: 1ページ進める",
            f"{one_page_previous}: 1ページ戻す",
            "F: 全画面表示/解除",
            "P: 右設定パネル表示/非表示",
            "B: しおり追加",
            "画像クリック: ページ情報を表示/非表示",
            "Esc: 全画面解除 / 本棚へ戻る",
            "?: このヘルプを表示",
        ]
    )


def compact_shortcuts_text(reading_direction: str) -> str:
    if reading_direction == "rtl":
        return "← 次 / → 前 / Shift+← 1p進む / Shift+→ 1p戻す / P 設定 / ? ヘルプ"
    return "→ 次 / ← 前 / Shift+→ 1p進む / Shift+← 1p戻す / P 設定 / ? ヘルプ"


def page_progress_text(visible_indexes: list[int], total_pages: int) -> str:
    if not visible_indexes or total_pages <= 0:
        return "0/0"
    if len(visible_indexes) == 1:
        return f"{visible_indexes[0] + 1}/{total_pages}"
    return f"{visible_indexes[0] + 1}-{visible_indexes[-1] + 1}/{total_pages}"


def visible_file_names(pages: Sequence[Path], visible_indexes: list[int]) -> str:
    names = [pages[index].name for index in visible_indexes if 0 <= index < len(pages)]
    return " / ".join(names)


def should_handle_global_shortcut(active_modal_widget: object | None) -> bool:
    return active_modal_widget is None


def standard_spread_index(index: int, cover_single: bool) -> int:
    if cover_single and index > 0 and index % 2 == 0:
        return max(1, index - 1)
    return index


def default_spread_order(reading_direction: str) -> str:
    return "rtl" if reading_direction == "rtl" else "ltr"


def output_cache_source_key(source: Path) -> str:
    try:
        stat = source.stat()
        identity = f"{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        identity = str(source.expanduser())
    return sha1(identity.encode("utf-8")).hexdigest()[:16]


def prefetch_window_indexes(
    current_index: int,
    total_pages: int,
    visible_indexes: Sequence[int],
    ahead_count: int,
    previous_count: int = DEFAULT_PREVIOUS_PREFETCH_COUNT,
) -> list[int]:
    indexes = [index for index in visible_indexes if 0 <= index < total_pages]
    start = current_index + len(indexes)
    for index in range(start, min(total_pages, start + max(0, ahead_count))):
        indexes.append(index)
    for index in range(current_index - 1, max(-1, current_index - previous_count - 1), -1):
        indexes.append(index)
    return list(dict.fromkeys(indexes))


def missing_processed_indexes(
    processed_pages: Sequence[Path | None],
    visible_indexes: Sequence[int],
    skipped_indexes: Sequence[int] = (),
) -> list[int]:
    skipped = set(skipped_indexes)
    return [
        index
        for index in visible_indexes
        if 0 <= index < len(processed_pages) and index not in skipped and processed_pages[index] is None
    ]


class WorkerSignals(QObject):
    upscale_done = Signal(int, object, object, int, object, bool)


class SpreadWindow(QMainWindow):
    def __init__(
        self,
        pages: Sequence[Path],
        title: str,
        cleanup_dir: Path | None = None,
        processed_pages: list[Path | None] | None = None,
        reading_direction: str = "rtl",
        spread_order: str = "rtl",
        cover_single: bool = True,
        auto_prefetch: bool = True,
        prefetch_count: int = 6,
        upscale_height_threshold: int = 2234,
        page_changed_callback: Callable[[int], None] | None = None,
        bookmark_callback: Callable[[int], None] | None = None,
        next_book_callback: Callable[[], None] | None = None,
        next_book_label: str | None = None,
        close_callback: Callable[["SpreadWindow"], None] | None = None,
        embedded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.pages = pages
        self.processed_pages = processed_pages or [None] * len(pages)
        self.reading_direction = reading_direction
        self.spread_order = spread_order
        self.cover_single = cover_single
        self.cleanup_dir = cleanup_dir
        self.auto_prefetch_default = auto_prefetch
        self.prefetch_count_default = prefetch_count
        self.prefetch_enabled = auto_prefetch
        self.upscale_height_threshold_default = upscale_height_threshold
        self.page_changed_callback = page_changed_callback
        self.bookmark_callback = bookmark_callback
        self.next_book_callback = next_book_callback
        self.next_book_label = next_book_label
        self.close_callback = close_callback
        self.embedded = embedded
        self.index = 0
        self.is_fullscreen = False
        self.upscale_running = False
        self.prefetch_running = False
        self.prefetch_suspended = False
        self.processing_generation = 0
        self.current_quality_preset = "標準補正"
        self.controls_visible = True
        self.reading_info_visible = False
        self.image_size_cache: dict[int, tuple[int, int]] = {}
        self.display_pixmap_cache: OrderedDict[tuple[str, int, int, int, int, int], QPixmap] = OrderedDict()
        self.display_pixmap_cache_limit = 32
        self.fast_resize_render = False
        self.resize_quality_delay_ms = 180
        self.resize_quality_timer = QTimer(self)
        self.resize_quality_timer.setSingleShot(True)
        self.resize_quality_timer.timeout.connect(self.finish_resize_quality_render)
        self.signals = WorkerSignals()
        self.signals.upscale_done.connect(self.on_upscale_done)

        direction_label = "right-bound" if self.is_right_bound() else "left-bound"
        self.setWindowTitle(f"RAIV spread smoke: {title} ({direction_label}, spread-{self.spread_order})")
        self.setStyleSheet(
            "QMainWindow, QWidget { background: #111111; color: #dddddd; font-size: 14px; } "
            "QLabel#pagePane { border: 1px solid #333333; } "
            "QWidget#controls { background: #181818; border-left: 1px solid #333333; } "
            "QPushButton, QComboBox, QSpinBox { min-height: 30px; font-size: 14px; } "
            "QCheckBox { min-height: 28px; } "
            "QStatusBar { font-size: 12px; }"
        )

        root = QWidget(self)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)
        image_host = QWidget(root)
        self.image_host = image_host
        image_host_layout = QVBoxLayout(image_host)
        image_host_layout.setContentsMargins(0, 0, 0, 0)
        image_host_layout.setSpacing(8)
        self.next_book_banner = QPushButton("次の巻へ", image_host)
        self.next_book_banner.setToolTip("読了後に本棚順の次の巻を開きます")
        self.next_book_banner.clicked.connect(self.open_next_book)
        self.next_book_banner.setStyleSheet(
            "QPushButton {"
            " background: rgba(12, 12, 12, 165);"
            " border: 1px solid rgba(255, 255, 255, 58);"
            " border-radius: 8px;"
            " color: #ffffff;"
            " font-size: 17px;"
            " font-weight: bold;"
            " padding: 12px 18px;"
            "}"
            "QPushButton:hover { background: rgba(36, 36, 36, 190); }"
            "QPushButton:pressed { background: rgba(60, 60, 60, 210); }"
        )
        self.next_book_banner.setVisible(False)
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.left = QLabel(alignment=Qt.AlignCenter)
        self.right = QLabel(alignment=Qt.AlignCenter)
        self.left.setObjectName("pagePane")
        self.right.setObjectName("pagePane")
        self.left.setMinimumSize(320, 320)
        self.right.setMinimumSize(320, 320)
        layout.addWidget(self.left, 1)
        layout.addWidget(self.right, 1)
        self.left.installEventFilter(self)
        self.right.installEventFilter(self)
        image_host_layout.addLayout(layout, 1)
        self.reading_info_panel = QWidget(image_host)
        reading_info_layout = QVBoxLayout(self.reading_info_panel)
        reading_info_layout.setContentsMargins(10, 8, 10, 8)
        reading_info_layout.setSpacing(6)
        self.reading_info_label = QLabel("", self.reading_info_panel)
        self.reading_info_label.setWordWrap(True)
        self.reading_info_label.setStyleSheet("font-size: 15px; color: #ffffff; background: transparent;")
        self.reading_progress = QProgressBar(self.reading_info_panel)
        self.reading_progress.setTextVisible(True)
        self.reading_progress.setStyleSheet(
            "QProgressBar {"
            " background: rgba(255, 255, 255, 36);"
            " border: 1px solid rgba(255, 255, 255, 58);"
            " border-radius: 5px;"
            " color: rgba(255, 255, 255, 210);"
            " text-align: center;"
            " height: 10px;"
            "}"
            "QProgressBar::chunk {"
            " background: rgba(255, 255, 255, 178);"
            " border-radius: 5px;"
            "}"
        )
        reading_info_layout.addWidget(self.reading_info_label)
        reading_info_layout.addWidget(self.reading_progress)
        self.reading_info_panel.setStyleSheet(
            "background: rgba(12, 12, 12, 150);"
            "border: 1px solid rgba(255, 255, 255, 42);"
            "border-radius: 8px;"
        )
        self.reading_info_panel.setVisible(False)
        root_layout.addWidget(image_host, 1)
        self.controls_panel = self.build_controls()
        root_layout.addWidget(self.controls_panel, 0)
        self.setCentralWidget(root)
        QApplication.instance().installEventFilter(self)

        self.statusBar().showMessage(self.help_text())
        self.resize(1400, 900)
        self.position_reading_info_overlay()
        self.render_spread()

    def build_controls(self) -> QWidget:
        controls = QWidget(self)
        controls.setObjectName("controls")
        controls.setFixedWidth(350)
        layout = QVBoxLayout(controls)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("読書設定", controls)
        title.setStyleSheet("font-weight: bold; font-size: 18px;")
        header.addWidget(title, 1)
        help_button = QPushButton("?", controls)
        help_button.setFixedWidth(34)
        help_button.setToolTip("ショートカットを表示")
        help_button.clicked.connect(self.show_shortcuts_help)
        header.addWidget(help_button)
        layout.addLayout(header)

        self.quality_state_card = QWidget(controls)
        self.quality_state_card.setStyleSheet(
            "background: #202020; border: 1px solid #3a3a3a; border-radius: 6px;"
        )
        state_layout = QVBoxLayout(self.quality_state_card)
        state_layout.setContentsMargins(10, 8, 10, 8)
        state_layout.setSpacing(4)
        self.quality_mode_label = QLabel("画質: 標準補正", self.quality_state_card)
        self.quality_engine_label = QLabel("エンジン: Real-CUGAN / models-se", self.quality_state_card)
        self.quality_correction_label = QLabel("状態: 原画表示中", self.quality_state_card)
        self.quality_prefetch_label = QLabel("先読み: 待機中", self.quality_state_card)
        for label in (
            self.quality_mode_label,
            self.quality_engine_label,
            self.quality_correction_label,
            self.quality_prefetch_label,
        ):
            label.setWordWrap(True)
            label.setStyleSheet("background: transparent; color: #eeeeee; font-size: 13px;")
            state_layout.addWidget(label)
        layout.addWidget(self.quality_state_card)

        back_button = QPushButton("本棚へ戻る", controls)
        back_button.clicked.connect(self.close)
        layout.addWidget(back_button)
        layout.addWidget(self.help_label("読書画面を閉じて本棚に戻ります。"))

        self.next_book_button = QPushButton("次の巻へ", controls)
        self.next_book_button.setToolTip("読了後に本棚順の次の巻を開きます")
        self.next_book_button.clicked.connect(self.open_next_book)
        layout.addWidget(self.next_book_button)
        self.next_book_hint = self.help_label("")
        layout.addWidget(self.next_book_hint)
        self.update_next_book_action()

        preset_title = QLabel("画質モード", controls)
        preset_title.setStyleSheet("font-weight: bold; font-size: 15px; margin-top: 4px;")
        layout.addWidget(preset_title)
        for preset in PRESETS:
            button = QPushButton(preset["name"], controls)
            button.clicked.connect(lambda _checked=False, item=preset: self.apply_preset(item))
            layout.addWidget(button)
            layout.addWidget(self.help_label(preset["description"]))
        self.preset_status = QLabel("標準補正を基準に、必要な時だけ強めや原画へ切り替えます。", controls)
        self.preset_status.setWordWrap(True)
        self.preset_status.setStyleSheet("color: #dddddd; font-size: 13px;")
        layout.addWidget(self.preset_status)

        spread_title = QLabel("見開き", controls)
        spread_title.setStyleSheet("font-weight: bold; font-size: 15px; margin-top: 8px;")
        layout.addWidget(spread_title)
        spread_buttons = QHBoxLayout()
        shift_back_button = QPushButton("-1", controls)
        shift_back_button.clicked.connect(lambda: self.move_by(-1))
        spread_buttons.addWidget(shift_back_button)
        shift_forward_button = QPushButton("+1", controls)
        shift_forward_button.clicked.connect(lambda: self.move_by(1))
        spread_buttons.addWidget(shift_forward_button)
        swap_button = QPushButton("左右入替", controls)
        swap_button.clicked.connect(self.swap_spread_order)
        spread_buttons.addWidget(swap_button)
        layout.addLayout(spread_buttons)
        reset_button = QPushButton("標準見開きに戻す", controls)
        reset_button.clicked.connect(self.reset_spread_alignment)
        layout.addWidget(reset_button)
        self.spread_status = QLabel("", controls)
        self.spread_status.setWordWrap(True)
        self.spread_status.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        layout.addWidget(self.spread_status)
        self.update_spread_status()

        self.advanced_check = QCheckBox("詳細パラメータを表示", controls)
        self.advanced_check.stateChanged.connect(self.toggle_advanced_panel)
        layout.addWidget(self.advanced_check)

        self.advanced_panel = QWidget(controls)
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        form = QFormLayout()
        self.scale_spin = QSpinBox(controls)
        self.scale_spin.setRange(1, 4)
        self.scale_spin.setValue(2)
        self.scale_spin.valueChanged.connect(lambda _value: self.on_processing_settings_changed())
        form.addRow("倍率", self.scale_spin)
        form.addRow("", self.help_label("拡大倍率。漫画確認はまず2倍が扱いやすいです。"))

        self.noise_combo = QComboBox(controls)
        self.noise_combo.addItems(MODEL_NOISE_OPTIONS["models-se"])
        self.noise_combo.setCurrentText("0")
        self.noise_combo.currentTextChanged.connect(lambda _value: self.on_processing_settings_changed())
        form.addRow("ノイズ除去", self.noise_combo)
        form.addRow("", self.help_label("0:自然 / 1:標準 / 3:強め。強いほど線が変わりやすいです。"))

        self.tile_spin = QSpinBox(controls)
        self.tile_spin.setRange(0, 4096)
        self.tile_spin.setSingleStep(32)
        self.tile_spin.setValue(0)
        self.tile_spin.valueChanged.connect(lambda _value: self.on_processing_settings_changed())
        form.addRow("タイル", self.tile_spin)
        form.addRow("", self.help_label("処理タイルサイズ。0は自動、重い時だけ調整します。"))

        self.threshold_spin = QSpinBox(controls)
        self.threshold_spin.setRange(1, 12000)
        self.threshold_spin.setValue(self.upscale_height_threshold_default)
        self.threshold_spin.valueChanged.connect(lambda _value: self.on_processing_settings_changed())
        form.addRow("補正スキップ縦px", self.threshold_spin)
        form.addRow("", self.help_label("この縦px以上は補正せず原画表示。今のMacは2234候補です。"))

        self.model_combo = QComboBox(controls)
        self.model_combo.addItems(["models-pro", "models-se"])
        self.model_combo.setCurrentText("models-se")
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        form.addRow("モデル", self.model_combo)
        form.addRow("", self.help_label("seは標準・軽量寄り。proは高品質候補ですが現状は実験扱いです。"))

        self.tta_check = QCheckBox("TTA", controls)
        self.tta_check.stateChanged.connect(lambda _state: self.on_processing_settings_changed())
        form.addRow("", self.tta_check)
        form.addRow("", self.help_label("反転推論で精度を上げます。かなり遅くなります。"))
        advanced_layout.addLayout(form)
        layout.addWidget(self.advanced_panel)
        self.advanced_panel.setVisible(False)

        self.apply_button = QPushButton("現在の見開きを補正", controls)
        self.apply_button.clicked.connect(self.process_current_spread)
        layout.addWidget(self.apply_button)
        layout.addWidget(self.help_label("現在表示中の見開きだけ処理して表示を差し替えます。"))

        self.original_check = QCheckBox("原画を表示（OFFで補正版）", controls)
        self.original_check.stateChanged.connect(lambda _state: self.on_original_compare_changed())
        layout.addWidget(self.original_check)
        layout.addWidget(self.help_label("チェックで原画、解除で補正版へ即時に切り替えて見比べます。"))

        self.parameter_status = QLabel("待機中", controls)
        self.parameter_status.setWordWrap(True)
        self.parameter_status.setMinimumHeight(72)
        self.parameter_status.setMaximumHeight(108)
        layout.addWidget(self.parameter_status)
        layout.addStretch(1)
        self.on_model_changed(self.model_combo.currentText(), announce=False)
        self.update_quality_state()
        return controls

    def toggle_advanced_panel(self) -> None:
        self.advanced_panel.setVisible(self.advanced_check.isChecked())

    def apply_preset(self, preset: dict[str, str]) -> None:
        self.scale_spin.setValue(2)
        self.tile_spin.setValue(0)
        self.model_combo.setCurrentText(preset["model"])
        self.on_model_changed(preset["model"], announce=False)
        self.noise_combo.setCurrentText(preset["noise"])
        self.tta_check.setChecked(False)
        if hasattr(self, "original_check"):
            self.original_check.setChecked(preset.get("mode") == "original")
        self.current_quality_preset = preset["name"]
        self.preset_status.setText(preset["description"])
        if preset.get("mode") == "original":
            self.parameter_status.setText("原画表示に切り替えました。補正処理は行いません。")
        else:
            self.parameter_status.setText(f"{preset['name']}に変更しました。現在の見開きを再補正できます。")
            self.request_prefetch()
        self.update_quality_state()
        self.render_spread()

    def on_original_compare_changed(self) -> None:
        visible_indexes = self.visible_page_indexes()
        self.display_pixmap_cache.clear()
        self.left.clear()
        self.right.clear()
        if self.original_check.isChecked():
            self.current_quality_preset = "原画"
            if visible_indexes and all(self.should_skip_upscale(index) for index in visible_indexes):
                self.parameter_status.setText("この見開きは高解像度のため補正対象外です。原画と補正版は同じ表示です。")
            elif self.visible_missing_correction_indexes(visible_indexes):
                self.parameter_status.setText("原画を表示中です。補正版がまだないページは、チェック解除後に生成します。")
            else:
                self.parameter_status.setText("原画を表示中です。チェックを外すと補正版に戻ります。")
        elif self.current_quality_preset == "原画":
            self.current_quality_preset = "標準補正"
        if not self.original_check.isChecked():
            if visible_indexes and all(self.should_skip_upscale(index) for index in visible_indexes):
                self.parameter_status.setText("この見開きは高解像度のため補正対象外です。原画を表示します。")
            elif self.visible_missing_correction_indexes(visible_indexes):
                self.parameter_status.setText("この見開きはまだ補正待ちです。現在ページを優先して生成します。")
                self.request_prefetch()
            else:
                self.parameter_status.setText("補正版を表示中です。チェックすると原画へ切り替わります。")
        self.update_quality_state()
        self.render_spread(high_quality=True)
        self.left.repaint()
        self.right.repaint()

    def stop_prefetch(self, message: str) -> None:
        self.prefetch_suspended = True
        if hasattr(self, "parameter_status"):
            self.parameter_status.setText("待機中")
        self.statusBar().showMessage(message, 6000)
        self.update_quality_state()

    def on_model_changed(self, model: str, announce: bool = True) -> None:
        options = MODEL_NOISE_OPTIONS.get(model, ["0"])
        current_noise = self.noise_combo.currentText()
        selected_noise = current_noise if current_noise in options else "0" if "0" in options else options[0]
        self.noise_combo.blockSignals(True)
        self.noise_combo.clear()
        self.noise_combo.addItems(options)
        self.noise_combo.setCurrentText(selected_noise)
        self.noise_combo.blockSignals(False)
        if model == "models-pro" and self.scale_spin.value() < 3:
            self.scale_spin.setValue(3)
        if announce and current_noise and current_noise not in options and hasattr(self, "parameter_status"):
            self.parameter_status.setText(f"{model} では noise {current_noise} は使えません。{selected_noise} に変更しました。")
        if announce:
            self.on_processing_settings_changed()

    def on_processing_settings_changed(self) -> None:
        self.processing_generation += 1
        self.processed_pages = [None] * len(self.pages)
        self.display_pixmap_cache.clear()
        if bool(getattr(self, "original_check", None) and self.original_check.isChecked()):
            self.current_quality_preset = "原画"
        elif hasattr(self, "model_combo"):
            self.current_quality_preset = "カスタム補正"
        if hasattr(self, "parameter_status") and not self.upscale_running and not self.prefetch_running:
            self.parameter_status.setText("設定を変更しました。古い先読み結果は使いません。")
        if hasattr(self, "quality_mode_label"):
            self.update_quality_state()

    def help_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        return label

    def help_text(self) -> str:
        return navigation_help_text(self.reading_direction)

    def current_quality_mode(self) -> str:
        if bool(getattr(self, "original_check", None) and self.original_check.isChecked()):
            return "原画"
        return self.current_quality_preset

    def current_noise_label(self) -> str:
        if not hasattr(self, "noise_combo"):
            return "自然"
        noise = self.noise_combo.currentText()
        return f"{noise} ({NOISE_LABELS.get(noise, '調整')})"

    def correction_state_text(self, visible_indexes: list[int] | None = None) -> str:
        if bool(getattr(self, "original_check", None) and self.original_check.isChecked()):
            return "原画表示中"
        if not visible_indexes:
            visible_indexes = self.visible_page_indexes()
        if not visible_indexes:
            return "ページなし"
        if any(self.should_skip_upscale(index) for index in visible_indexes):
            return "高解像度のため補正スキップ"
        missing = self.visible_missing_correction_indexes(visible_indexes)
        if not missing:
            return "補正済み"
        if self.upscale_running:
            return "現在の見開きを補正中"
        if self.prefetch_running:
            return f"先読み補正中 / 未処理 p.{missing[0] + 1}"
        return f"原画表示中・補正待ち p.{missing[0] + 1}"

    def prefetch_state_text(self) -> str:
        if not self.prefetch_enabled:
            return "オフ / 0ページ"
        if self.prefetch_suspended:
            return "停止中 / 原画表示継続"
        if self.prefetch_running:
            return f"生成中 / 自動{self.prefetch_count_default}ページ先"
        return f"自動 / {self.prefetch_count_default}ページ先"

    def update_quality_state(self) -> None:
        if not hasattr(self, "quality_mode_label"):
            return
        model = self.model_combo.currentText() if hasattr(self, "model_combo") else "models-se"
        scale = self.scale_spin.value() if hasattr(self, "scale_spin") else 2
        threshold = self.threshold_spin.value() if hasattr(self, "threshold_spin") else self.upscale_height_threshold_default
        self.quality_mode_label.setText(f"画質: {self.current_quality_mode()}")
        self.quality_engine_label.setText(f"エンジン: Real-CUGAN / {model}")
        self.quality_correction_label.setText(
            f"状態: {self.correction_state_text()} / {scale}倍 / noise {self.current_noise_label()}"
        )
        self.quality_prefetch_label.setText(
            f"先読み: {self.prefetch_state_text()} / 縦{threshold}px以上は原画"
        )

    def is_right_bound(self) -> bool:
        return self.reading_direction == "rtl"

    def is_spread_reversed(self) -> bool:
        return self.spread_order == "rtl"

    def eventFilter(self, watched, event) -> bool:
        if watched in {getattr(self, "left", None), getattr(self, "right", None)} and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self.toggle_reading_info()
                return True
        if event.type() == QEvent.KeyPress and not should_handle_global_shortcut(QApplication.activeModalWidget()):
            return False
        if event.type() == QEvent.KeyPress and self.handle_navigation_event(event):
            return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.position_reading_info_overlay()
        self.position_next_book_overlay()
        self.fast_resize_render = True
        self.render_spread(high_quality=False)
        self.resize_quality_timer.start(self.resize_quality_delay_ms)

    def finish_resize_quality_render(self) -> None:
        self.fast_resize_render = False
        self.render_spread(high_quality=True)

    def keyPressEvent(self, event) -> None:
        if self.handle_navigation_event(event):
            return
        super().keyPressEvent(event)

    def handle_navigation_event(self, event) -> bool:
        return self.handle_navigation_key(event.key(), event.modifiers())

    def handle_navigation_key(self, key: int, modifiers=Qt.NoModifier) -> bool:
        next_key = Qt.Key_Left if self.is_right_bound() else Qt.Key_Right
        previous_key = Qt.Key_Right if self.is_right_bound() else Qt.Key_Left
        if modifiers & Qt.ShiftModifier:
            if key in {next_key, Qt.Key_Down}:
                self.move_by(1)
                return True
            if key in {previous_key, Qt.Key_Up}:
                self.move_by(-1)
                return True
        if key in {next_key, Qt.Key_Down, Qt.Key_Space}:
            self.move_by(2)
            return True
        elif key in {previous_key, Qt.Key_Up, Qt.Key_Backspace}:
            self.move_by(-2)
            return True
        elif key == Qt.Key_E:
            self.move_by(1)
            return True
        elif key == Qt.Key_Q:
            self.move_by(-1)
            return True
        elif key == Qt.Key_F:
            self.toggle_fullscreen()
            return True
        elif key == Qt.Key_P:
            self.toggle_controls()
            return True
        elif key == Qt.Key_B:
            self.add_bookmark()
            return True
        elif key == Qt.Key_Question:
            self.show_shortcuts_help()
            return True
        elif key == Qt.Key_Escape:
            if self.is_fullscreen:
                self.toggle_fullscreen()
            else:
                self.close()
            return True
        return False

    def move_by(self, step: int) -> None:
        if not self.pages:
            return
        previous_index = self.index
        if self.cover_single and step == 2 and self.index == 0:
            next_index = 1
        elif self.cover_single and step == -2 and self.index <= 1:
            next_index = 0
        else:
            next_index = self.index + step
        self.index = max(0, min(len(self.pages) - 1, next_index))
        if self.index != previous_index:
            self.invalidate_prefetch_for_navigation()
        self.render_spread()
        self.notify_page_changed()
        self.update_spread_status()
        self.update_next_book_action()

    def invalidate_prefetch_for_navigation(self) -> None:
        if not self.prefetch_running:
            return
        self.processing_generation += 1
        if hasattr(self, "parameter_status"):
            self.parameter_status.setText("ページ移動に合わせて先読みを組み直しています。")

    def notify_page_changed(self) -> None:
        if self.page_changed_callback is not None:
            self.page_changed_callback(self.index)

    def add_bookmark(self) -> None:
        if self.bookmark_callback is not None:
            self.bookmark_callback(self.index)
            self.statusBar().showMessage(f"Bookmark added at p.{self.index + 1}    {self.help_text()}")

    def show_shortcuts_help(self) -> None:
        QMessageBox.information(self, "ショートカット", viewer_shortcuts_text(self.reading_direction))
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    def toggle_fullscreen(self) -> None:
        self.is_fullscreen = not self.is_fullscreen
        fullscreen_target = self.window() if self.embedded else self
        if self.is_fullscreen:
            fullscreen_target.showFullScreen()
        else:
            fullscreen_target.showNormal()

    def toggle_controls(self) -> None:
        self.controls_visible = not self.controls_visible
        self.controls_panel.setVisible(self.controls_visible)
        self.render_spread()

    def swap_spread_order(self) -> None:
        self.spread_order = "rtl" if self.spread_order == "ltr" else "ltr"
        self.render_spread()
        self.update_spread_status()
        self.notify_page_changed()

    def reset_spread_alignment(self) -> None:
        if not self.pages:
            return
        self.index = standard_spread_index(self.index, self.cover_single)
        self.spread_order = default_spread_order(self.reading_direction)
        self.render_spread()
        self.update_spread_status()
        self.notify_page_changed()

    def update_spread_status(self) -> None:
        if not hasattr(self, "spread_status"):
            return
        direction = "右綴じ" if self.is_right_bound() else "左綴じ"
        order = "左→右" if self.spread_order == "ltr" else "右→左"
        phase = "表紙単独" if self.cover_single else "通常"
        self.spread_status.setText(f"{direction} / 表示順 {order} / {phase}")

    def render_spread(self, high_quality: bool | None = None) -> None:
        if not isinstance(high_quality, bool):
            high_quality = not self.fast_resize_render
        self.load_cached_outputs(self.visible_and_prefetch_indexes())
        visible_indexes = self.visible_page_indexes()
        if self.cover_single and self.index == 0:
            if self.is_right_bound():
                self.render_label(self.left, -1, high_quality=high_quality)
                self.render_label(self.right, 0, high_quality=high_quality)
            else:
                self.render_label(self.left, 0, high_quality=high_quality)
                self.render_label(self.right, -1, high_quality=high_quality)
        elif self.index + 1 >= len(self.pages):
            if self.is_right_bound():
                self.render_label(self.left, -1, high_quality=high_quality)
                self.render_label(self.right, self.index, high_quality=high_quality)
            else:
                self.render_label(self.left, self.index, high_quality=high_quality)
                self.render_label(self.right, -1, high_quality=high_quality)
        elif self.is_spread_reversed():
            self.render_label(self.left, self.index + 1, high_quality=high_quality)
            self.render_label(self.right, self.index, high_quality=high_quality)
        else:
            self.render_label(self.left, self.index, high_quality=high_quality)
            self.render_label(self.right, self.index + 1, high_quality=high_quality)
        page_text = page_progress_text(visible_indexes, len(self.pages))
        processed_count = sum(1 for path in self.processed_pages if path is not None)
        file_text = visible_file_names(self.pages, visible_indexes)
        self.statusBar().showMessage(
            f"{page_text}    {file_text}    processed {processed_count}/{len(self.pages)}    {self.help_text()}"
        )
        self.update_quality_state()
        self.update_reading_info()
        if high_quality:
            self.warm_display_pixmap_cache(self.visible_and_prefetch_indexes())
            self.prune_revolving_correction_cache()
            self.request_prefetch()
        self.update_next_book_action()

    def render_label(self, label: QLabel, index: int, high_quality: bool = True) -> None:
        if index < 0 or index >= len(self.pages):
            label.setText("")
            label.setPixmap(QPixmap())
            return
        display_path = self.display_path_for_index(index)
        scaled = self.scaled_pixmap(display_path, label.size(), high_quality=high_quality)
        if scaled.isNull():
            label.setText(f"Failed to load:\n{display_path.name}")
            label.setPixmap(QPixmap())
            return
        label.setText("")
        label.setPixmap(scaled)

    def display_path_for_index(self, index: int) -> Path:
        show_original = bool(getattr(self, "original_check", None) and self.original_check.isChecked())
        display_path = self.pages[index] if show_original else self.processed_pages[index] or self.pages[index]
        return self.display_safe_path(index, display_path)

    def scaled_pixmap(self, display_path: Path, target, high_quality: bool = True) -> QPixmap:
        if target.width() <= 0 or target.height() <= 0:
            return QPixmap()
        try:
            stat = display_path.stat()
            key = (
                str(display_path),
                stat.st_size,
                stat.st_mtime_ns,
                target.width(),
                target.height(),
                1 if high_quality else 0,
            )
        except OSError:
            return QPixmap()
        cached = self.display_pixmap_cache.get(key)
        if cached is not None:
            self.display_pixmap_cache.move_to_end(key)
            return cached
        pixmap = QPixmap(str(display_path))
        if pixmap.isNull():
            return pixmap
        transform_mode = Qt.SmoothTransformation if high_quality else Qt.FastTransformation
        scaled = pixmap.scaled(target, Qt.KeepAspectRatio, transform_mode)
        self.display_pixmap_cache[key] = scaled
        while len(self.display_pixmap_cache) > self.display_pixmap_cache_limit:
            self.display_pixmap_cache.popitem(last=False)
        return scaled

    def warm_display_pixmap_cache(self, indexes: list[int]) -> None:
        if not indexes:
            return
        targets = [self.left.size(), self.right.size()]
        for index in indexes:
            if index < 0 or index >= len(self.pages):
                continue
            display_path = self.display_path_for_index(index)
            for target in targets:
                self.scaled_pixmap(display_path, target)

    def display_safe_path(self, index: int, display_path: Path) -> Path:
        if display_path == self.pages[index]:
            return display_path
        try:
            stat = display_path.stat()
            key = sha1(f"{display_path}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")).hexdigest()[:16]
            cached_path = DISPLAY_CACHE_DIR / f"{key}.png"
            if cached_path.exists():
                return cached_path
            DISPLAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with Image.open(display_path) as image:
                ImageOps.grayscale(image).save(cached_path)
            return cached_path
        except Exception:
            return display_path

    def visible_page_indexes(self) -> list[int]:
        if self.index < 0 or self.index >= len(self.pages):
            return []
        if self.cover_single and self.index == 0:
            return [0]
        if self.index + 1 >= len(self.pages):
            return [self.index]
        return [self.index, self.index + 1]

    def toggle_reading_info(self) -> None:
        self.reading_info_visible = not self.reading_info_visible
        self.position_reading_info_overlay()
        self.reading_info_panel.setVisible(self.reading_info_visible)
        self.reading_info_panel.raise_()
        self.update_reading_info()

    def position_reading_info_overlay(self) -> None:
        if not hasattr(self, "reading_info_panel") or not hasattr(self, "image_host"):
            return
        margin = 18
        height = 118
        width = max(240, self.image_host.width() - margin * 2)
        y = max(margin, self.image_host.height() - height - margin)
        self.reading_info_panel.setGeometry(margin, y, width, height)
        if self.reading_info_panel.isVisible():
            self.reading_info_panel.raise_()

    def position_next_book_overlay(self) -> None:
        if not hasattr(self, "next_book_banner") or not hasattr(self, "image_host"):
            return
        margin = 18
        self.next_book_banner.adjustSize()
        width = min(max(320, self.next_book_banner.sizeHint().width()), max(320, self.image_host.width() - margin * 2))
        height = max(54, self.next_book_banner.sizeHint().height())
        x = max(margin, (self.image_host.width() - width) // 2)
        y = max(margin, int(self.image_host.height() * 0.44) - height // 2)
        self.next_book_banner.setGeometry(x, y, width, height)
        if self.next_book_banner.isVisible():
            self.next_book_banner.raise_()

    def update_reading_info(self) -> None:
        if not hasattr(self, "reading_info_panel"):
            return
        visible_indexes = self.visible_page_indexes()
        page_text = page_progress_text(visible_indexes, len(self.pages))
        file_text = visible_file_names(self.pages, visible_indexes)
        quality_text = f"{self.current_quality_mode()} / {self.correction_state_text(visible_indexes)}"
        shortcut_text = compact_shortcuts_text(self.reading_direction)
        self.reading_info_label.setText(f"{page_text}    {quality_text}\n{file_text}\n{shortcut_text}")
        self.reading_progress.setRange(0, max(1, len(self.pages)))
        value = visible_indexes[-1] + 1 if visible_indexes else 0
        self.reading_progress.setValue(value)
        self.reading_progress.setFormat(page_text)

    def is_at_end(self) -> bool:
        visible_indexes = self.visible_page_indexes()
        return bool(visible_indexes and visible_indexes[-1] >= len(self.pages) - 1)

    def update_next_book_action(self) -> None:
        if not hasattr(self, "next_book_button"):
            return
        visible = self.next_book_callback is not None and self.is_at_end()
        self.next_book_button.setVisible(visible)
        self.next_book_hint.setVisible(visible)
        if not visible:
            if hasattr(self, "next_book_banner"):
                self.next_book_banner.setVisible(False)
            return
        label = self.next_book_label or "次の巻"
        self.next_book_button.setText(f"次の巻へ: {label}")
        self.next_book_hint.setText("最後まで読んだので、続きの巻を開けます。")
        if hasattr(self, "next_book_banner"):
            self.next_book_banner.setText(f"次の巻へ: {label}")
            self.position_next_book_overlay()
            self.next_book_banner.setVisible(True)
            self.next_book_banner.raise_()

    def open_next_book(self) -> None:
        if self.next_book_callback is not None:
            self.next_book_callback()

    def visible_and_prefetch_indexes(self) -> list[int]:
        return prefetch_window_indexes(
            self.index,
            len(self.pages),
            self.visible_page_indexes(),
            self.prefetch_count_default if self.prefetch_enabled else 0,
        )

    def visible_missing_correction_indexes(self, visible_indexes: list[int] | None = None) -> list[int]:
        if not visible_indexes:
            visible_indexes = self.visible_page_indexes()
        skipped = [index for index in visible_indexes if self.should_skip_upscale(index)]
        return missing_processed_indexes(self.processed_pages, visible_indexes, skipped)

    def image_size(self, index: int) -> tuple[int, int]:
        cached = self.image_size_cache.get(index)
        if cached is not None:
            return cached
        try:
            with Image.open(self.pages[index]) as image:
                size = image.size
        except Exception:
            size = (0, 0)
        self.image_size_cache[index] = size
        return size

    def should_skip_upscale(self, index: int) -> bool:
        width, height = self.image_size(index)
        return bool(width and height and height >= self.threshold_spin.value())

    def load_cached_outputs(self, indexes: list[int]) -> None:
        if not hasattr(self, "scale_spin") or bool(getattr(self, "original_check", None) and self.original_check.isChecked()):
            return
        for index in indexes:
            if index < 0 or index >= len(self.pages):
                continue
            output_path = self.current_output_path(index)
            if output_path.exists():
                self.processed_pages[index] = output_path

    def current_parameter_key(self) -> str:
        tta = "_tta" if self.tta_check.isChecked() else ""
        return (
            f"scale{self.scale_spin.value()}_noise{self.noise_combo.currentText()}_"
            f"tile{self.tile_spin.value()}_{self.model_combo.currentText()}{tta}"
        )

    def current_output_path(self, index: int) -> Path:
        source = self.pages[index]
        folder = DEFAULT_UPSCALE_DIR / "interactive" / self.current_parameter_key() / output_cache_source_key(source)
        return folder / f"{index + 1:04d}_{source.stem}_x{self.scale_spin.value()}.png"

    def prune_revolving_correction_cache(self) -> None:
        if not hasattr(self, "scale_spin"):
            return
        keep = set(self.visible_and_prefetch_indexes())
        for index, processed_path in enumerate(list(self.processed_pages)):
            if index in keep:
                continue
            self.processed_pages[index] = None
            output_path = self.current_output_path(index)
            try:
                if output_path.exists():
                    output_path.unlink()
                output_path.parent.rmdir()
            except OSError:
                pass

    def current_engine_settings(self) -> dict | None:
        model = self.model_combo.currentText()
        noise_text = self.noise_combo.currentText()
        if noise_text not in MODEL_NOISE_OPTIONS.get(model, []):
            self.parameter_status.setText(f"{model} では noise {noise_text} は使えません。")
            return None
        if model == "models-pro" and self.scale_spin.value() < 3:
            self.parameter_status.setText("models-pro は scale 3 / noise 3 の実験用に制限しています。")
            return None
        return {
            "scale": self.scale_spin.value(),
            "noise": int(noise_text),
            "tile": self.tile_spin.value(),
            "model": model,
            "tta": self.tta_check.isChecked(),
        }

    def process_current_spread(self) -> None:
        if self.upscale_running:
            return
        indexes = self.visible_page_indexes()
        if not indexes:
            return
        settings = self.current_engine_settings()
        if settings is None:
            return
        output_paths = {index: self.current_output_path(index) for index in indexes if not self.should_skip_upscale(index)}
        if not output_paths:
            self.parameter_status.setText("現在見開きは閾値以上のため原画表示です。")
            self.update_quality_state()
            return
        self.upscale_running = True
        self.apply_button.setEnabled(False)
        generation = self.processing_generation
        parameter_key = self.current_parameter_key()
        self.parameter_status.setText("現在の見開きを補正中...")
        self.update_quality_state()
        self.update_reading_info()
        threading.Thread(
            target=self._process_pages_worker,
            args=(indexes, output_paths, settings, generation, parameter_key, False),
            daemon=True,
        ).start()

    def request_prefetch(self) -> None:
        if self.prefetch_suspended:
            return
        if not self.prefetch_enabled:
            if hasattr(self, "quality_mode_label"):
                self.update_quality_state()
            return
        if bool(getattr(self, "original_check", None) and self.original_check.isChecked()):
            self.update_quality_state()
            return
        if self.prefetch_count_default <= 0:
            self.parameter_status.setText("先読みページ数が0のため、先読み補正は実行しません。")
            self.update_quality_state()
            return
        if realcugan_executable() is None:
            self.stop_prefetch("AI先読み補正を停止しました。Real-CUGANエンジンが見つかりません。")
            return
        QTimer.singleShot(0, self.start_prefetch)

    def start_prefetch(self) -> None:
        if self.prefetch_running or self.upscale_running or not self.prefetch_enabled:
            return
        if self.prefetch_suspended:
            return
        if bool(getattr(self, "original_check", None) and self.original_check.isChecked()):
            self.update_quality_state()
            return
        if self.prefetch_count_default <= 0:
            self.parameter_status.setText("先読みページ数が0のため、先読み補正は実行しません。")
            self.update_quality_state()
            return
        if realcugan_executable() is None:
            self.stop_prefetch("AI先読み補正を停止しました。Real-CUGANエンジンが見つかりません。")
            return
        settings = self.current_engine_settings()
        if settings is None:
            return
        indexes = [
            index
            for index in self.visible_and_prefetch_indexes()
            if not self.should_skip_upscale(index) and not self.current_output_path(index).exists()
        ]
        if not indexes:
            self.load_cached_outputs(self.visible_and_prefetch_indexes())
            self.update_quality_state()
            return
        self.prefetch_running = True
        skipped_count = len(self.visible_and_prefetch_indexes()) - len(indexes)
        suffix = f" / {skipped_count}ページはスキップ" if skipped_count else ""
        self.parameter_status.setText(f"先読み補正中: {len(indexes)}ページ{suffix}")
        self.update_quality_state()
        self.update_reading_info()
        output_paths = {index: self.current_output_path(index) for index in indexes}
        generation = self.processing_generation
        parameter_key = self.current_parameter_key()
        threading.Thread(
            target=self._process_pages_worker,
            args=(indexes, output_paths, settings, generation, parameter_key, True),
            daemon=True,
        ).start()

    def _process_pages_worker(
        self,
        indexes: list[int],
        output_paths: dict[int, Path],
        settings: dict,
        generation: int,
        parameter_key: str,
        is_prefetch: bool,
    ) -> None:
        started = time.perf_counter()
        errors: list[str] = []
        for index in output_paths:
            if is_prefetch and generation != self.processing_generation:
                break
            try:
                result = run_realcugan(
                    self.pages[index],
                    output_paths[index],
                    scale=settings["scale"],
                    noise=settings["noise"],
                    tile=settings["tile"],
                    model=settings["model"],
                    tta=settings["tta"],
                )
                if result.returncode != 0 or not result.output_exists:
                    errors.append(f"{self.pages[index].name}: code {result.returncode}")
            except Exception as exc:
                errors.append(f"{self.pages[index].name}: {exc}")
        self.signals.upscale_done.emit(
            round((time.perf_counter() - started) * 1000),
            output_paths,
            errors,
            generation,
            parameter_key,
            is_prefetch,
        )

    def on_upscale_done(
        self,
        elapsed_ms: int,
        output_paths: dict[int, Path],
        errors: list[str],
        generation: int,
        parameter_key: str,
        is_prefetch: bool,
    ) -> None:
        stale = generation != self.processing_generation or parameter_key != self.current_parameter_key()
        for index, output_path in output_paths.items():
            if not stale and output_path.exists():
                self.processed_pages[index] = output_path
        self.upscale_running = False
        self.prefetch_running = False
        self.apply_button.setEnabled(True)
        if stale:
            self.parameter_status.setText("古い先読み結果を破棄しました。")
            self.load_cached_outputs(self.visible_and_prefetch_indexes())
            self.update_quality_state()
            self.request_prefetch()
            self.render_spread()
            return
        if errors:
            if is_prefetch:
                self.stop_prefetch("AI先読み補正を停止しました。原画表示は継続します。")
                self.render_spread()
                return
            self.parameter_status.setText(f"補正エラーあり: {elapsed_ms / 1000:.1f}秒\n" + "\n".join(errors[:2]))
        else:
            prefix = "先読み補正完了" if is_prefetch else "補正完了"
            self.parameter_status.setText(f"{prefix}: {elapsed_ms / 1000:.1f}秒")
        if not is_prefetch:
            self.original_check.setChecked(False)
        self.update_quality_state()
        self.render_spread()

    def closeEvent(self, event) -> None:
        self.notify_page_changed()
        if self.cleanup_dir is not None:
            shutil.rmtree(self.cleanup_dir, ignore_errors=True)
            self.cleanup_dir = None
        if self.close_callback is not None:
            self.close_callback(self)
        super().closeEvent(event)


def parse_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(description="Manual two-page spread smoke viewer.")
    parser.add_argument("sample", nargs="?", help="folder/archive/image sample path")
    parser.add_argument("--bookshelf", action="store_true", help="open the RAIV bookshelf window")
    parser.add_argument("--processed-dir", help="directory containing processed images")
    parser.add_argument("--original", action="store_true", help="ignore processed images")
    parser.add_argument("--use-processed", action="store_true", help="auto-load processed benchmark images when available")
    parser.add_argument("--no-auto-prefetch", action="store_true", help="disable interactive correction prefetch")
    parser.add_argument("--no-cover-single", action="store_true", help="start with a normal two-page spread instead of a single cover")
    parser.add_argument("--prefetch", type=int, default=6, help="number of pages to correct ahead")
    parser.add_argument("--skip-height", type=int, default=2234, help="skip correction when source height is this value or higher")
    parser.add_argument(
        "--direction",
        choices=["rtl", "ltr"],
        default="rtl",
        help="page-turn direction: rtl for right-bound manga, ltr for western comics",
    )
    parser.add_argument(
        "--spread-order",
        choices=["ltr", "rtl"],
        default=None,
        help="visual page placement in a spread: ltr shows current/current+1, rtl reverses them",
    )
    args, _unknown = parser.parse_known_args([arg for arg in argv[1:] if not arg.startswith("-psn_")])
    return args


def should_open_bookshelf(args: Namespace) -> bool:
    return bool(args.bookshelf or not args.sample)


def choose_source(sample_arg: str | None) -> Path:
    if sample_arg:
        return Path(sample_arg).expanduser()
    samples = discover_samples(SAMPLE_DIR)
    if not samples:
        raise SystemExit(f"No samples found. Put folders or archives in {SAMPLE_DIR}")
    return samples[0]


def choose_source_with_dialog(parent=None) -> Path:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        "Open RAIV sample",
        str(Path.home()),
        "Images and archives (*.zip *.cbz *.rar *.cbr *.7z *.cb7 *.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.avif);;All files (*)",
    )
    if not path:
        raise SystemExit("No sample selected.")
    return Path(path).expanduser()


def default_processed_dir(source: Path) -> Path:
    return DEFAULT_UPSCALE_DIR / source.stem / "realcugan"


def collect_processed_pages(source_pages: list[Path], processed_dir: Path | None) -> list[Path | None]:
    if processed_dir is None or not processed_dir.is_dir():
        return [None] * len(source_pages)
    processed: list[Path | None] = []
    for index, source_page in enumerate(source_pages, start=1):
        candidates = sorted(processed_dir.glob(f"{index:04d}_{source_page.stem}_*.png"))
        processed.append(candidates[0].resolve() if candidates else None)
    return processed


def main() -> None:
    if PYSIDE_IMPORT_ERROR is not None:
        raise SystemExit("PySide6 is required: python3 -m pip install PySide6") from PYSIDE_IMPORT_ERROR
    args = parse_args(sys.argv)
    app = QApplication(sys.argv)
    app.setApplicationName("RAIV")
    if should_open_bookshelf(args):
        from raiv_app.bookshelf import BookshelfWindow

        window = BookshelfWindow()
        window.show()
        window.raise_()
        window.activateWindow()
        QTimer.singleShot(0, window.raise_)
        QTimer.singleShot(0, window.activateWindow)
        app.exec()
        return
    if args.sample:
        source = choose_source(args.sample)
    else:
        try:
            source = choose_source(None)
        except SystemExit:
            source = choose_source_with_dialog()
    pages, cleanup_dir = load_sample_pages(source)
    if not pages:
        raise SystemExit(f"No images found in {source}")
    if args.original:
        processed_dir = None
    elif args.processed_dir:
        processed_dir = Path(args.processed_dir).expanduser()
    elif args.use_processed:
        processed_dir = default_processed_dir(source)
    else:
        processed_dir = None
    processed_pages = collect_processed_pages(pages, processed_dir)
    window = SpreadWindow(
        pages,
        source.name,
        cleanup_dir,
        processed_pages=processed_pages,
        reading_direction=args.direction,
        spread_order=args.spread_order or default_spread_order(args.direction),
        cover_single=not args.no_cover_single,
        auto_prefetch=not args.no_auto_prefetch,
        prefetch_count=args.prefetch,
        upscale_height_threshold=args.skip_height,
    )
    window.show()
    window.raise_()
    window.activateWindow()
    QTimer.singleShot(0, window.raise_)
    QTimer.singleShot(0, window.activateWindow)
    app.exec()


if __name__ == "__main__":
    main()
