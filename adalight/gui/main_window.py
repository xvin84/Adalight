"""Главное окно приложения: настройки, предпросмотр, управление движком, трей.

Логика применения настроек:
- «мягкие» (гамма/яркость/насыщенность/сглаживание, расписание, адаптивная
  яркость) применяются к работающему движку мгновенно и без ресета платы;
- «жёсткие» (порт, диоды, геометрия, монитор, бэкенд, FPS) перезапускают
  подсветку автоматически через 5 секунд после последнего изменения.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QThread, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, autostart, updates
from ..capture import list_outputs
from ..config import (
    BACKENDS,
    COLOR_ORDERS,
    DIRECTIONS,
    LAMP_EFFECTS,
    MODES,
    MUSIC_EFFECTS,
    START_CORNERS,
    Config,
)
from ..device import list_serial_ports
from ..engine import Engine, Mode
from ..schedule import parse_time
from .preview import LedPreview

_CORNER_LABELS = {
    "top-left": "Верхний левый",
    "top-right": "Верхний правый",
    "bottom-left": "Нижний левый",
    "bottom-right": "Нижний правый",
}
_DIRECTION_LABELS = {"cw": "По часовой", "ccw": "Против часовой"}
_MODE_LABELS = {"capture": "Захват экрана", "lamp": "Лампа", "music": "Цветомузыка"}
_MODE_TO_ENGINE: dict[str, Mode] = {"capture": "live", "lamp": "lamp", "music": "music"}
_LAMP_EFFECT_LABELS = {
    "solid": "Сплошной цвет",
    "gradient": "Градиент",
    "rainbow": "Радуга",
    "breathing": "Дыхание",
}
_MUSIC_EFFECT_LABELS = {"spectrum": "Спектр по периметру", "pulse": "Пульс от баса"}
_MAIN_MODES: tuple[Mode, ...] = ("live", "lamp", "music")
_BAUDS = ("115200", "230400", "460800", "500000", "921600", "1000000", "2000000")
_APPLY_DELAY_S = 5

_BTN_START_QSS = (
    "QPushButton {background: #2e7d46; color: white; font-weight: 600; padding: 7px;}"
    "QPushButton:hover {background: #379554;}"
)
_BTN_STOP_QSS = (
    "QPushButton {background: #8b2e2e; color: white; font-weight: 600; padding: 7px;}"
    "QPushButton:hover {background: #a63a3a;}"
)


class EngineThread(QThread):
    colorsReady = Signal(object)
    fpsChanged = Signal(float)
    backendReady = Signal(str)
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
                on_backend=self.backendReady.emit,
            )
            self._engine.run(self._mode)
        except Exception as e:  # noqa: BLE001 — любая ошибка уходит в UI
            self.failed.emit(str(e))

    def request_stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()

    def set_tuning(self, **kwargs) -> None:
        if self._engine is not None:
            self._engine.set_tuning(**kwargs)


class UpdateCheckThread(QThread):
    """Фоновая проверка последнего релиза на GitHub."""

    result = Signal(str, str)  # версия, url
    failed = Signal(str)

    def run(self) -> None:
        try:
            version, url = updates.fetch_latest()
        except Exception as e:  # noqa: BLE001 — сеть может падать чем угодно
            self.failed.emit(str(e))
            return
        self.result.emit(version, url)


class ScheduleDelegate(QStyledItemDelegate):
    """Жёсткие редакторы ячеек расписания: время только как ЧЧ:ММ, яркость 0..2.

    Произвольный текст ввести невозможно: колонки времени редактируются
    через QTimeEdit («1816» превращается в «18:16»), яркость — через спинбокс.
    """

    TIME_COLUMNS = (0, 1)

    def createEditor(self, parent, option, index):  # noqa: N802 (Qt API)
        if index.column() in self.TIME_COLUMNS:
            editor = QTimeEdit(parent)
            editor.setDisplayFormat("HH:mm")
            return editor
        editor = QDoubleSpinBox(parent)
        editor.setRange(0.0, 2.0)
        editor.setSingleStep(0.05)
        editor.setDecimals(2)
        return editor

    def setEditorData(self, editor, index):  # noqa: N802 (Qt API)
        text = str(index.data() or "")
        if index.column() in self.TIME_COLUMNS:
            t = QTime.fromString(text, "HH:mm")
            editor.setTime(t if t.isValid() else QTime(0, 0))
        else:
            try:
                editor.setValue(float(text.replace(",", ".")))
            except ValueError:
                editor.setValue(1.0)

    def setModelData(self, editor, model, index):  # noqa: N802 (Qt API)
        if index.column() in self.TIME_COLUMNS:
            model.setData(index, editor.time().toString("HH:mm"))
        else:
            model.setData(index, f"{editor.value():.2f}")


def _normalize_time_text(text: str) -> str:
    """«1816» / «8:5» -> «18:16» / «08:05»; нераспознанное оставляем как есть."""
    try:
        return parse_time(text).strftime("%H:%M")
    except ValueError:
        return text


def _normalize_brightness_text(text: str) -> str:
    try:
        return f"{float(str(text).replace(',', '.')):.2f}"
    except ValueError:
        return text


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
        self._mode: Mode | None = None
        self._quitting = False
        self._tray_tip_shown = False
        self._loading = True

        self._apply_left = 0
        self._apply_timer = QTimer(self)
        self._apply_timer.setInterval(1000)
        self._apply_timer.timeout.connect(self._tick_apply)

        self._build_ui()
        self._apply_cfg_to_ui(self.cfg)
        self._build_tray()
        self._loading = False
        self._refresh_preview_layout()
        QTimer.singleShot(2000, lambda: self._check_updates(silent=True))

    # ── построение интерфейса ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # левая колонка: настройки
        form_host = QWidget()
        left = QVBoxLayout(form_host)
        left.setContentsMargins(0, 0, 6, 0)
        left.addWidget(self._group_mode())
        left.addWidget(self._group_connection())
        left.addWidget(self._group_leds())
        left.addWidget(self._group_capture())
        left.addWidget(self._group_image())
        left.addWidget(self._group_lamp())
        left.addWidget(self._group_music())
        left.addWidget(self._group_adaptive())
        left.addWidget(self._group_schedule())
        left.addWidget(self._group_system())
        left.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(form_host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumWidth(380)
        root.addWidget(scroll, 0)

        # правая колонка: предпросмотр и управление
        right = QVBoxLayout()
        self.preview = LedPreview()
        right.addWidget(self.preview, 1)

        controls = QHBoxLayout()
        self.btn_start = QPushButton("▶ Старт")
        self.btn_start.setStyleSheet(_BTN_START_QSS)
        self.btn_start.clicked.connect(self._on_start_stop)
        self.btn_apply = QPushButton("Применить сейчас")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setToolTip(
            "Перезапустить подсветку с новыми настройками, не дожидаясь автоприменения"
        )
        self.btn_apply.clicked.connect(lambda: self._start_engine(self._selected_mode()))
        self.btn_night = QPushButton("🌙 Ночной режим")
        self.btn_night.setCheckable(True)
        self.btn_night.setToolTip(
            "Теплее (3400K), темнее (×0.6) и плавнее — поверх текущих настроек"
        )
        self.btn_night.toggled.connect(self._on_soft_changed)
        controls.addWidget(self.btn_start, 1)
        controls.addWidget(self.btn_apply, 1)
        controls.addWidget(self.btn_night, 1)
        right.addLayout(controls)

        calib = QGroupBox("Калибровка")
        tests = QHBoxLayout(calib)
        btn_sides = QPushButton("Стороны")
        btn_sides.setToolTip("Верх=красный, право=зелёный, низ=синий, лево=жёлтый")
        btn_sides.clicked.connect(lambda: self._start_engine("sides"))
        btn_chase = QPushButton("Бегущий диод")
        btn_chase.clicked.connect(lambda: self._start_engine("chase"))
        btn_off = QPushButton("Погасить")
        btn_off.clicked.connect(lambda: self._start_engine("off"))
        for b in (btn_sides, btn_chase, btn_off):
            tests.addWidget(b)
        right.addWidget(calib)

        btn_save = QPushButton("💾 Сохранить настройки")
        btn_save.clicked.connect(self._on_save)
        right.addWidget(btn_save)

        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self.lbl_state = QLabel("Остановлено")
        self.lbl_pending = QLabel("")
        self.lbl_backend = QLabel("")
        self.lbl_fps = QLabel("")
        self.statusBar().addWidget(self.lbl_state)
        self.statusBar().addWidget(self.lbl_pending)
        self.statusBar().addPermanentWidget(self.lbl_backend)
        self.statusBar().addPermanentWidget(self.lbl_fps)

    def _group_mode(self) -> QGroupBox:
        g = QGroupBox("Режим")
        form = QFormLayout(g)
        self.cb_mode = QComboBox()
        for value in MODES:
            self.cb_mode.addItem(_MODE_LABELS[value], value)
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Источник:", self.cb_mode)
        return g

    def _group_lamp(self) -> QGroupBox:
        g = QGroupBox("Лампа")
        form = QFormLayout(g)

        self.cb_lamp_effect = QComboBox()
        for value in LAMP_EFFECTS:
            self.cb_lamp_effect.addItem(_LAMP_EFFECT_LABELS[value], value)
        self.cb_lamp_effect.currentIndexChanged.connect(self._on_soft_changed)
        form.addRow("Эффект:", self.cb_lamp_effect)

        self.btn_lamp_color = self._color_button("#ff9329")
        form.addRow("Цвет:", self.btn_lamp_color)
        self.btn_lamp_color2 = self._color_button("#2962ff")
        self.btn_lamp_color2.setToolTip("Второй цвет для градиента")
        form.addRow("Цвет 2:", self.btn_lamp_color2)

        self.sl_lamp_speed, row = self._slider_row(0, 100)
        form.addRow("Скорость:", row)
        return g

    def _group_music(self) -> QGroupBox:
        g = QGroupBox("Цветомузыка")
        form = QFormLayout(g)

        self.cb_music_effect = QComboBox()
        for value in MUSIC_EFFECTS:
            self.cb_music_effect.addItem(_MUSIC_EFFECT_LABELS[value], value)
        self.cb_music_effect.currentIndexChanged.connect(self._on_soft_changed)
        form.addRow("Эффект:", self.cb_music_effect)

        self.btn_music_color = self._color_button("#ff2d95")
        self.btn_music_color.setToolTip("Цвет для эффекта «Пульс»")
        form.addRow("Цвет:", self.btn_music_color)

        self.sl_music_gain, row = self._slider_row(10, 500)
        self.sl_music_gain.setToolTip("Чувствительность: больше — ярче реакция на звук")
        form.addRow("Чувствительность:", row)
        return g

    def _color_button(self, initial: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(64, 24)
        self._set_button_color(btn, initial)
        btn.clicked.connect(lambda: self._pick_color(btn))
        return btn

    @staticmethod
    def _set_button_color(btn: QPushButton, value: str) -> None:
        btn.setProperty("color_value", value)
        btn.setStyleSheet(
            f"background: {value}; border: 1px solid #777; border-radius: 4px;"
        )

    def _pick_color(self, btn: QPushButton) -> None:
        color = QColorDialog.getColor(QColor(btn.property("color_value")), self, "Цвет")
        if color.isValid():
            self._set_button_color(btn, color.name())
            self._on_soft_changed()

    def _group_connection(self) -> QGroupBox:
        g = QGroupBox("Подключение")
        form = QFormLayout(g)

        self.cb_port = QComboBox()
        self.cb_port.setEditable(True)
        self.cb_port.currentTextChanged.connect(self._on_hard_changed)
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
        self.cb_baud.setToolTip(
            "115200 ограничивает частоту обновления: ~76 fps при 48 диодах, "
            "~13 fps при 300. Поднимите скорость и здесь, и в прошивке."
        )
        self.cb_baud.currentTextChanged.connect(self._on_hard_changed)
        form.addRow("Скорость:", self.cb_baud)

        self.cb_order = QComboBox()
        self.cb_order.addItems(COLOR_ORDERS)
        self.cb_order.setToolTip("Порядок каналов ленты: WS2812 обычно GRB")
        self.cb_order.currentIndexChanged.connect(self._on_hard_changed)
        form.addRow("Порядок цвета:", self.cb_order)
        return g

    def _group_leds(self) -> QGroupBox:
        g = QGroupBox("Светодиоды")
        form = QFormLayout(g)

        def spin() -> QSpinBox:
            s = QSpinBox()
            s.setRange(0, 500)
            s.valueChanged.connect(self._on_geometry_changed)
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
        self.cb_corner.currentIndexChanged.connect(self._on_geometry_changed)
        form.addRow("Начальный угол:", self.cb_corner)

        self.cb_direction = QComboBox()
        for value in DIRECTIONS:
            self.cb_direction.addItem(_DIRECTION_LABELS[value], value)
        self.cb_direction.currentIndexChanged.connect(self._on_geometry_changed)
        form.addRow("Направление:", self.cb_direction)

        self.ch_flip_x = QCheckBox("Инверсия лево/право")
        self.ch_flip_y = QCheckBox("Инверсия верх/низ")
        self.ch_flip_x.toggled.connect(self._on_geometry_changed)
        self.ch_flip_y.toggled.connect(self._on_geometry_changed)
        form.addRow(self.ch_flip_x)
        form.addRow(self.ch_flip_y)
        return g

    def _group_capture(self) -> QGroupBox:
        g = QGroupBox("Захват экрана")
        form = QFormLayout(g)

        self.cb_output = QComboBox()
        self.cb_output.setEditable(True)
        self.cb_output.currentTextChanged.connect(self._on_hard_changed)
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
            "auto: Windows — bettercam → dxcam → mss, Wayland — wf-recorder, иначе mss.\n"
            "Реально работающий бэкенд показан в статус-баре."
        )
        self.cb_backend.currentIndexChanged.connect(self._on_hard_changed)
        form.addRow("Бэкенд:", self.cb_backend)

        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(1, 240)
        self.sp_fps.valueChanged.connect(self._on_hard_changed)
        form.addRow("Целевой FPS:", self.sp_fps)

        self.ds_band = QDoubleSpinBox()
        self.ds_band.setRange(0.02, 0.5)
        self.ds_band.setSingleStep(0.01)
        self.ds_band.setToolTip("Толщина краевой полосы, доля экрана")
        self.ds_band.valueChanged.connect(self._on_hard_changed)
        form.addRow("Полоса захвата:", self.ds_band)

        self.ds_window = QDoubleSpinBox()
        self.ds_window.setRange(0.01, 0.5)
        self.ds_window.setSingleStep(0.01)
        self.ds_window.setToolTip("Ширина окна одного диода, доля экрана")
        self.ds_window.valueChanged.connect(self._on_hard_changed)
        form.addRow("Окно диода:", self.ds_window)
        return g

    def _slider_row(self, lo: int, hi: int) -> tuple[QSlider, QHBoxLayout]:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        label = QLabel()
        label.setFixedWidth(38)
        s.valueChanged.connect(lambda v: label.setText(f"{v / 100:.2f}"))
        s.valueChanged.connect(self._on_soft_changed)
        row = QHBoxLayout()
        row.addWidget(s, 1)
        row.addWidget(label)
        return s, row

    def _group_image(self) -> QGroupBox:
        g = QGroupBox("Изображение")
        form = QFormLayout(g)

        self.sl_gamma, row = self._slider_row(50, 320)
        form.addRow("Гамма:", row)
        self.sl_bright, row = self._slider_row(5, 150)
        self.sl_bright.setToolTip(
            "Основная яркость. Используется как значение «по умолчанию» "
            "для расписания и как база для адаптивной яркости."
        )
        form.addRow("Яркость:", row)
        self.sl_sat, row = self._slider_row(0, 250)
        form.addRow("Насыщенность:", row)
        self.sl_smooth, row = self._slider_row(0, 95)
        form.addRow("Сглаживание:", row)

        # цветовая температура — со своим форматом подписи (K)
        self.sl_temp = QSlider(Qt.Orientation.Horizontal)
        self.sl_temp.setRange(1000, 10000)
        self.sl_temp.setSingleStep(100)
        self.sl_temp.setToolTip("6500K — нейтрально, меньше — теплее")
        lbl = QLabel()
        lbl.setFixedWidth(48)
        self.sl_temp.valueChanged.connect(lambda v: lbl.setText(f"{v}K"))
        self.sl_temp.valueChanged.connect(self._on_soft_changed)
        row = QHBoxLayout()
        row.addWidget(self.sl_temp, 1)
        row.addWidget(lbl)
        form.addRow("Температура:", row)

        self.sl_black, row = self._slider_row(0, 50)
        self.sl_black.setToolTip(
            "Отсечка шума в тенях: сигнал ниже порога гасится в ноль"
        )
        form.addRow("Порог теней:", row)
        return g

    def _group_adaptive(self) -> QGroupBox:
        g = QGroupBox("Адаптивная яркость")
        form = QFormLayout(g)

        self.ch_adaptive = QCheckBox("Подстраивать яркость под яркость изображения")
        self.ch_adaptive.setToolTip(
            "Тёмная сцена — лента тускнеет к «мин», яркая — разгорается к «макс». "
            "Работает как множитель к основной яркости (или яркости из расписания)."
        )
        self.ch_adaptive.toggled.connect(self._on_soft_changed)
        form.addRow(self.ch_adaptive)

        self.sl_amin, row = self._slider_row(0, 150)
        form.addRow("Мин. коэффициент:", row)
        self.sl_amax, row = self._slider_row(0, 150)
        form.addRow("Макс. коэффициент:", row)
        self.sl_aspeed, row = self._slider_row(1, 100)
        self.sl_aspeed.setToolTip("Скорость реакции: больше — быстрее догоняет сцену")
        form.addRow("Скорость:", row)
        return g

    def _group_schedule(self) -> QGroupBox:
        g = QGroupBox("Расписание яркости")
        lay = QVBoxLayout(g)

        self.ch_schedule = QCheckBox("Включить (вне интервалов действует яркость «по умолчанию»)")
        self.ch_schedule.toggled.connect(self._on_soft_changed)
        lay.addWidget(self.ch_schedule)

        self.tbl_schedule = QTableWidget(0, 3)
        self.tbl_schedule.setHorizontalHeaderLabels(["Начало", "Конец", "Яркость"])
        self.tbl_schedule.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.tbl_schedule.verticalHeader().setVisible(False)
        self.tbl_schedule.setFixedHeight(140)
        self.tbl_schedule.setToolTip(
            "Время в формате ЧЧ:ММ, интервалы через полночь (22:00–06:00) поддерживаются"
        )
        self.tbl_schedule.setItemDelegate(ScheduleDelegate(self.tbl_schedule))
        self.tbl_schedule.itemChanged.connect(self._on_soft_changed)
        lay.addWidget(self.tbl_schedule)

        btns = QHBoxLayout()
        btn_add = QPushButton("+ Интервал")
        btn_add.clicked.connect(self._on_schedule_add)
        btn_del = QPushButton("− Удалить")
        btn_del.clicked.connect(self._on_schedule_del)
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addStretch(1)
        lay.addLayout(btns)
        return g

    def _group_system(self) -> QGroupBox:
        g = QGroupBox("Система")
        lay = QVBoxLayout(g)
        self.ch_autostart = QCheckBox("Запускать при входе в систему (свёрнуто в трей)")
        if autostart.is_supported():
            try:
                self.ch_autostart.setChecked(autostart.is_enabled())
            except OSError:
                pass
        else:
            self.ch_autostart.setEnabled(False)
            self.ch_autostart.setToolTip("Не поддерживается на этой ОС")
        self.ch_autostart.toggled.connect(self._on_autostart_toggled)
        lay.addWidget(self.ch_autostart)

        row = QHBoxLayout()
        self.btn_update = QPushButton("Проверить обновления")
        self.btn_update.clicked.connect(self._check_updates)
        self.lbl_update = QLabel("")
        row.addWidget(self.btn_update)
        row.addWidget(self.lbl_update, 1)
        lay.addLayout(row)
        return g

    # ── обновления ────────────────────────────────────────────────────────

    def _check_updates(self, silent: bool = False) -> None:
        self._update_thread = UpdateCheckThread(self)
        self._update_thread.result.connect(self._on_update_result)
        if not silent:
            self._update_thread.failed.connect(
                lambda msg: self.lbl_update.setText(f"Ошибка проверки: {msg}")
            )
            self.lbl_update.setText("Проверяю…")
        self._update_thread.start()

    def _on_update_result(self, version: str, url: str) -> None:
        if updates.is_newer(version, __version__):
            self.lbl_update.setText(f"Доступна версия {version}")
            self.btn_update.setText(f"⬇ Обновить до v{version}")
            self.btn_update.clicked.disconnect()
            self.btn_update.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        else:
            self.lbl_update.setText("У вас последняя версия")

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
        act_night = QAction("Ночной режим", menu)
        act_night.setCheckable(True)
        act_night.setChecked(self.btn_night.isChecked())
        act_night.toggled.connect(self.btn_night.setChecked)
        self.btn_night.toggled.connect(act_night.setChecked)
        act_quit = QAction("Выход", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addAction(act_start)
        menu.addAction(act_night)
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
        self.sl_temp.setValue(cfg.color_temp)
        self.sl_black.setValue(round(cfg.black_threshold * 100))
        self.btn_night.setChecked(cfg.night_mode)

        self.cb_mode.setCurrentIndex(MODES.index(cfg.mode))
        self.cb_lamp_effect.setCurrentIndex(LAMP_EFFECTS.index(cfg.lamp_effect))
        self._set_button_color(self.btn_lamp_color, cfg.lamp_color)
        self._set_button_color(self.btn_lamp_color2, cfg.lamp_color2)
        self.sl_lamp_speed.setValue(round(cfg.lamp_speed * 100))
        self.cb_music_effect.setCurrentIndex(MUSIC_EFFECTS.index(cfg.music_effect))
        self._set_button_color(self.btn_music_color, cfg.music_color)
        self.sl_music_gain.setValue(round(cfg.music_gain * 100))

        self.ch_adaptive.setChecked(cfg.adaptive_enabled)
        self.sl_amin.setValue(round(cfg.adaptive_min * 100))
        self.sl_amax.setValue(round(cfg.adaptive_max * 100))
        self.sl_aspeed.setValue(round(cfg.adaptive_speed * 100))

        self.ch_schedule.setChecked(cfg.schedule_enabled)
        self.tbl_schedule.setRowCount(0)
        for rule in cfg.schedule:
            self._append_schedule_row(
                str(rule.get("start", "")),
                str(rule.get("end", "")),
                str(rule.get("brightness", "")),
            )

    def _cfg_from_ui(self) -> Config:
        return Config(
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
            color_temp=self.sl_temp.value(),
            black_threshold=self.sl_black.value() / 100,
            night_mode=self.btn_night.isChecked(),
            mode=self.cb_mode.currentData(),
            lamp_effect=self.cb_lamp_effect.currentData(),
            lamp_color=self.btn_lamp_color.property("color_value"),
            lamp_color2=self.btn_lamp_color2.property("color_value"),
            lamp_speed=self.sl_lamp_speed.value() / 100,
            music_effect=self.cb_music_effect.currentData(),
            music_color=self.btn_music_color.property("color_value"),
            music_gain=self.sl_music_gain.value() / 100,
            adaptive_enabled=self.ch_adaptive.isChecked(),
            adaptive_min=self.sl_amin.value() / 100,
            adaptive_max=self.sl_amax.value() / 100,
            adaptive_speed=self.sl_aspeed.value() / 100,
            schedule_enabled=self.ch_schedule.isChecked(),
            schedule=self._schedule_from_table(),
        )

    def _current_output(self) -> str:
        idx = self.cb_output.currentIndex()
        data = self.cb_output.itemData(idx)
        # если пользователь вписал значение руками — берём текст
        if data is not None and self.cb_output.itemText(idx) == self.cb_output.currentText():
            return data
        return self.cb_output.currentText().strip()

    def _refresh_ports(self) -> None:
        was_loading, self._loading = self._loading, True
        current = self.cb_port.currentText()
        self.cb_port.clear()
        for device, desc in list_serial_ports():
            label = f"{device} — {desc}" if desc else device
            self.cb_port.addItem(device)
            self.cb_port.setItemData(self.cb_port.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        if current:
            self.cb_port.setCurrentText(current)
        self._loading = was_loading

    def _refresh_outputs(self) -> None:
        was_loading, self._loading = self._loading, True
        current = self.cb_output.currentText()
        self.cb_output.clear()
        self.cb_output.addItem("(основной)", "")
        for value, label in list_outputs():
            self.cb_output.addItem(label, value)
        if current:
            self.cb_output.setCurrentText(current)
        self._loading = was_loading

    def _refresh_preview_layout(self) -> None:
        self.preview.set_config(self._cfg_from_ui())

    # ── расписание ────────────────────────────────────────────────────────

    def _append_schedule_row(self, start: str, end: str, brightness: str) -> None:
        was_loading, self._loading = self._loading, True
        r = self.tbl_schedule.rowCount()
        self.tbl_schedule.insertRow(r)
        texts = (
            _normalize_time_text(start),
            _normalize_time_text(end),
            _normalize_brightness_text(brightness),
        )
        for col, text in enumerate(texts):
            self.tbl_schedule.setItem(r, col, QTableWidgetItem(text))
        self._loading = was_loading

    def _schedule_from_table(self) -> list[dict]:
        def cell(r: int, c: int) -> str:
            item = self.tbl_schedule.item(r, c)
            return item.text().strip() if item else ""

        return [
            {"start": cell(r, 0), "end": cell(r, 1), "brightness": cell(r, 2)}
            for r in range(self.tbl_schedule.rowCount())
        ]

    def _on_schedule_add(self) -> None:
        self._append_schedule_row("08:00", "20:00", "0.9")
        self._on_soft_changed()

    def _on_schedule_del(self) -> None:
        row = self.tbl_schedule.currentRow()
        if row >= 0:
            self.tbl_schedule.removeRow(row)
            self._on_soft_changed()

    # ── применение настроек ───────────────────────────────────────────────

    def _selected_mode(self) -> Mode:
        return _MODE_TO_ENGINE[self.cb_mode.currentData()]

    def _on_mode_changed(self, *args) -> None:
        """Смена источника — перезапуск сразу, ждать 5 секунд тут ни к чему."""
        if self._loading:
            return
        if self._mode in _MAIN_MODES and self.thread is not None:
            self._start_engine(self._selected_mode())

    def _on_geometry_changed(self, *args) -> None:
        if self._loading:
            return
        self._refresh_preview_layout()
        self._on_hard_changed()

    def _on_hard_changed(self, *args) -> None:
        """«Жёсткая» настройка: перезапуск через 5 с после последнего изменения."""
        if self._loading:
            return
        if self._mode not in _MAIN_MODES or self.thread is None:
            return
        self._apply_left = _APPLY_DELAY_S
        self._apply_timer.start()
        self.lbl_pending.setText(f"⏱ автоприменение через {self._apply_left} с")

    def _tick_apply(self) -> None:
        self._apply_left -= 1
        if self._apply_left > 0:
            self.lbl_pending.setText(f"⏱ автоприменение через {self._apply_left} с")
            return
        self._cancel_pending_apply()
        self._start_engine(self._selected_mode())

    def _cancel_pending_apply(self) -> None:
        self._apply_timer.stop()
        self._apply_left = 0
        self.lbl_pending.setText("")

    def _on_soft_changed(self, *args) -> None:
        """«Мягкая» настройка: применяется к работающему движку сразу, без ресета платы."""
        if self._loading:
            return
        if self._mode not in _MAIN_MODES or self.thread is None:
            return
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            self.statusBar().showMessage(str(e), 4000)
            return
        self.thread.set_tuning(
            gamma=cfg.gamma,
            brightness=cfg.brightness,
            saturation=cfg.saturation,
            smooth=cfg.smooth,
            color_temp=cfg.color_temp,
            black_threshold=cfg.black_threshold,
            night_mode=cfg.night_mode,
            schedule_enabled=cfg.schedule_enabled,
            schedule=cfg.schedule,
            adaptive_enabled=cfg.adaptive_enabled,
            adaptive_min=cfg.adaptive_min,
            adaptive_max=cfg.adaptive_max,
            adaptive_speed=cfg.adaptive_speed,
            lamp_effect=cfg.lamp_effect,
            lamp_color=cfg.lamp_color,
            lamp_color2=cfg.lamp_color2,
            lamp_speed=cfg.lamp_speed,
            music_effect=cfg.music_effect,
            music_color=cfg.music_color,
            music_gain=cfg.music_gain,
        )
        self.statusBar().showMessage("Применено", 1200)

    # ── управление движком ────────────────────────────────────────────────

    def _on_start_stop(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self._stop_engine()
        else:
            self._start_engine(self._selected_mode())

    def _start_engine(self, mode: Mode) -> None:
        self._stop_engine()
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Настройки", str(e))
            return

        self._mode = mode
        self.thread = EngineThread(cfg, mode, self)
        self.thread.colorsReady.connect(self.preview.set_colors)
        self.thread.fpsChanged.connect(lambda f: self.lbl_fps.setText(f"{f:.1f} fps"))
        self.thread.backendReady.connect(
            lambda name: self.lbl_backend.setText(f"Бэкенд: {name}")
        )
        self.thread.failed.connect(self._on_engine_failed)
        self.thread.finished.connect(self._on_engine_finished)
        self.thread.start()

        names = {
            "live": "Подсветка",
            "lamp": "Лампа",
            "music": "Цветомузыка",
            "sides": "Тест сторон",
            "chase": "Бегущий диод",
            "off": "Гашение",
        }
        self.lbl_state.setText(f"{names[mode]}: работает")
        self.btn_start.setText("■ Стоп")
        self.btn_start.setStyleSheet(_BTN_STOP_QSS)
        self.btn_apply.setEnabled(mode in _MAIN_MODES)

    def _stop_engine(self) -> None:
        self._cancel_pending_apply()
        thread, self.thread = self.thread, None
        if thread is None:
            return
        thread.request_stop()
        thread.wait(8000)
        self._reset_running_ui()

    def _reset_running_ui(self) -> None:
        self._mode = None
        self.lbl_state.setText("Остановлено")
        self.lbl_fps.setText("")
        self.btn_start.setText("▶ Старт")
        self.btn_start.setStyleSheet(_BTN_START_QSS)
        self.btn_apply.setEnabled(False)

    def _on_engine_finished(self) -> None:
        # сигнал от уже заменённого потока игнорируем — иначе UI «останавливается»,
        # хотя новый движок работает (баг двойного нажатия «Старт»)
        if self.sender() is not self.thread:
            return
        self.thread = None
        self._reset_running_ui()

    def _on_engine_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Ошибка", message)

    # ── прочее ────────────────────────────────────────────────────────────

    def _on_autostart_toggled(self, enabled: bool) -> None:
        if self._loading:
            return
        try:
            if enabled:
                autostart.enable()
            else:
                autostart.disable()
        except OSError as e:
            QMessageBox.warning(self, "Автозапуск", f"Не удалось изменить автозапуск: {e}")
            self.ch_autostart.blockSignals(True)
            self.ch_autostart.setChecked(not enabled)
            self.ch_autostart.blockSignals(False)
            return
        self.statusBar().showMessage(
            "Автозапуск включён" if enabled else "Автозапуск выключен", 3000
        )

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


def run(minimized: bool = False) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Adalight")
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow()
    win.resize(960, 680)
    if minimized and win.tray is not None:
        # автозапуск: сразу включаем сохранённый режим, окно остаётся в трее
        win._start_engine(win._selected_mode())
    else:
        win.show()
    return app.exec()
