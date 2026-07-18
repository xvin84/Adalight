"""Окно менеджера плагинов: два вида — «Установленные» и «Каталог».

Идея как в Factorio: единое место, где видно все плагины, можно включить/
выключить, настроить любой из них (по его settings_schema или встроенному
виджету) и поставить новый из каталога.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..plugins import schema_defaults
from .icons import icon
from .notification_settings import NotificationSettingsWidget
from .plugin_settings import SettingsForm


class PluginManagerWindow(QDialog):
    """Контроллер (обычно MainWindow) даёт данные и применяет изменения."""

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctrl = controller
        self._loading = False
        self._settings_widget: QWidget | None = None
        self._catalog_entries: list = []
        self.setWindowTitle("Плагины")
        self.setMinimumSize(760, 500)

        root = QVBoxLayout(self)

        # переключатель видов
        seg = QHBoxLayout()
        self.btn_installed = QPushButton("Установленные")
        self.btn_catalog = QPushButton("Каталог")
        group = QButtonGroup(self)
        for i, btn in enumerate((self.btn_installed, self.btn_catalog)):
            btn.setCheckable(True)
            btn.setObjectName("segBtn")
            group.addButton(btn, i)
            seg.addWidget(btn)
        seg.addStretch(1)
        self.btn_installed.setChecked(True)
        group.idClicked.connect(lambda i: self.stack.setCurrentIndex(i))
        root.addLayout(seg)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_installed_page())
        self.stack.addWidget(self._build_catalog_page())
        root.addWidget(self.stack, 1)

        self.refresh_installed()

    # ── вид «Установленные» ───────────────────────────────────────────────

    def _build_installed_page(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)

        self.list = QListWidget()
        self.list.setObjectName("pluginList")
        self.list.setFixedWidth(230)
        self.list.currentRowChanged.connect(self._on_select)
        lay.addWidget(self.list)

        right = QWidget()
        self.detail = QVBoxLayout(right)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("heroState")
        self.lbl_meta = QLabel()
        self.lbl_meta.setObjectName("heroSub")
        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.ch_enabled = QCheckBox("Включён")
        self.ch_enabled.toggled.connect(self._on_enabled_toggled)
        self.lbl_err = QLabel()
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setObjectName("hintLabel")
        self.lbl_err.hide()

        self.settings_host = QVBoxLayout()

        for w in (self.lbl_title, self.lbl_meta, self.lbl_desc, self.ch_enabled, self.lbl_err):
            self.detail.addWidget(w)
        self.detail.addLayout(self.settings_host)
        self.detail.addStretch(1)

        bottom = QHBoxLayout()
        btn_dir = QPushButton("Открыть папку плагинов")
        btn_dir.clicked.connect(self.ctrl.open_plugins_dir)
        self.btn_delete = QPushButton("Удалить")
        self.btn_delete.setIcon(icon("trash"))
        self.btn_delete.clicked.connect(self._on_delete)
        bottom.addWidget(btn_dir)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_delete)
        self.detail.addLayout(bottom)

        lay.addWidget(right, 1)
        return page

    def refresh_installed(self) -> None:
        prev = self.list.currentRow()
        self.list.clear()
        cfg = self.ctrl.plugins_cfg()
        for loaded in self.ctrl.manager.plugins:
            enabled = bool(cfg.get(loaded.name, {}).get("enabled", False))
            mark = "⚠" if loaded.error else ("●" if enabled else "○")
            item = QListWidgetItem(f"{mark}  {loaded.title}")
            item.setData(Qt.ItemDataRole.UserRole, loaded.name)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(min(max(prev, 0), self.list.count() - 1))

    def _current_loaded(self):
        item = self.list.currentItem()
        if item is None:
            return None
        name = item.data(Qt.ItemDataRole.UserRole)
        return self.ctrl.manager.get(name)

    def _on_select(self, _row: int) -> None:
        loaded = self._current_loaded()
        if loaded is None:
            return
        self._loading = True
        badge = "встроенный" if loaded.builtin else "установленный"
        ver = f" · v{loaded.version}" if loaded.version else ""
        self.lbl_title.setText(loaded.title)
        self.lbl_meta.setText(f"{badge}{ver}")
        self.lbl_desc.setText(loaded.description or loaded.name)
        self.btn_delete.setVisible(not loaded.builtin and loaded.path is not None)

        if loaded.error:
            self.lbl_err.setText(f"⚠ Ошибка: {loaded.error}")
            self.lbl_err.show()
        else:
            self.lbl_err.hide()

        cfg = self.ctrl.plugins_cfg()
        entry = cfg.get(loaded.name, {})
        self.ch_enabled.setEnabled(loaded.plugin is not None)
        self.ch_enabled.setChecked(bool(entry.get("enabled", False)))
        self._build_settings(loaded, entry)
        self._loading = False

    def _clear_settings_widget(self) -> None:
        if self._settings_widget is not None:
            self._settings_widget.setParent(None)
            self._settings_widget.deleteLater()
            self._settings_widget = None

    def _build_settings(self, loaded, entry: dict) -> None:
        self._clear_settings_widget()
        widget: QWidget | None = None
        if loaded.name == "notifications" and loaded.plugin is not None:
            widget = NotificationSettingsWidget()
            values = {**self.ctrl.notif_defaults(), **entry}
            widget.set_values(values)
            widget.changed.connect(self._on_settings_changed)
            widget.flashTest.connect(lambda: self.ctrl.flash_test(self._gather_entry()))
            widget.dragTest.connect(lambda: self.ctrl.flash_test(self._gather_entry()))
        elif loaded.schema:
            form = SettingsForm(loaded.schema)
            if form.has_fields():
                values = {**schema_defaults(loaded.schema), **entry}
                form.set_values(values)
                form.changed.connect(self._on_settings_changed)
                widget = form
        if widget is None:
            widget = QLabel("У этого плагина нет настроек.")
            widget.setObjectName("heroSub")
        self._settings_widget = widget
        self.settings_host.addWidget(widget)

    def _gather_entry(self) -> dict:
        """Собрать полную запись конфига текущего плагина из UI."""
        entry = {"enabled": self.ch_enabled.isChecked()}
        w = self._settings_widget
        if isinstance(w, (NotificationSettingsWidget, SettingsForm)):
            entry.update(w.values())
        return entry

    def _apply_current(self) -> None:
        loaded = self._current_loaded()
        if loaded is not None:
            self.ctrl.apply_plugin_entry(loaded.name, self._gather_entry())

    def _on_enabled_toggled(self, _checked: bool) -> None:
        if self._loading:
            return
        self._apply_current()
        loaded = self._current_loaded()
        if loaded is not None:  # обновить значок ●/○ в списке
            item = self.list.currentItem()
            mark = "⚠" if loaded.error else ("●" if _checked else "○")
            item.setText(f"{mark}  {loaded.title}")

    def _on_settings_changed(self) -> None:
        if self._loading:
            return
        self._apply_current()

    def _on_delete(self) -> None:
        loaded = self._current_loaded()
        if loaded is None or loaded.path is None:
            return
        if QMessageBox.question(
            self, "Удалить плагин",
            f"Удалить файл плагина «{loaded.title}»?\n{loaded.path}",
        ) != QMessageBox.StandardButton.Yes:
            return
        if self.ctrl.delete_plugin(loaded):
            self.refresh_installed()

    # ── вид «Каталог» ─────────────────────────────────────────────────────

    def _build_catalog_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск плагинов…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render_catalog)
        self.btn_reload = QPushButton("Загрузить")
        self.btn_reload.setIcon(icon("refresh"))
        self.btn_reload.clicked.connect(self._load_catalog)
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_reload)
        lay.addLayout(top)

        warn = QLabel(
            "Плагин — это код, который выполняется на вашем компьютере. "
            "Ставьте только то, чему доверяете."
        )
        warn.setWordWrap(True)
        warn.setObjectName("hintLabel")
        lay.addWidget(warn)

        self.catalog_scroll = QScrollArea()
        self.catalog_scroll.setWidgetResizable(True)
        self.catalog_host = QWidget()
        self.catalog_lay = QVBoxLayout(self.catalog_host)
        self.catalog_lay.addStretch(1)
        self.catalog_scroll.setWidget(self.catalog_host)
        lay.addWidget(self.catalog_scroll, 1)

        self.catalog_status = QLabel("Нажмите «Загрузить», чтобы получить список.")
        self.catalog_status.setObjectName("heroSub")
        lay.addWidget(self.catalog_status)
        return page

    def _load_catalog(self) -> None:
        self.btn_reload.setEnabled(False)
        self.catalog_status.setText("Загружаю каталог…")
        self.ctrl.fetch_catalog(self._on_catalog_loaded, self._on_catalog_failed)

    def _on_catalog_failed(self, message: str) -> None:
        self.btn_reload.setEnabled(True)
        self.catalog_status.setText(f"Каталог недоступен: {message}")

    def _on_catalog_loaded(self, entries: list) -> None:
        self.btn_reload.setEnabled(True)
        self.btn_reload.setText("Обновить")
        self._catalog_entries = entries
        self.catalog_status.setText(f"Плагинов в каталоге: {len(entries)}")
        self._render_catalog()

    def _render_catalog(self) -> None:
        while self.catalog_lay.count() > 1:  # оставляем финальный stretch
            item = self.catalog_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        query = self.search.text().strip().lower()
        kind_label = {"official": "официальный", "community": "сообщество"}
        shown = 0
        for entry in self._catalog_entries:
            hay = f"{entry.title} {entry.description} {getattr(entry, 'author', '')}".lower()
            if query and query not in hay:
                continue
            shown += 1
            card = QWidget()
            card.setObjectName("card")
            row = QHBoxLayout(card)
            author = f" · {entry.author}" if getattr(entry, "author", "") else ""
            text = QLabel(
                f"<b>{entry.title}</b> ({kind_label.get(entry.kind, entry.kind)}{author})<br>"
                f"{entry.description}"
            )
            text.setWordWrap(True)
            installed = self.ctrl.is_installed(entry.name)
            btn = QPushButton("Обновить" if installed else "Установить")
            btn.setFixedWidth(110)
            btn.clicked.connect(lambda _=False, e=entry, b=btn: self._install(e, b))
            row.addWidget(text, 1)
            row.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            self.catalog_lay.insertWidget(self.catalog_lay.count() - 1, card)
        if self._catalog_entries and not shown:
            empty = QLabel("Ничего не найдено.")
            empty.setObjectName("heroSub")
            self.catalog_lay.insertWidget(0, empty)

    def _install(self, entry, btn: QPushButton) -> None:
        if self.ctrl.install_entry(entry, self):
            btn.setText("Обновить")
