"""Мастер первого запуска: порт -> диоды -> проверка сторон."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ..config import DIRECTIONS, START_CORNERS
from ..device import list_serial_ports

if TYPE_CHECKING:
    from .main_window import MainWindow

_BAUDS = ("115200", "230400", "460800", "500000", "921600", "1000000", "2000000")
_CORNER_LABELS = {
    "top-left": "Верхний левый",
    "top-right": "Верхний правый",
    "bottom-left": "Нижний левый",
    "bottom-right": "Нижний правый",
}
_DIRECTION_LABELS = {"cw": "По часовой", "ccw": "Против часовой"}


class SetupWizard(QWizard):
    """Три шага до работающей подсветки; значения уходят в главное окно."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self._mw = mw
        self.setWindowTitle("Мастер настройки Adalight")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.NextButton, "Далее >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Назад")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Готово")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Отмена")
        self.setMinimumSize(520, 420)

        self.addPage(self._page_port())
        self.addPage(self._page_leds())
        self.addPage(self._page_test())

        self.accepted.connect(self._on_accepted)
        self.rejected.connect(self._mw._stop_engine)

    # ── страницы ──────────────────────────────────────────────────────────

    def _page_port(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Подключение")
        page.setSubTitle(
            "Подключите Arduino/ESP с прошивкой Adalight по USB и выберите порт."
        )
        form = QFormLayout(page)

        self.cb_port = QComboBox()
        self.cb_port.setEditable(True)
        btn = QPushButton("Обновить")
        btn.clicked.connect(self._refresh_ports)
        row = QHBoxLayout()
        row.addWidget(self.cb_port, 1)
        row.addWidget(btn)
        form.addRow("Порт:", row)

        self.cb_baud = QComboBox()
        self.cb_baud.setEditable(True)
        self.cb_baud.addItems(_BAUDS)
        self.cb_baud.setCurrentText("115200")
        form.addRow("Скорость:", self.cb_baud)

        hint = QLabel(
            "Скорость должна совпадать с прошивкой. Если порта нет в списке —\n"
            "проверьте кабель (бывают кабели «только зарядка») и драйвер CH340/CP210x."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        self._refresh_ports()
        return page

    def _page_leds(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Светодиоды")
        page.setSubTitle(
            "Посчитайте диоды на каждой стороне монитора и укажите, где начинается "
            "лента и куда она идёт."
        )
        form = QFormLayout(page)

        def spin(value: int) -> QSpinBox:
            s = QSpinBox()
            s.setRange(0, 500)
            s.setValue(value)
            return s

        self.sp_top, self.sp_right = spin(15), spin(9)
        self.sp_bottom, self.sp_left = spin(15), spin(9)
        form.addRow("Сверху:", self.sp_top)
        form.addRow("Справа:", self.sp_right)
        form.addRow("Снизу:", self.sp_bottom)
        form.addRow("Слева:", self.sp_left)

        self.cb_corner = QComboBox()
        for value in START_CORNERS:
            self.cb_corner.addItem(_CORNER_LABELS[value], value)
        self.cb_corner.setCurrentIndex(START_CORNERS.index("bottom-left"))
        form.addRow("Начальный угол:", self.cb_corner)

        self.cb_direction = QComboBox()
        for value in DIRECTIONS:
            self.cb_direction.addItem(_DIRECTION_LABELS[value], value)
        form.addRow("Направление:", self.cb_direction)
        return page

    def _page_test(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Проверка")
        page.setSubTitle("Убедимся, что стороны не перепутаны.")
        lay = QVBoxLayout(page)

        btn_test = QPushButton("▶ Тест сторон")
        btn_test.clicked.connect(self._run_sides_test)
        lay.addWidget(btn_test)

        lay.addWidget(
            QLabel(
                "Должно получиться: верх — красный, право — зелёный,\n"
                "низ — синий, лево — жёлтый."
            )
        )

        self.ch_flip_x = QCheckBox("Лево и право перепутаны")
        self.ch_flip_y = QCheckBox("Верх и низ перепутаны")
        self.ch_flip_x.toggled.connect(self._run_sides_test_if_running)
        self.ch_flip_y.toggled.connect(self._run_sides_test_if_running)
        lay.addWidget(self.ch_flip_x)
        lay.addWidget(self.ch_flip_y)

        hint = QLabel(
            "Если цвета сторон верные, но оттенки странные (красный горит зелёным) —\n"
            "после мастера поменяйте «Порядок цвета» на вкладке «Устройство» (обычно GRB)."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return page

    # ── действия ──────────────────────────────────────────────────────────

    def _refresh_ports(self) -> None:
        current = self.cb_port.currentText()
        self.cb_port.clear()
        self.cb_port.addItems([device for device, _ in list_serial_ports()])
        if current:
            self.cb_port.setCurrentText(current)

    def _push_to_main(self) -> None:
        mw = self._mw
        mw.cb_port.setCurrentText(self.cb_port.currentText().strip())
        mw.cb_baud.setCurrentText(self.cb_baud.currentText())
        mw.sp_top.setValue(self.sp_top.value())
        mw.sp_right.setValue(self.sp_right.value())
        mw.sp_bottom.setValue(self.sp_bottom.value())
        mw.sp_left.setValue(self.sp_left.value())
        mw.cb_corner.setCurrentIndex(self.cb_corner.currentIndex())
        mw.cb_direction.setCurrentIndex(self.cb_direction.currentIndex())
        mw.ch_flip_x.setChecked(self.ch_flip_x.isChecked())
        mw.ch_flip_y.setChecked(self.ch_flip_y.isChecked())

    def _run_sides_test(self) -> None:
        self._push_to_main()
        self._mw._start_engine("sides")

    def _run_sides_test_if_running(self) -> None:
        if self._mw.thread is not None:
            self._run_sides_test()

    def _on_accepted(self) -> None:
        self._mw._stop_engine()
        self._push_to_main()
        self._mw._on_save()
