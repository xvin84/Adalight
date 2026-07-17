"""Главное окно приложения: вкладки настроек, предпросмотр, движок, трей.

Организация интерфейса:
- вкладка «Режим» показывает только настройки выбранного источника
  (захват / лампа / цветомузыка);
- «Устройство» — порт и геометрия ленты; «Изображение» — конвейер цвета;
- «Яркость» — адаптивность и расписание; «Система» — автозапуск и обновления.

Логика применения настроек:
- «мягкие» (цвет, эффекты, расписание, адаптивность, ночной режим) применяются
  к работающему движку мгновенно и без ресета платы;
- «жёсткие» (порт, диоды, геометрия, монитор, бэкенд, FPS) перезапускают
  подсветку автоматически через 5 секунд после последнего изменения;
- смена режима перезапускает сразу.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import (
    QPoint,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTime,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
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
    PRESET_PROFILES,
    START_CORNERS,
    Config,
    apply_preset,
    default_config_path,
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)
from ..device import list_serial_ports
from ..engine import Engine, Mode
from ..schedule import parse_time
from .anim import fade_in, fade_out_and_delete, make_pulse, slide_fade_in
from .gradient import GradientEditor
from .icons import icon
from .preview import LedPreview
from .theme import apply_theme

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
    "rainbow": "Радуга (бегущая)",
    "rainbow_static": "Радуга (статичная)",
    "breathing": "Дыхание",
    "fire": "Камин",
}
_MUSIC_EFFECT_LABELS = {"spectrum": "Спектр по периметру", "pulse": "Пульс от баса"}
_MAIN_MODES: tuple[Mode, ...] = ("live", "lamp", "music")
_PRESET_ICONS = {"Кино": "film", "Игра": "gamepad", "Работа": "briefcase"}
_THEME_LABELS = {"dark": "Тёмная", "light": "Светлая", "system": "Системная"}
_THEMES = tuple(_THEME_LABELS)
_BAUDS = ("115200", "230400", "460800", "500000", "921600", "1000000", "2000000")
_APPLY_DELAY_S = 5
_UPDATE_RETRY_MS = 30 * 60 * 1000  # повтор тихой проверки обновлений
_BOOT_RETRY_MAX = 30
_BOOT_RETRY_DELAY_MS = 10_000
_INSTANCE_KEY = "adalight-single-instance"

_BTN_START_QSS = (
    "QPushButton {background: #2e7d46; color: white; font-weight: 600;"
    " padding: 7px; border: none; border-radius: 6px;}"
    "QPushButton:hover {background: #379554;}"
    "QPushButton:pressed {background: #27693b;}"
)
_BTN_STOP_QSS = (
    "QPushButton {background: #8b2e2e; color: white; font-weight: 600;"
    " padding: 7px; border: none; border-radius: 6px;}"
    "QPushButton:hover {background: #a63a3a;}"
    "QPushButton:pressed {background: #772727;}"
)
_BTN_UPDATE_QSS = (
    "QPushButton {background: #b8860b; color: white; font-weight: 600;"
    " padding: 3px 10px; border: none; border-radius: 6px;}"
    "QPushButton:hover {background: #d09c1d;}"
)

_ABOUT_HTML = f"""
<h3>Adalight {__version__}</h3>
<p>Фоновая подсветка (ambilight) для LED-ленты: захват экрана, лампа
и цветомузыка. Windows и Linux/Wayland.</p>
<p>Протокол: Adalight (Arduino/ESP по serial).</p>
<p><a href="https://github.com/xvin84/Adalight">github.com/xvin84/Adalight</a><br>
Автор: xvin84 · Лицензия: MIT</p>
"""


class EngineThread(QThread):
    colorsReady = Signal(object)
    fpsChanged = Signal(float)
    backendReady = Signal(str)
    frameReady = Signal(object)
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
                on_frame=self.frameReady.emit,
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

    def identify(self, index: int) -> None:
        if self._engine is not None:
            self._engine.identify(index)


class UpdateCheckThread(QThread):
    """Фоновая проверка последнего релиза на GitHub."""

    result = Signal(str, str, str)  # версия, url страницы, url бинарника ('' если нет)
    failed = Signal(str)

    def run(self) -> None:
        try:
            version, page_url, asset_url = updates.fetch_latest()
        except Exception as e:  # noqa: BLE001 — сеть может падать чем угодно
            self.failed.emit(str(e))
            return
        self.result.emit(version, page_url, asset_url)


class UpdateDownloadThread(QThread):
    """Скачивание нового бинарника с прогрессом."""

    progress = Signal(int)  # проценты (или -1, если размер неизвестен)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, dest: Path, parent=None):
        super().__init__(parent)
        self._url = url
        self._dest = dest

    def run(self) -> None:
        try:
            updates.download(self._url, self._dest, self._on_progress)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        self.done.emit(str(self._dest))

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.emit(int(done * 100 / total) if total else -1)


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
    """Резервная программная иконка: тёмный экран с подсветкой по углам."""
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


def app_icon() -> QIcon:
    """Иконка приложения: из assets (в т.ч. внутри PyInstaller-сборки) или программная."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    png = base / "assets" / "icon.png"
    if png.is_file():
        return QIcon(str(png))
    return _make_icon()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Adalight {__version__}")
        self.setWindowIcon(app_icon())

        self.cfg = Config.load()
        self.thread: EngineThread | None = None
        self._mode: Mode | None = None
        self._quitting = False
        self._tray_tip_shown = False
        self._loading = True
        self._update_asset_url = ""
        self._update_page_url = ""
        self._update_version = ""
        self._update_ready_path: Path | None = None
        self._notified_version = ""
        self._booting = False
        self._boot_retry = 0

        # если бинарник переехал — молча чиним запись автозапуска
        try:
            if autostart.refresh_if_stale():
                self.statusBar().showMessage("Запись автозапуска обновлена", 4000)
        except OSError:
            pass

        self._apply_left = 0
        self._apply_timer = QTimer(self)
        self._apply_timer.setInterval(1000)
        self._apply_timer.timeout.connect(self._tick_apply)

        self._build_ui()
        self._apply_cfg_to_ui(self.cfg)
        self._refresh_profiles()
        self._build_tray()
        self._loading = False
        self._refresh_preview_layout()

        # восстановление геометрии окна и активной вкладки
        self._settings = QSettings("xvin84", "Adalight")
        self.resize(980, 640)
        geometry = self._settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.nav.setCurrentRow(int(self._settings.value("tab", 0)))
        # показать в списке последний применённый профиль (значения уже в конфиге)
        kind = self._settings.value("profile_kind", "")
        name = self._settings.value("profile_name", "")
        if kind and name and self._find_profile_index((kind, name)) >= 0:
            self._refresh_profiles(select=(kind, name))
            self._profile_baseline = self._cfg_from_ui()
            self._update_profile_dirty()

        # проверка обновлений: сразу после запуска и далее каждые 30 минут
        QTimer.singleShot(2000, lambda: self._check_updates(silent=True))
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(_UPDATE_RETRY_MS)
        self._update_check_timer.timeout.connect(lambda: self._check_updates(silent=True))
        self._update_check_timer.start()

    # ── построение интерфейса ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # левая колонка: вертикальная навигация + страницы настроек
        self.nav = QListWidget()
        self.nav.setObjectName("sidebar")
        self.nav.setFixedWidth(158)
        self.nav.setIconSize(QSize(20, 20))
        sections = (
            ("monitor", "Режим"),
            ("chip", "Устройство"),
            ("sliders", "Изображение"),
            ("sun", "Яркость"),
            ("gear", "Система"),
        )
        for icon_name, label in sections:
            self.nav.addItem(QListWidgetItem(icon(icon_name), label))

        self.pages = QStackedWidget()
        self.pages.addWidget(self._make_tab(self._tab_mode_content()))
        self.pages.addWidget(self._make_tab(self._group_connection(), self._group_leds()))
        self.pages.addWidget(self._make_tab(self._group_image()))
        self.pages.addWidget(self._make_tab(self._group_adaptive(), self._group_schedule()))
        self.pages.addWidget(
            self._make_tab(
                self._group_appearance(), self._group_system(), self._group_updates()
            )
        )
        self.pages.setMinimumWidth(340)
        self.pages.setMaximumWidth(430)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setCurrentRow(0)

        root.addWidget(self.nav, 0)
        root.addWidget(self.pages, 0)

        # правая колонка: профили, предпросмотр и управление
        right = QVBoxLayout()

        profiles_row = QHBoxLayout()
        profiles_row.addWidget(QLabel("Профиль:"))
        self.cb_profile = QComboBox()
        self.cb_profile.setMinimumWidth(160)
        self.cb_profile.setToolTip("Выбор профиля сразу применяет его настройки")
        self.cb_profile.activated.connect(self._on_profile_selected)
        self.btn_prof_update = QPushButton()
        self.btn_prof_update.setFixedWidth(36)
        self.btn_prof_update.clicked.connect(self._on_profile_update)
        btn_prof_save = QPushButton("Сохранить как…")
        btn_prof_save.setIcon(icon("save"))
        btn_prof_save.setToolTip("Сохранить текущие настройки как именованный профиль")
        btn_prof_save.clicked.connect(self._on_profile_save)
        btn_prof_del = QPushButton()
        btn_prof_del.setIcon(icon("trash"))
        btn_prof_del.setFixedWidth(36)
        btn_prof_del.setToolTip("Удалить выбранный профиль")
        btn_prof_del.clicked.connect(self._on_profile_delete)
        profiles_row.addWidget(self.cb_profile, 1)
        profiles_row.addWidget(self.btn_prof_update)
        profiles_row.addWidget(btn_prof_save)
        profiles_row.addWidget(btn_prof_del)
        right.addLayout(profiles_row)
        self._profile_baseline: Config | None = None
        self._update_profile_dirty()

        # статус-карточка: главное состояние программы одним взглядом
        hero = QFrame()
        hero.setObjectName("hero")
        hero_lay = QHBoxLayout(hero)
        hero_lay.setContentsMargins(14, 10, 14, 10)
        self.lbl_hero_dot = QLabel("●")
        self.lbl_hero_dot.setObjectName("heroDot")
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self.lbl_state = QLabel("Остановлено")
        self.lbl_state.setObjectName("heroState")
        self.lbl_hero_sub = QLabel("Нажмите «Старт», чтобы включить подсветку")
        self.lbl_hero_sub.setObjectName("heroSub")
        text_col.addWidget(self.lbl_state)
        text_col.addWidget(self.lbl_hero_sub)
        self.btn_start = QPushButton("▶ Старт")
        self.btn_start.setStyleSheet(_BTN_START_QSS)
        self.btn_start.setMinimumWidth(130)
        self.btn_start.clicked.connect(self._on_start_stop)
        hero_lay.addWidget(self.lbl_hero_dot)
        hero_lay.addLayout(text_col, 1)
        hero_lay.addWidget(self.btn_start)
        right.addWidget(hero)
        self._set_hero_dot("#6a6d73")
        # пульсация индикатора, пока подсветка работает
        self._dot_pulse = make_pulse(self.lbl_hero_dot)

        self.preview = LedPreview()
        self.preview.ledClicked.connect(self._on_led_clicked)
        right.addWidget(self.preview, 1)

        overlay = QHBoxLayout()
        self.ch_preview_screen = QCheckBox("Экран")
        self.ch_preview_screen.setToolTip("Показывать картинку экрана в предпросмотре")
        self.ch_preview_screen.toggled.connect(self._on_preview_options_changed)
        self.ch_preview_zones = QCheckBox("Зоны сбора цвета")
        self.ch_preview_zones.setToolTip(
            "Показывать области, из которых усредняется цвет каждого диода"
        )
        self.ch_preview_zones.toggled.connect(self._on_preview_options_changed)
        overlay.addStretch(1)
        overlay.addWidget(self.ch_preview_screen)
        overlay.addWidget(self.ch_preview_zones)
        overlay.addStretch(1)
        right.addLayout(overlay)

        controls = QHBoxLayout()
        self.btn_apply = QPushButton("Применить сейчас")
        self.btn_apply.setEnabled(False)
        self.btn_apply.setToolTip(
            "Перезапустить с новыми настройками, не дожидаясь автоприменения"
        )
        self.btn_apply.clicked.connect(lambda: self._start_engine(self._selected_mode()))
        self.btn_night = QPushButton("Ночной режим")
        self.btn_night.setIcon(icon("moon"))
        self.btn_night.setCheckable(True)
        self.btn_night.setToolTip(
            "Теплее (3400K), темнее (×0.6) и плавнее — поверх текущих настроек"
        )
        self.btn_night.toggled.connect(self._on_soft_changed)
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

        btn_save = QPushButton("Сохранить настройки")
        btn_save.setIcon(icon("save"))
        btn_save.clicked.connect(self._on_save)
        right.addWidget(btn_save)

        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self._backend_info = ""
        self._fps_text = ""
        self.lbl_pending = QLabel("")
        self.btn_update_bar = QPushButton("")
        self.btn_update_bar.setStyleSheet(_BTN_UPDATE_QSS)
        self.btn_update_bar.setVisible(False)
        self.btn_update_bar.clicked.connect(self._start_update)
        self.statusBar().addWidget(self.lbl_pending)
        self.statusBar().addPermanentWidget(self.btn_update_bar)

        # горячие клавиши
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._on_save)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self._quit)
        btn_save.setToolTip("Сохранить как текущие настройки (Ctrl+S)")

    # ── статус-карточка ───────────────────────────────────────────────────

    def _set_hero_dot(self, color: str) -> None:
        self.lbl_hero_dot.setStyleSheet(
            f"color: {color}; font-size: 20px; background: transparent;"
        )

    def _update_hero_sub(self) -> None:
        parts = [p for p in (self._backend_info, self._fps_text) if p]
        if parts:
            self.lbl_hero_sub.setText(" · ".join(parts))

    def _on_led_clicked(self, index: int) -> None:
        if self.thread is not None and self._mode in _MAIN_MODES:
            self.thread.identify(index)
            self._toast(f"Диод {index + 1} вспыхнул на ленте")
        else:
            self._toast("Запустите подсветку, чтобы подсветить диод на ленте")

    def _notify(self, title: str, text: str) -> None:
        """Системное уведомление из трея (если включено в настройках)."""
        if self.tray is not None and self.ch_notifications.isChecked():
            self.tray.showMessage(title, text, app_icon())

    def _toast(self, message: str) -> None:
        toast = QLabel(message, self)
        toast.setObjectName("toast")
        toast.adjustSize()
        end = QPoint(
            self.width() - toast.width() - 24, self.height() - toast.height() - 44
        )
        toast.show()
        toast.raise_()
        slide_fade_in(toast, end)
        QTimer.singleShot(2400, lambda: fade_out_and_delete(toast))

    def _on_nav_changed(self, index: int) -> None:
        if self.pages.currentIndex() == index:
            return
        self.pages.setCurrentIndex(index)
        fade_in(self.pages.currentWidget())

    @staticmethod
    def _make_tab(*widgets: QWidget) -> QScrollArea:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(12)
        for w in widgets:
            lay.addWidget(w)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    @staticmethod
    def _wrap_row(layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return w

    # ── вкладка «Режим» ───────────────────────────────────────────────────

    def _tab_mode_content(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        g = QGroupBox("Источник")
        form = QFormLayout(g)
        self.cb_mode = QComboBox()
        for value in MODES:
            self.cb_mode.addItem(_MODE_LABELS[value], value)
        self.cb_mode.setToolTip(
            "Захват экрана — ambilight по краям картинки;\n"
            "Лампа — эффекты без захвата; Цветомузыка — лента реагирует на звук.\n"
            "Смена режима на лету перезапускает подсветку сразу."
        )
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Режим:", self.cb_mode)
        lay.addWidget(g)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._group_capture())
        self.mode_stack.addWidget(self._group_lamp())
        self.mode_stack.addWidget(self._group_music())
        self.cb_mode.currentIndexChanged.connect(self._on_mode_page_changed)
        lay.addWidget(self.mode_stack)
        return box

    def _on_mode_page_changed(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        if not self._loading:
            fade_in(self.mode_stack.currentWidget())

    def _group_capture(self) -> QGroupBox:
        g = QGroupBox("Захват экрана")
        form = QFormLayout(g)

        self.cb_output = QComboBox()
        self.cb_output.setEditable(True)
        self.cb_output.currentTextChanged.connect(self._on_hard_changed)
        btn = QPushButton()
        btn.setIcon(icon("refresh"))
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
        self.sp_fps.setToolTip(
            "Сколько раз в секунду обновлять ленту. 60 — комфортно;\n"
            "реальный fps виден в статус-карточке."
        )
        self.sp_fps.valueChanged.connect(self._on_hard_changed)
        form.addRow("Целевой FPS:", self.sp_fps)

        self.ds_band = QDoubleSpinBox()
        self.ds_band.setRange(0.02, 0.5)
        self.ds_band.setSingleStep(0.01)
        self.ds_band.setToolTip("Толщина краевой полосы, доля экрана")
        # влияет на зоны сбора цвета — обновляем и предпросмотр
        self.ds_band.valueChanged.connect(self._on_geometry_changed)
        form.addRow("Полоса захвата:", self.ds_band)

        self.ds_window = QDoubleSpinBox()
        self.ds_window.setRange(0.01, 0.5)
        self.ds_window.setSingleStep(0.01)
        self.ds_window.setToolTip("Ширина окна одного диода, доля экрана")
        self.ds_window.valueChanged.connect(self._on_geometry_changed)
        form.addRow("Окно диода:", self.ds_window)
        return g

    def _group_lamp(self) -> QGroupBox:
        g = QGroupBox("Лампа")
        form = QFormLayout(g)
        self._lamp_form = form

        self.cb_lamp_effect = QComboBox()
        for value in LAMP_EFFECTS:
            self.cb_lamp_effect.addItem(_LAMP_EFFECT_LABELS[value], value)
        self.cb_lamp_effect.setToolTip(
            "Бегущая радуга вращается по периметру со скоростью «Скорость»,\n"
            "статичная — неподвижное распределение оттенков вдоль ленты."
        )
        self.cb_lamp_effect.currentIndexChanged.connect(self._on_lamp_effect_changed)
        form.addRow("Эффект:", self.cb_lamp_effect)

        self.btn_lamp_color = self._color_button("#ff9329")
        form.addRow("Цвет:", self.btn_lamp_color)

        self.sl_lamp_speed, row = self._slider_row(0, 100)
        self._lamp_speed_w = self._wrap_row(row)
        form.addRow("Скорость:", self._lamp_speed_w)

        self.gradient_editor = GradientEditor()
        self.gradient_editor.changed.connect(self._on_soft_changed)
        form.addRow("Точки:", self.gradient_editor)

        self._sync_lamp_rows()
        return g

    def _group_music(self) -> QGroupBox:
        g = QGroupBox("Цветомузыка")
        form = QFormLayout(g)
        self._music_form = form

        self.cb_music_effect = QComboBox()
        for value in MUSIC_EFFECTS:
            self.cb_music_effect.addItem(_MUSIC_EFFECT_LABELS[value], value)
        self.cb_music_effect.setToolTip(
            "Спектр: басы в начале ленты, высокие — в конце.\n"
            "Пульс: вся лента дышит одним цветом от энергии баса."
        )
        self.cb_music_effect.currentIndexChanged.connect(self._on_music_effect_changed)
        form.addRow("Эффект:", self.cb_music_effect)

        self.btn_music_color = self._color_button("#ff2d95")
        form.addRow("Цвет:", self.btn_music_color)

        self.sl_music_gain, row = self._slider_row(10, 500)
        self.sl_music_gain.setToolTip("Чувствительность: больше — ярче реакция на звук")
        form.addRow("Чувствительность:", self._wrap_row(row))

        self._sync_music_rows()
        return g

    def _on_lamp_effect_changed(self, *args) -> None:
        self._sync_lamp_rows()
        self._on_soft_changed()

    def _sync_lamp_rows(self) -> None:
        effect = self.cb_lamp_effect.currentData()
        rows = {
            self.btn_lamp_color: effect in ("solid", "breathing"),
            self._lamp_speed_w: effect in ("rainbow", "breathing", "fire"),
            self.gradient_editor: effect == "gradient",
        }
        for widget, visible in rows.items():
            label = self._lamp_form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)
            widget.setVisible(visible)

    def _on_music_effect_changed(self, *args) -> None:
        self._sync_music_rows()
        self._on_soft_changed()

    def _sync_music_rows(self) -> None:
        show_color = self.cb_music_effect.currentData() == "pulse"
        label = self._music_form.labelForField(self.btn_music_color)
        if label is not None:
            label.setVisible(show_color)
        self.btn_music_color.setVisible(show_color)

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

    # ── вкладка «Устройство» ──────────────────────────────────────────────

    def _group_connection(self) -> QGroupBox:
        g = QGroupBox("Подключение")
        form = QFormLayout(g)

        self.cb_port = QComboBox()
        self.cb_port.setEditable(True)
        self.cb_port.currentTextChanged.connect(self._on_hard_changed)
        btn = QPushButton()
        btn.setIcon(icon("refresh"))
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
        self.cb_corner.setToolTip(
            "Угол, где первый диод ленты (отмечен кольцом в предпросмотре)"
        )
        self.cb_corner.currentIndexChanged.connect(self._on_geometry_changed)
        form.addRow("Начальный угол:", self.cb_corner)

        self.cb_direction = QComboBox()
        for value in DIRECTIONS:
            self.cb_direction.addItem(_DIRECTION_LABELS[value], value)
        self.cb_direction.setToolTip("Куда идёт лента от первого диода (глядя на экран)")
        self.cb_direction.currentIndexChanged.connect(self._on_geometry_changed)
        form.addRow("Направление:", self.cb_direction)

        self.ch_flip_x = QCheckBox("Инверсия лево/право")
        self.ch_flip_y = QCheckBox("Инверсия верх/низ")
        self.ch_flip_x.toggled.connect(self._on_geometry_changed)
        self.ch_flip_y.toggled.connect(self._on_geometry_changed)
        form.addRow(self.ch_flip_x)
        form.addRow(self.ch_flip_y)
        return g

    # ── вкладка «Изображение» ─────────────────────────────────────────────

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
        self.sl_gamma.setToolTip(
            "Кривая яркости: 2.2 — стандарт; больше — глубже тени, сочнее"
        )
        form.addRow("Гамма:", row)
        self.sl_bright, row = self._slider_row(5, 150)
        self.sl_bright.setToolTip(
            "Основная яркость. Используется как значение «по умолчанию» "
            "для расписания и как база для адаптивной яркости."
        )
        form.addRow("Яркость:", row)
        self.sl_sat, row = self._slider_row(0, 250)
        self.sl_sat.setToolTip("1.00 — как на экране; больше — цвета сочнее")
        form.addRow("Насыщенность:", row)
        self.sl_smooth, row = self._slider_row(0, 95)
        self.sl_smooth.setToolTip(
            "Инерция смены цвета: 0 — мгновенно, больше — плавнее (для кино)"
        )
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

        # баланс белого: калибровка каналов, чтобы белый на ленте был белым
        self.sl_wb_r, row = self._slider_row(20, 150)
        form.addRow("Баланс R:", row)
        self.sl_wb_g, row = self._slider_row(20, 150)
        form.addRow("Баланс G:", row)
        self.sl_wb_b, row = self._slider_row(20, 150)
        form.addRow("Баланс B:", row)
        for s in (self.sl_wb_r, self.sl_wb_g, self.sl_wb_b):
            s.setToolTip(
                "Множитель канала (1.00 = без изменений). Включите белую «лампу» "
                "и подстройте, чтобы лента светила чистым белым."
            )
        return g

    # ── вкладка «Яркость» ─────────────────────────────────────────────────

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

    # ── вкладка «Система» ─────────────────────────────────────────────────

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

        self.ch_notifications = QCheckBox("Уведомления в трее")
        self.ch_notifications.setToolTip(
            "Сообщать о включении/выключении подсветки (когда окно скрыто) "
            "и о выходе новых версий"
        )
        self.ch_notifications.toggled.connect(self._on_soft_changed)
        lay.addWidget(self.ch_notifications)

        row = QHBoxLayout()
        btn_export = QPushButton("Экспорт настроек…")
        btn_export.setToolTip("Сохранить все настройки в JSON-файл")
        btn_export.clicked.connect(self._on_export)
        btn_import = QPushButton("Импорт настроек…")
        btn_import.setToolTip("Загрузить настройки из JSON-файла")
        btn_import.clicked.connect(self._on_import)
        row.addWidget(btn_export)
        row.addWidget(btn_import)
        lay.addLayout(row)

        btn_wizard = QPushButton("Мастер настройки…")
        btn_wizard.setIcon(icon("wand"))
        btn_wizard.setToolTip("Пошаговая настройка: порт → диоды → проверка сторон")
        btn_wizard.clicked.connect(self._open_wizard)
        lay.addWidget(btn_wizard)

        btn_about = QPushButton("О программе")
        btn_about.clicked.connect(self._show_about)
        lay.addWidget(btn_about)
        return g

    def _open_wizard(self) -> None:
        from .wizard import SetupWizard

        SetupWizard(self).exec()

    # ── профили и импорт/экспорт ──────────────────────────────────────────

    def _refresh_profiles(self, select: tuple[str, str] | None = None) -> None:
        """Наполняет комбо: встроенные пресеты, разделитель, профили пользователя."""
        self.cb_profile.blockSignals(True)
        self.cb_profile.clear()
        for name in PRESET_PROFILES:
            self.cb_profile.addItem(icon(_PRESET_ICONS[name]), name, ("preset", name))
        users = list_profiles()
        if users:
            self.cb_profile.insertSeparator(self.cb_profile.count())
            for name in users:
                self.cb_profile.addItem(icon("user"), name, ("user", name))
        self.cb_profile.setCurrentIndex(self._find_profile_index(select) if select else -1)
        self.cb_profile.blockSignals(False)

    def _find_profile_index(self, data: tuple[str, str]) -> int:
        # QComboBox.findData не сравнивает python-кортежи — ищем вручную
        for i in range(self.cb_profile.count()):
            if self.cb_profile.itemData(i) == data:
                return i
        return -1

    def _apply_config(self, cfg: Config, source: str) -> None:
        """Применить готовый Config: в UI, к теме, к движку — и сохранить.

        Сохранение обязательно: иначе после перезапуска (в т.ч. автозапуска)
        программа вернётся к старым настройкам.
        """
        self._loading = True
        self._apply_cfg_to_ui(cfg)
        self._loading = False
        self._refresh_preview_layout()
        self._sync_lamp_rows()
        self._sync_music_rows()
        apply_theme(QApplication.instance(), cfg.theme)
        cfg.save()
        self.cfg = cfg
        if self.thread is not None:
            self._start_engine(self._selected_mode())
        self._toast(f"{source}: применено и сохранено")

    def _on_profile_selected(self, index: int) -> None:
        data = self.cb_profile.itemData(index)
        if data:
            self._select_profile(*data)

    def _select_profile(self, kind: str, name: str) -> None:
        try:
            if kind == "preset":
                # пресет накладывается поверх текущих настроек: железо не трогаем
                cfg = apply_preset(self._cfg_from_ui(), name)
            else:
                cfg = load_profile(name)
            cfg.validate()
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Профиль", f"Не удалось применить профиль: {e}")
            return
        self._refresh_profiles(select=(kind, name))
        self._settings.setValue("profile_kind", kind)
        self._settings.setValue("profile_name", name)
        self._apply_config(cfg, f"Профиль «{name}»")
        # базовая точка для индикатора правок — после прохода через UI,
        # чтобы округления слайдеров не считались изменениями
        self._profile_baseline = self._cfg_from_ui()
        self._update_profile_dirty()

    def _update_profile_dirty(self) -> None:
        """Иконка кнопки сохранения профиля: жёлтая, если есть несохранённые правки."""
        data = self.cb_profile.currentData()
        if not data or self._profile_baseline is None:
            self.btn_prof_update.setIcon(icon("save"))
            self.btn_prof_update.setEnabled(False)
            self.btn_prof_update.setToolTip("Профиль не выбран")
            return
        dirty = self._cfg_from_ui() != self._profile_baseline
        kind, name = data
        self.btn_prof_update.setEnabled(dirty)
        if not dirty:
            self.btn_prof_update.setIcon(icon("save"))
            self.btn_prof_update.setToolTip(f"Профиль «{name}» сохранён")
        else:
            self.btn_prof_update.setIcon(icon("save", color="#e0a030"))
            self.btn_prof_update.setToolTip(
                f"Есть несохранённые изменения — сохранить в профиль «{name}»"
                if kind == "user"
                else "Настройки отличаются от пресета — сохранить как свой профиль…"
            )

    def _on_profile_update(self) -> None:
        data = self.cb_profile.currentData()
        if not data or data[0] != "user":
            self._on_profile_save()  # пресет перезаписать нельзя — «Сохранить как…»
            return
        name = data[1]
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
            save_profile(name, cfg)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Профиль", str(e))
            return
        self._profile_baseline = cfg
        self._update_profile_dirty()
        self._toast(f"Профиль «{name}» обновлён")

    def _on_profile_save(self) -> None:
        name, ok = QInputDialog.getText(self, "Профиль", "Имя профиля:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in PRESET_PROFILES:
            QMessageBox.warning(
                self, "Профиль", f"«{name}» — встроенный пресет, выберите другое имя."
            )
            return
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
            save_profile(name, cfg)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Профиль", str(e))
            return
        self._refresh_profiles(select=("user", name))
        self._settings.setValue("profile_kind", "user")
        self._settings.setValue("profile_name", name)
        self._profile_baseline = self._cfg_from_ui()
        self._update_profile_dirty()
        self._toast(f"Профиль «{name}» сохранён")

    def _on_profile_delete(self) -> None:
        data = self.cb_profile.currentData()
        if not data:
            return
        kind, name = data
        if kind == "preset":
            QMessageBox.information(
                self, "Профиль", "Встроенные пресеты удалить нельзя."
            )
            return
        answer = QMessageBox.question(
            self, "Профиль", f"Удалить профиль «{name}»?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_profile(name)
        self._refresh_profiles()
        self._toast(f"Профиль «{name}» удалён")

    def _on_export(self) -> None:
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Экспорт", str(e))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт настроек", "adalight-config.json", "JSON (*.json)"
        )
        if not path:
            return
        cfg.save(Path(path))
        self._toast("Настройки экспортированы")

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт настроек", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            cfg = Config.load(Path(path))
            cfg.validate()
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Импорт", f"Не удалось загрузить настройки: {e}")
            return
        self._apply_config(cfg, "Импорт")

    def _group_appearance(self) -> QGroupBox:
        g = QGroupBox("Внешний вид")
        form = QFormLayout(g)
        self.cb_theme = QComboBox()
        for value in _THEMES:
            self.cb_theme.addItem(_THEME_LABELS[value], value)
        self.cb_theme.setToolTip("Применяется сразу, без перезапуска")
        self.cb_theme.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow("Тема:", self.cb_theme)
        return g

    def _on_theme_changed(self, *args) -> None:
        if self._loading:
            return
        apply_theme(QApplication.instance(), self.cb_theme.currentData())

    def _on_preview_options_changed(self, *args) -> None:
        self.preview.show_screen = self.ch_preview_screen.isChecked()
        self.preview.show_zones = self.ch_preview_zones.isChecked()
        if not self.preview.show_screen:
            self.preview.clear_frame()
        self.preview.update()
        self._on_soft_changed()

    def _group_updates(self) -> QGroupBox:
        g = QGroupBox("Обновления")
        lay = QVBoxLayout(g)
        self.lbl_update = QLabel(f"Текущая версия: {__version__}")
        lay.addWidget(self.lbl_update)
        self.btn_update = QPushButton("Проверить обновления")
        self.btn_update.clicked.connect(self._on_update_button)
        lay.addWidget(self.btn_update)
        return g

    def _show_about(self) -> None:
        QMessageBox.about(self, "О программе", _ABOUT_HTML)

    # ── обновления ────────────────────────────────────────────────────────

    def _on_update_button(self) -> None:
        if self._update_asset_url or self._update_page_url:
            self._start_update()
        else:
            self._check_updates()

    def _check_updates(self, silent: bool = False) -> None:
        self._update_thread = UpdateCheckThread(self)
        self._update_thread.result.connect(self._on_update_result)
        if not silent:
            # тихие сбои сети игнорируем — следующая попытка через 30 минут
            self._update_thread.failed.connect(self._on_update_check_failed)
            self.lbl_update.setText("Проверяю…")
        self._update_thread.start()

    def _on_update_check_failed(self, message: str) -> None:
        self.lbl_update.setText("Не удалось связаться с GitHub — попробуйте позже")
        self.lbl_update.setToolTip(message)

    def _on_update_result(self, version: str, page_url: str, asset_url: str) -> None:
        self.lbl_update.setToolTip("")
        if not updates.is_newer(version, __version__):
            self.lbl_update.setText(f"Текущая версия: {__version__} — последняя")
            return
        self._update_version = version
        self._update_page_url = page_url
        self._update_asset_url = asset_url
        self.lbl_update.setText(f"Доступна версия {version}")
        self.btn_update.setText(f"⬇ Обновить до v{version}")
        self.btn_update_bar.setText(f"⬇ Доступна v{version}")
        self.btn_update_bar.setVisible(True)
        if version != self._notified_version:
            self._notified_version = version
            self._notify(
                f"Доступна версия {version}",
                "Откройте окно и нажмите кнопку обновления в правом нижнем углу.",
            )

    def _start_update(self) -> None:
        if not (updates.can_self_update() and self._update_asset_url):
            # из исходников или без бинарника под эту ОС — открываем страницу релиза
            QDesktopServices.openUrl(QUrl(self._update_page_url))
            return
        if self._update_ready_path is not None and self._update_ready_path.is_file():
            # уже скачано — не качаем повторно, сразу предлагаем перезапуск
            self._confirm_and_restart()
            return
        self.btn_update.setEnabled(False)
        self.btn_update_bar.setEnabled(False)
        self._dl_thread = UpdateDownloadThread(
            self._update_asset_url, updates.staging_path(), self
        )
        self._dl_thread.progress.connect(self._on_update_progress)
        self._dl_thread.done.connect(self._on_update_downloaded)
        self._dl_thread.failed.connect(self._on_update_failed)
        self._dl_thread.start()

    def _on_update_progress(self, pct: int) -> None:
        text = f"Скачивание… {pct}%" if pct >= 0 else "Скачивание…"
        self.btn_update.setText(text)
        self.btn_update_bar.setText(f"⬇ {pct}%" if pct >= 0 else "⬇ …")

    def _on_update_downloaded(self, path: str) -> None:
        self._update_ready_path = Path(path)
        self._confirm_and_restart()

    def _confirm_and_restart(self) -> None:
        answer = QMessageBox.question(
            self,
            "Обновление",
            f"Версия {self._update_version} скачана.\nПерезапустить приложение сейчас?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            # файл сохранён — при следующем клике перезапустим без скачивания
            self.btn_update.setEnabled(True)
            self.btn_update_bar.setEnabled(True)
            self.btn_update.setText(f"↻ Перезапустить для v{self._update_version}")
            self.btn_update_bar.setText(f"↻ v{self._update_version} готова")
            self._toast("Обновление скачано — перезапустите, когда будет удобно")
            return
        self._stop_engine()
        try:
            updates.apply_and_restart(self._update_ready_path)
        except OSError as e:
            self._update_ready_path = None
            self._on_update_failed(str(e))
            return
        self._quit()

    def _on_update_failed(self, message: str) -> None:
        self.btn_update.setEnabled(True)
        self.btn_update_bar.setEnabled(True)
        self.btn_update.setText(f"⬇ Обновить до v{self._update_version}")
        self.btn_update_bar.setText(f"⬇ Доступна v{self._update_version}")
        QMessageBox.warning(
            self,
            "Обновление",
            f"Автообновление не удалось: {message}\nОткрою страницу релиза.",
        )
        QDesktopServices.openUrl(QUrl(self._update_page_url))

    # ── трей ──────────────────────────────────────────────────────────────

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
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
        profiles_menu = QMenu("Профили", menu)
        profiles_menu.aboutToShow.connect(
            lambda: self._fill_tray_profiles(profiles_menu)
        )
        act_about = QAction("О программе", menu)
        act_about.triggered.connect(self._show_about)
        act_quit = QAction("Выход", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addAction(act_start)
        menu.addAction(act_night)
        menu.addMenu(profiles_menu)
        menu.addSeparator()
        menu.addAction(act_about)
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
        self.sl_wb_r.setValue(round(cfg.wb_r * 100))
        self.sl_wb_g.setValue(round(cfg.wb_g * 100))
        self.sl_wb_b.setValue(round(cfg.wb_b * 100))
        self.btn_night.setChecked(cfg.night_mode)

        self.cb_theme.setCurrentIndex(_THEMES.index(cfg.theme))
        self.ch_preview_screen.setChecked(cfg.preview_screen)
        self.ch_preview_zones.setChecked(cfg.preview_zones)
        self.ch_notifications.setChecked(cfg.notifications)
        self.preview.show_screen = cfg.preview_screen
        self.preview.show_zones = cfg.preview_zones

        self.cb_mode.setCurrentIndex(MODES.index(cfg.mode))
        self.mode_stack.setCurrentIndex(MODES.index(cfg.mode))
        self.cb_lamp_effect.setCurrentIndex(LAMP_EFFECTS.index(cfg.lamp_effect))
        self._set_button_color(self.btn_lamp_color, cfg.lamp_color)
        self.gradient_editor.set_stops(cfg.lamp_gradient)
        self.sl_lamp_speed.setValue(round(cfg.lamp_speed * 100))
        self.cb_music_effect.setCurrentIndex(MUSIC_EFFECTS.index(cfg.music_effect))
        self._set_button_color(self.btn_music_color, cfg.music_color)
        self.sl_music_gain.setValue(round(cfg.music_gain * 100))
        self._sync_lamp_rows()
        self._sync_music_rows()

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
            wb_r=self.sl_wb_r.value() / 100,
            wb_g=self.sl_wb_g.value() / 100,
            wb_b=self.sl_wb_b.value() / 100,
            night_mode=self.btn_night.isChecked(),
            mode=self.cb_mode.currentData(),
            lamp_effect=self.cb_lamp_effect.currentData(),
            lamp_color=self.btn_lamp_color.property("color_value"),
            lamp_gradient=self.gradient_editor.stops(),
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
            theme=self.cb_theme.currentData(),
            preview_screen=self.ch_preview_screen.isChecked(),
            preview_zones=self.ch_preview_zones.isChecked(),
            notifications=self.ch_notifications.isChecked(),
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
        self._update_profile_dirty()
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
        self._update_profile_dirty()
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
            white_balance=(cfg.wb_r, cfg.wb_g, cfg.wb_b),
            night_mode=cfg.night_mode,
            schedule_enabled=cfg.schedule_enabled,
            schedule=cfg.schedule,
            adaptive_enabled=cfg.adaptive_enabled,
            adaptive_min=cfg.adaptive_min,
            adaptive_max=cfg.adaptive_max,
            adaptive_speed=cfg.adaptive_speed,
            lamp_effect=cfg.lamp_effect,
            lamp_color=cfg.lamp_color,
            lamp_gradient=cfg.lamp_gradient,
            lamp_speed=cfg.lamp_speed,
            music_effect=cfg.music_effect,
            music_color=cfg.music_color,
            music_gain=cfg.music_gain,
            preview_screen=cfg.preview_screen,
        )
        self.statusBar().showMessage("Применено", 1200)

    # ── управление движком ────────────────────────────────────────────────

    def _on_start_stop(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self._stop_engine()
        else:
            self._start_engine(self._selected_mode())

    def _start_engine(self, mode: Mode) -> None:
        self._stop_engine(quiet=True)
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Настройки", str(e))
            return

        self._mode = mode
        self.thread = EngineThread(cfg, mode, self)
        self.thread.colorsReady.connect(self.preview.set_colors)
        self.thread.colorsReady.connect(self._mark_boot_ok)
        self.thread.frameReady.connect(self.preview.set_frame)
        self.thread.fpsChanged.connect(self._on_fps)
        self.thread.backendReady.connect(self._on_backend_info)
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
        self.lbl_state.setText(names[mode])
        self._backend_info = ""
        self._fps_text = ""
        self.lbl_hero_sub.setText("Запуск…")
        self._set_hero_dot("#2ecc71")
        self._dot_pulse.start()
        if mode in _MAIN_MODES and self.isHidden():
            self._notify("Подсветка включена", f"Режим: {names[mode]}")
        self.btn_start.setText("■ Стоп")
        self.btn_start.setStyleSheet(_BTN_STOP_QSS)
        self.btn_apply.setEnabled(mode in _MAIN_MODES)

    def _on_fps(self, fps: float) -> None:
        self._fps_text = f"{fps:.1f} fps"
        self._update_hero_sub()

    def _on_backend_info(self, name: str) -> None:
        self._backend_info = name
        self._update_hero_sub()

    def _stop_engine(self, quiet: bool = False) -> None:
        self._cancel_pending_apply()
        thread, self.thread = self.thread, None
        if thread is None:
            return
        thread.request_stop()
        thread.wait(8000)
        self._reset_running_ui(notify=not quiet)

    def _reset_running_ui(self, notify: bool = True) -> None:
        prev_mode = self._mode
        self._mode = None
        if notify and prev_mode in _MAIN_MODES and self.isHidden():
            self._notify("Подсветка выключена", "Лента погашена.")
        self.lbl_state.setText("Остановлено")
        self.lbl_hero_sub.setText("Нажмите «Старт», чтобы включить подсветку")
        self._set_hero_dot("#6a6d73")
        self._dot_pulse.stop()
        effect = self.lbl_hero_dot.graphicsEffect()
        if effect is not None:
            effect.setProperty("opacity", 1.0)
        self._backend_info = ""
        self._fps_text = ""
        self.btn_start.setText("▶ Старт")
        self.btn_start.setStyleSheet(_BTN_START_QSS)
        self.btn_apply.setEnabled(False)
        self.preview.clear_frame()

    def _on_engine_finished(self) -> None:
        # сигнал от уже заменённого потока игнорируем — иначе UI «останавливается»,
        # хотя новый движок работает (баг двойного нажатия «Старт»)
        if self.sender() is not self.thread:
            return
        self.thread = None
        self._reset_running_ui()

    def _on_engine_failed(self, message: str) -> None:
        if self._booting and self._boot_retry < _BOOT_RETRY_MAX:
            # автозапуск при входе в систему: порт/монитор могли ещё не проснуться —
            # повторяем каждые 10 секунд вместо модальной ошибки в скрытом окне
            self._boot_retry += 1
            self.lbl_state.setText(f"Ожидание устройства… (попытка {self._boot_retry})")
            if self.tray is not None and self._boot_retry == 1:
                self.tray.showMessage(
                    "Adalight",
                    f"Пока не получилось запустить ({message}). "
                    "Пробую снова каждые 10 секунд.",
                )
            QTimer.singleShot(_BOOT_RETRY_DELAY_MS, self._retry_boot)
            return
        self._booting = False
        self._show_friendly_error(message)

    def _show_friendly_error(self, message: str) -> None:
        """Ошибка человеческим языком + подсказки; технические детали — по кнопке."""
        low = message.lower()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Ошибка")
        if "порт" in low or "serial" in low:
            box.setText("Не удалось подключиться к устройству.")
            box.setInformativeText(
                "• Проверьте USB-кабель (бывают кабели «только зарядка»)\n"
                "• Выберите другой порт: Устройство → Порт → кнопка обновления\n"
                "• Порт может быть занят другой программой — закройте её\n"
                "• Скорость должна совпадать с прошивкой"
            )
        elif any(w in low for w in ("захват", "монитор", "кадр", "dxcam", "bettercam",
                                    "mss", "wf-recorder", "grim")):
            box.setText("Не удалось захватить экран.")
            box.setInformativeText(
                "• Попробуйте другой бэкенд: Режим → Бэкенд\n"
                "• Проверьте номер монитора\n"
                "• На Wayland нужен установленный wf-recorder"
            )
        elif any(w in low for w in ("звук", "loopback", "soundcard", "аудио")):
            box.setText("Не удалось захватить системный звук.")
            box.setInformativeText(
                "• Проверьте, что в системе выбрано устройство вывода звука\n"
                "• Включите музыку и попробуйте ещё раз"
            )
        else:
            box.setText("Что-то пошло не так.")
        box.setDetailedText(message)
        box.exec()

    def _retry_boot(self) -> None:
        if self.thread is None:  # пользователь мог уже запустить/остановить вручную
            self._start_engine(self._selected_mode())

    def _mark_boot_ok(self, *args) -> None:
        self._booting = False
        self._boot_retry = 0

    def start_minimized(self) -> None:
        """Старт из автозагрузки: подсветка включается, окно остаётся в трее."""
        self._booting = True
        self._start_engine(self._selected_mode())

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
        self._toast("Автозапуск включён" if enabled else "Автозапуск выключен")

    def _on_save(self) -> None:
        cfg = self._cfg_from_ui()
        try:
            cfg.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Настройки", str(e))
            return
        cfg.save()
        self.cfg = cfg
        self._toast("Настройки сохранены")

    def _fill_tray_profiles(self, menu: QMenu) -> None:
        menu.clear()
        for name in PRESET_PROFILES:
            menu.addAction(
                icon(_PRESET_ICONS[name]),
                name,
                lambda n=name: self._select_profile("preset", n),
            )
        users = list_profiles()
        if users:
            menu.addSeparator()
        for name in users:
            menu.addAction(
                icon("user"), name, lambda n=name: self._select_profile("user", n)
            )

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("tab", self.nav.currentRow())
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
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    # одиночный экземпляр: повторный запуск показывает окно уже работающей программы
    probe = QLocalSocket()
    probe.connectToServer(_INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(_INSTANCE_KEY)  # уборка сокета после аварийного выхода
    server = QLocalServer()
    server.listen(_INSTANCE_KEY)

    first_run = not default_config_path().is_file()
    apply_theme(app, Config.load().theme)
    win = MainWindow()
    server.newConnection.connect(win._show_from_tray)
    if minimized and win.tray is not None:
        win.start_minimized()  # подсветка включается, окно остаётся в трее
    else:
        win.show()
        if first_run:
            QTimer.singleShot(400, win._open_wizard)
    return app.exec()
