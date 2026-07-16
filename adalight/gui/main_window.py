"""Главное окно приложения: настройки, предпросмотр, управление движком, трей."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..capture import list_outputs
from ..config import BACKENDS, COLOR_ORDERS, DIRECTIONS, START_CORNERS, Config
from ..device import list_serial_ports
from ..engine import Engine, Mode
from .preview import LedPreview

_CORNER_LABELS = {
    "top-left": "Верхний левый",
    "top-right": "Верхний правый",
    "bottom-left": "Нижний левый",
    "bottom-right": "Нижний правый",
}
_DIRECTION_LABELS = {"cw": "По часовой", "ccw": "Против часовой"}
_BAUDS = ("115200", "230400", "460800", "500000", "921600", "1000000", "2000000")


class EngineThread(QThread):
    colorsReady = Signal(object)
    fpsChanged = Signal(float)
    failed = Signal(str)

    def __init__(self, cfg: Config, mode: Mode, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._mode: Mode = mode
        self._engine: Engine | None = None

    def run(self) -> None:
        try:
            self._engine = Engine(
                self._cfg,
                on_colors=self.colorsReady.emit,
                on_fps=self.fpsChanged.emit,
            )
            self._engine.run(self._mode)
        except Exception as e:  # noqa: BLE001 — любая ошибка уходит в UI
            self.failed.emit(str(e))

    def request_stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()


def _make_icon() -> QIcon:
    """Программная иконка: тёмный экран с цветной подсветкой по углам."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for (x, y), color in {
        (8, 8): QColor(255, 60, 60),
        (36, 8): QColor(60, 255, 60),
        (8, 36): QColor(255, 210, 40),
        (36, 36): QColor(70, 120, 255),
    }.items():
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(x, y, 20, 20)
    p.setBrush(QColor(24, 26, 30))
    p.drawRoundedRect(14, 14, 36, 36, 6, 6)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Adalight {__version__}")
        self.setWindowIcon(_make_icon())

        self.cfg = Config.load()
        self.thread: EngineThread | None = None
        self._quitting = False
        self._tray_tip_shown = False

        self._build_ui()
        self._apply_cfg_to_ui(self.cfg)
        self._build_tray()
        self._refresh_preview_layout()

    # ── построение интерфейса ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)

        # левая колонка: настройки
        form_host = QWidget()
        left = QVBoxLayout(form_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self._group_connection())
        left.addWidget(self._group_leds())
        left.addWidget(self._group_capture())
        left.addWidget(self._group_image())
        left.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(form_host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumWidth(360)
        root.addWidget(scroll, 0)

        # правая колонка: предпросмотр и управление
        right = QVBoxLayout()
        self.preview = LedPreview()
        right.addWidget(self.preview, 1)

        controls = QHBoxLayout()
        self.btn_start = QPushButton("▶ Старт")
        self.btn_start.clicked.connect(self._on_start_stop)
        self.btn_apply = QPushButton("Применить")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setToolTip("Перезапустить подсветку с новыми настройками")
        self.btn_apply.clicked.connect(lambda: self._start_engine("live"))
        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_apply)
        right.addLayout(controls)

        tests = QHBoxLayout()
        btn_sides = QPushButton("Тест: стороны")
        btn_sides.setToolTip("Верх=красный, право=зелёный, низ=синий, лево=жёлтый")
        btn_sides.clicked.connect(lambda: self._start_engine("sides"))
        btn_chase = QPushButton("Тест: бегущий")
        btn_chase.clicked.connect(lambda: self._start_engine("chase"))
        btn_off = QPushButton("Погасить")
        btn_off.clicked.connect(lambda: self._start_engine("off"))
        for b in (btn_sides, btn_chase, btn_off):
            tests.addWidget(b)
        right.addLayout(tests)

        btn_save = QPushButton("💾 Сохранить настройки")
        btn_save.clicked.connect(self._on_save)
        right.addWidget(btn_save)

        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self.lbl_state = QLabel("Остановлено")
        self.lbl_fps = QLabel("")
        self.statusBar().addWidget(self.lbl_state)
        self.statusBar().addPermanentWidget(self.lbl_fps)

    def _group_connection(self) -> QGroupBox:
        g = QGroupBox("Подключение")
        form = QFormLayout(g)

        self.cb_port = QComboBox()
        self.cb_port.setEditable(True)
        btn = QPushButton("⟳")
        btn.setFixedWidth(32)
        btn.setToolTip("Обновить список портов")
        btn.clicked.connect(self._refresh_ports)
        row = QHBoxLayout()
        row.addWidget(self.cb_port, 1)
        row.addWidget(btn)
        form.addRow("Порт:", row)

        self.cb_baud = QComboBox()
        self.cb_baud.setEditable(True)
        self.cb_baud.addItems(_BAUDS)
        form.addRow("Скорость:", self.cb_baud)

        self.cb_order = QComboBox()
        self.cb_order.addItems(COLOR_ORDERS)
        self.cb_order.setToolTip("Порядок каналов ленты: WS2812 обычно GRB")
        form.addRow("Порядок цвета:", self.cb_order)
        return g

    def _group_leds(self) -> QGroupBox:
        g = QGroupBox("Светодиоды")
        form = QFormLayout(g)

        def spin() -> QSpinBox:
            s = QSpinBox()
            s.setRange(0, 500)
            s.valueChanged.connect(self._refresh_preview_layout)
            return s

        self.sp_top, self.sp_right = spin(), spin()
        self.sp_bottom, self.sp_left = spin(), spin()
        form.addRow("Сверху:", self.sp_top)
        form.addRow("Справа:", self.sp_right)
        form.addRow("Снизу:", self.sp_bottom)
        form.addRow("Слева:", self.sp_left)

        self.cb_corner = QComboBox()
        for value in START_CORNERS:
            self.cb_corner.addItem(_CORNER_LABELS[value], value)
        self.cb_corner.currentIndexChanged.connect(self._refresh_preview_layout)
        form.addRow("Начальный угол:", self.cb_corner)

        self.cb_direction = QComboBox()
        for value in DIRECTIONS:
            self.cb_direction.addItem(_DIRECTION_LABELS[value], value)
        self.cb_direction.currentIndexChanged.connect(self._refresh_preview_layout)
        form.addRow("Направление:", self.cb_direction)

        self.ch_flip_x = QCheckBox("Инверсия лево/право")
        self.ch_flip_y = QCheckBox("Инверсия верх/низ")
        self.ch_flip_x.toggled.connect(self._refresh_preview_layout)
        self.ch_flip_y.toggled.connect(self._refresh_preview_layout)
        form.addRow(self.ch_flip_x)
        form.addRow(self.ch_flip_y)
        return g

    def _group_capture(self) -> QGroupBox:
        g = QGroupBox("Захват экрана")
        form = QFormLayout(g)

        self.cb_output = QComboBox()
        self.cb_output.setEditable(True)
        btn = QPushButton("⟳")
        btn.setFixedWidth(32)
        btn.setToolTip("Обновить список мониторов")
        btn.clicked.connect(self._refresh_outputs)
        row = QHBoxLayout()
        row.addWidget(self.cb_output, 1)
        row.addWidget(btn)
        form.addRow("Монитор:", row)

        self.cb_backend = QComboBox()
        self.cb_backend.addItems(BACKENDS)
        self.cb_backend.setToolTip(
            "auto: Windows — dxcam (fallback mss), Wayland — wf-recorder, иначе mss"
        )
        form.addRow("Бэкенд:", self.cb_backend)

        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(1, 240)
        form.addRow("Целевой FPS:", self.sp_fps)

        self.ds_band = QDoubleSpinBox()
        self.ds_band.setRange(0.02, 0.5)
        self.ds_band.setSingleStep(0.01)
        self.ds_band.setToolTip("Толщина краевой полосы, доля экрана")
        form.addRow("Полоса захвата:", self.ds_band)

        self.ds_window = QDoubleSpinBox()
        self.ds_window.setRange(0.01, 0.5)
        self.ds_window.setSingleStep(0.01)
        self.ds_window.setToolTip("Ширина окна одного диода, доля экрана")
        form.addRow("Окно диода:", self.ds_window)
        return g

    def _group_image(self) -> QGroupBox:
        g = QGroupBox("Изображение")
        form = QFormLayout(g)

        def slider(lo: int, hi: int, factor: float) -> tuple[QSlider, QLabel, QHBoxLayout]:
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            label = QLabel()
            label.setFixedWidth(38)
            s.valueChanged.connect(lambda v: label.setText(f"{v * factor:.2f}"))
            row = QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(label)
            return s, label, row

        self.sl_gamma, _, row = slider(50, 320, 0.01)
        form.addRow("Гамма:", row)
        self.sl_bright, _, row = slider(5, 150, 0.01)
        form.addRow("Яркость:", row)
        self.sl_sat, _, row = slider(0, 250, 0.01)
        form.addRow("Насыщенность:", row)
        self.sl_smooth, _, row = slider(0, 95, 0.01)
        form.addRow("Сглаживание:", row)
        return g

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(_make_icon(), self)
        menu = QMenu()
        act_show = QAction("Показать окно", menu)
        act_show.triggered.connect(self._show_from_tray)
        act_start = QAction("Старт/Стоп", menu)
        act_start.triggered.connect(self._on_start_stop)
        act_quit = QAction("Выход", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addAction(act_start)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Adalight")
        self.tray.activated.connect(
            lambda reason: self._show_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.show()

    # ── связь Config <-> UI ───────────────────────────────────────────────

    def _apply_cfg_to_ui(self, cfg: Config) -> None:
        self._refresh_ports()
        self.cb_port.setCurrentText(cfg.port)
        self.cb_baud.setCurrentText(str(cfg.baud))
        self.cb_order.setCurrentText(cfg.color_order)

        self.sp_top.setValue(cfg.leds_top)
        self.sp_right.setValue(cfg.leds_right)
        self.sp_bottom.setValue(cfg.leds_bottom)
        self.sp_left.setValue(cfg.leds_left)
        self.cb_corner.setCurrentIndex(START_CORNERS.index(cfg.start_corner))
        self.cb_direction.setCurrentIndex(DIRECTIONS.index(cfg.direction))
        self.ch_flip_x.setChecked(cfg.flip_x)
        self.ch_flip_y.setChecked(cfg.flip_y)

        self._refresh_outputs()
        self.cb_output.setCurrentText(cfg.output)
        self.cb_backend.setCurrentText(cfg.backend)
        self.sp_fps.setValue(cfg.target_fps)
        self.ds_band.setValue(cfg.band_size)
        self.ds_window.setValue(cfg.window_size)

        self.sl_gamma.setValue(round(cfg.gamma * 100))
        self.sl_bright.setValue(round(cfg.brightness * 100))
        self.sl_sat.setValue(round(cfg.saturation * 100))
        self.sl_smooth.setValue(round(cfg.smooth * 100))

    def _cfg_from_ui(self) -> Config:
        cfg = Config(
            port=self.cb_port.currentText().strip(),
            baud=int(self.cb_baud.currentText() or 115200),
            color_order=self.cb_order.currentText(),
            output=self._current_output(),
            leds_top=self.sp_top.value(),
            leds_right=self.sp_right.value(),
            leds_bottom=self.sp_bottom.value(),
            leds_left=self.sp_left.value(),
            start_corner=self.cb_corner.currentData(),
            direction=self.cb_direction.currentData(),
            flip_x=self.ch_flip_x.isChecked(),
            flip_y=self.ch_flip_y.isChecked(),
            backend=self.cb_backend.currentText(),
            target_fps=self.sp_fps.value(),
            band_size=self.ds_band.value(),
            window_size=self.ds_window.value(),
            gamma=self.sl_gamma.value() / 100,
            brightness=self.sl_bright.value() / 100,
            saturation=self.sl_sat.value() / 100,
            smooth=self.sl_smooth.value() / 100,
        )
        return cfg

    def _current_output(self) -> str:
        idx = self.cb_output.currentIndex()
        data = self.cb_output.itemData(idx)
        # если пользователь вписал значение руками — берём текст
        if data is not None and self.cb_output.itemText(idx) == self.cb_output.currentText():
            return data
        return self.cb_output.currentText().strip()

    def _refresh_ports(self) -> None:
        current = self.cb_port.currentText()
        self.cb_port.clear()
        for device, desc in list_serial_ports():
            label = f"{device} — {desc}" if desc else device
            self.cb_port.addItem(device)
            self.cb_port.setItemData(self.cb_port.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        if current:
            self.cb_port.setCurrentText(current)

    def _refresh_outputs(self) -> None:
        current = self.cb_output.currentText()
        self.cb_output.clear()
        self.cb_output.addItem("(основной)", "")
        for value, label in list_outputs():
            self.cb_output.addItem(label, value)
        if current:
            self.cb_output.setCurrentText(current)

    def _refresh_preview_layout(self) -> None:
        self.preview.set_config(self._cfg_from_ui())

    # ── управление движком ────────────────────────────────────────────────

    def _on_start_stop(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self._stop_engine()
        else:
            self._start_engine("live")

    def _start_engine(self, mode: Mode) -> None:
        self._stop_engine()
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Настройки", str(e))
            return

        self.thread = EngineThread(cfg, mode, self)
        self.thread.colorsReady.connect(self.preview.set_colors)
        self.thread.fpsChanged.connect(lambda f: self.lbl_fps.setText(f"{f:.1f} fps"))
        self.thread.failed.connect(self._on_engine_failed)
        self.thread.finished.connect(self._on_engine_finished)
        self.thread.start()

        names = {
            "live": "Подсветка",
            "sides": "Тест сторон",
            "chase": "Бегущий диод",
            "off": "Гашение",
        }
        self.lbl_state.setText(f"{names[mode]}: работает")
        self.btn_start.setText("■ Стоп")
        self.btn_apply.setEnabled(mode == "live")

    def _stop_engine(self) -> None:
        if self.thread is None:
            return
        self.thread.request_stop()
        self.thread.wait(5000)
        self.thread = None

    def _on_engine_finished(self) -> None:
        self.lbl_state.setText("Остановлено")
        self.lbl_fps.setText("")
        self.btn_start.setText("▶ Старт")
        self.btn_apply.setEnabled(False)

    def _on_engine_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Ошибка", message)

    # ── прочее ────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Настройки", str(e))
            return
        path = cfg.save()
        self.cfg = cfg
        self.statusBar().showMessage(f"Сохранено: {path}", 4000)

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self.tray is not None and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_tip_shown:
                self._tray_tip_shown = True
                self.tray.showMessage(
                    "Adalight",
                    "Приложение продолжает работать в трее. Выход — через меню трея.",
                )
            return
        self._stop_engine()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.quit()  # quitOnLastWindowClosed выключен — завершаем явно


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Adalight")
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow()
    win.resize(900, 560)
    win.show()
    return app.exec()
