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

from ..i18n import tr
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
        self.setWindowTitle(tr("Плагины"))
        self.setMinimumSize(760, 500)

        root = QVBoxLayout(self)

        # переключатель видов
        seg = QHBoxLayout()
        self.btn_installed = QPushButton(tr("Установленные"))
        self.btn_catalog = QPushButton(tr("Каталог"))
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
        self.ch_enabled = QCheckBox(tr("Включён"))
        self.ch_enabled.toggled.connect(self._on_enabled_toggled)
        self.lbl_err = QLabel()
        self.lbl_err.setWordWrap(True)
        self.lbl_err.setObjectName("hintLabel")
        self.lbl_err.hide()

        # для языков: кнопка «сделать языком интерфейса» вместо галочки «Включён»
        self.btn_use_lang = QPushButton(tr("Сделать языком интерфейса"))
        self.btn_use_lang.clicked.connect(self._on_use_language)
        self.btn_use_lang.hide()

        self.settings_host = QVBoxLayout()

        for w in (self.lbl_title, self.lbl_meta, self.lbl_desc, self.ch_enabled,
                  self.btn_use_lang, self.lbl_err):
            self.detail.addWidget(w)
        self.detail.addLayout(self.settings_host)
        self.detail.addStretch(1)

        # прокрутка: настройки берут натуральную высоту и не наезжают строками
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(right)

        right_col = QWidget()
        right_v = QVBoxLayout(right_col)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.addWidget(scroll, 1)

        # нижняя панель — вне прокрутки, всегда видна
        bottom = QHBoxLayout()
        btn_dir = QPushButton(tr("Открыть папку плагинов"))
        btn_dir.clicked.connect(self.ctrl.open_plugins_dir)
        self.btn_delete = QPushButton(tr("Удалить"))
        self.btn_delete.setIcon(icon("trash"))
        self.btn_delete.clicked.connect(self._on_delete)
        bottom.addWidget(btn_dir)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_delete)
        right_v.addLayout(bottom)

        lay.addWidget(right_col, 1)
        return page

    def refresh_installed(self) -> None:
        prev = self.list.currentRow()
        self.list.clear()
        self._locales = {loc.code: loc for loc in self.ctrl.installed_locales()}
        cfg = self.ctrl.plugins_cfg()
        for loaded in self.ctrl.manager.plugins:
            enabled = bool(cfg.get(loaded.name, {}).get("enabled", loaded.base))
            mark = "⚠" if loaded.error else ("●" if enabled else "○")
            item = QListWidgetItem(f"{mark}  {tr(loaded.title)}")
            item.setData(Qt.ItemDataRole.UserRole, ("plugin", loaded.name))
            self.list.addItem(item)
        cur = self.ctrl.current_language()
        for loc in self._locales.values():
            mark = "●" if loc.code == cur else "○"
            item = QListWidgetItem(f"{mark}  {loc.name}")
            item.setData(Qt.ItemDataRole.UserRole, ("locale", loc.code))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(min(max(prev, 0), self.list.count() - 1))

    def _current_ref(self):
        item = self.list.currentItem()
        if item is None:
            return None, None
        kind, key = item.data(Qt.ItemDataRole.UserRole)
        if kind == "plugin":
            return "plugin", self.ctrl.manager.get(key)
        return "locale", self._locales.get(key)

    def _current_loaded(self):
        kind, obj = self._current_ref()
        return obj if kind == "plugin" else None

    def _on_select(self, _row: int) -> None:
        kind, obj = self._current_ref()
        if obj is None:
            return
        self._loading = True
        self._clear_settings_widget()
        if kind == "locale":
            self._show_locale(obj)
        else:
            self._show_plugin(obj)
        self._loading = False

    def _show_plugin(self, loaded) -> None:
        self.btn_use_lang.hide()
        self.ch_enabled.show()
        badge = tr("встроенный") if loaded.builtin else tr("установленный")
        ver = f" · v{loaded.version}" if loaded.version else ""
        self.lbl_title.setText(tr(loaded.title))
        self.lbl_meta.setText(f"{badge}{ver}")
        self.lbl_desc.setText(tr(loaded.description) if loaded.description else loaded.name)
        self.btn_delete.setVisible(not loaded.builtin and loaded.path is not None)
        if loaded.error:
            self.lbl_err.setText(tr("⚠ Ошибка: {e}").format(e=loaded.error))
            self.lbl_err.show()
        else:
            self.lbl_err.hide()
        entry = self.ctrl.plugins_cfg().get(loaded.name, {})
        self.ch_enabled.setEnabled(loaded.plugin is not None)
        self.ch_enabled.setChecked(bool(entry.get("enabled", loaded.base)))
        self._build_settings(loaded, entry)

    def _show_locale(self, loc) -> None:
        self.ch_enabled.hide()
        self.lbl_err.hide()
        active = loc.code == self.ctrl.current_language()
        badge = tr("язык · встроенный") if loc.builtin else tr("язык · установленный")
        self.lbl_title.setText(loc.name)
        self.lbl_meta.setText(badge)
        self.lbl_desc.setText(
            tr("Текущий язык интерфейса.") if active
            else tr("Язык интерфейса. Выбор применяется после перезапуска.")
        )
        self.btn_use_lang.show()
        self.btn_use_lang.setEnabled(not active)
        self.btn_use_lang.setText(
            tr("Текущий язык") if active else tr("Сделать языком интерфейса")
        )
        self.btn_delete.setVisible(not loc.builtin and loc.path is not None)

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
            widget = QLabel(tr("У этого плагина нет настроек."))
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
        loaded = self._current_loaded()
        # выключение базового мода — предупреждаем: часть функционала пропадёт
        if loaded is not None and loaded.base and not _checked:
            if QMessageBox.warning(
                self, tr("Выключить базовый мод?"),
                tr("«{title}» — базовый мод. Без него пропадёт часть функционала "
                   "(эффекты/захват/транспорт). Выключить?").format(
                    title=tr(loaded.title)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                self._loading = True  # откат галочки без повторного применения
                self.ch_enabled.setChecked(True)
                self._loading = False
                return
        self._apply_current()
        if loaded is not None:  # обновить значок ●/○ в списке
            item = self.list.currentItem()
            mark = "⚠" if loaded.error else ("●" if _checked else "○")
            item.setText(f"{mark}  {tr(loaded.title)}")

    def _on_settings_changed(self) -> None:
        if self._loading:
            return
        self._apply_current()

    def _on_use_language(self) -> None:
        kind, loc = self._current_ref()
        if kind != "locale" or loc is None:
            return
        self.ctrl.set_ui_language(loc.code)
        self.refresh_installed()

    def _on_delete(self) -> None:
        kind, obj = self._current_ref()
        if obj is None or obj.path is None:
            return
        title = obj.title if kind == "plugin" else obj.name
        if QMessageBox.question(
            self, tr("Удалить плагин"),
            tr("Удалить файл плагина «{title}»?\n{path}").format(
                title=title, path=obj.path
            ),
        ) != QMessageBox.StandardButton.Yes:
            return
        ok = self.ctrl.delete_plugin(obj) if kind == "plugin" else self.ctrl.delete_locale(obj)
        if ok:
            self.refresh_installed()

    # ── вид «Каталог» ─────────────────────────────────────────────────────

    def _build_catalog_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Поиск плагинов…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render_catalog)
        self.btn_reload = QPushButton(tr("Загрузить"))
        self.btn_reload.setIcon(icon("refresh"))
        self.btn_reload.clicked.connect(self._load_catalog)
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_reload)
        lay.addLayout(top)

        warn = QLabel(
            tr("Плагин — это код, который выполняется на вашем компьютере. "
            "Ставьте только то, чему доверяете.")
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

        self.catalog_status = QLabel(tr("Нажмите «Загрузить», чтобы получить список."))
        self.catalog_status.setObjectName("heroSub")
        lay.addWidget(self.catalog_status)
        return page

    def _load_catalog(self) -> None:
        self.btn_reload.setEnabled(False)
        self.catalog_status.setText(tr("Загружаю каталог…"))
        self.ctrl.fetch_catalog(self._on_catalog_loaded, self._on_catalog_failed)

    def _on_catalog_failed(self, message: str) -> None:
        self.btn_reload.setEnabled(True)
        self.catalog_status.setText(tr("Каталог недоступен: {msg}").format(msg=message))

    def _on_catalog_loaded(self, entries: list) -> None:
        self.btn_reload.setEnabled(True)
        self.btn_reload.setText(tr("Обновить"))
        self._catalog_entries = entries
        self.catalog_status.setText(
            tr("Плагинов в каталоге: {n}").format(n=len(entries))
        )
        self._render_catalog()

    def _render_catalog(self) -> None:
        while self.catalog_lay.count() > 1:  # оставляем финальный stretch
            item = self.catalog_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        query = self.search.text().strip().lower()
        kind_label = {"official": tr("официальный"), "community": tr("сообщество")}
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
            btn = QPushButton()
            btn.setFixedWidth(110)
            if self.ctrl.is_installed(entry.name):
                self._mark_installed(card, btn)
            else:
                btn.setText(tr("Установить"))
                btn.clicked.connect(
                    lambda _=False, e=entry, b=btn, c=card: self._install(e, b, c)
                )
            row.addWidget(text, 1)
            row.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            self.catalog_lay.insertWidget(self.catalog_lay.count() - 1, card)
        if self._catalog_entries and not shown:
            empty = QLabel(tr("Ничего не найдено."))
            empty.setObjectName("heroSub")
            self.catalog_lay.insertWidget(0, empty)

    def _mark_installed(self, card: QWidget, btn: QPushButton) -> None:
        """Уже установленное — приглушённая карточка и неактивная кнопка."""
        btn.setText(tr("Установлено"))
        btn.setEnabled(False)
        card.setEnabled(False)  # серый вид; управление — во вкладке «Установленные»

    def _install(self, entry, btn: QPushButton, card: QWidget) -> None:
        if self.ctrl.install_entry(entry, self):
            self._mark_installed(card, btn)
            self.refresh_installed()  # новый плагин появляется без перезапуска
