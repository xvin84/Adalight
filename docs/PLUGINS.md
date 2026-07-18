# Плагины Adalight

Плагин — это один `.py`-файл, который расширяет Adalight: реагирует на внешние
события вспышками на ленте, шлёт уведомления, ведёт свою фоновую работу.
Пересобирать программу не нужно.

## Куда класть

| ОС | Папка |
|---|---|
| Windows | `%APPDATA%\adalight\plugins\` |
| Linux | `~/.config/adalight/plugins/` |

Открыть её можно из окна плагинов: вкладка «Плагины» → **«Открыть менеджер
плагинов…»** → кнопка **«Открыть папку плагинов»**. После добавления файла
перезапустите Adalight — плагин появится в списке «Установленные».

## Минимальный плагин

```python
"""Мой первый плагин."""
import threading


class MyPlugin:
    name = "my_plugin"          # ключ в конфиге: латиница, без пробелов
    title = "Мой плагин"        # название в GUI
    description = "Что я делаю" # описание в GUI

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self, api, settings: dict) -> None:
        # вызывается при включении; верните управление быстро,
        # долгую работу ведите в своём потоке
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(api,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        # обязaн остановить все ваши потоки
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self, api) -> None:
        while not self._stop.wait(60):
            api.trigger_flash("#00c8ff", x=0.9, y=0.9)


def create_plugin():
    return MyPlugin()
```

Единственное жёсткое требование к модулю — функция `create_plugin()`,
возвращающая объект с атрибутами `name`, `title`, `description`
и методами `start(api, settings)` / `stop()`.

## API

Объект `api` (тип `adalight.plugins.base.PluginAPI`) потокобезопасен:

| Метод | Что делает |
|---|---|
| `api.trigger_flash(color, x, y, radius=0.25, duration=1.5, style="ripple")` | Вспышка на ленте: `color` — `"#rrggbb"`; `x`, `y` — точка экрана в долях (`0,0` — левый верх, `1,1` — правый низ); `radius` — размер; `duration` — секунды; `style` — `"ripple"` (капля с расходящейся волной) или `"blob"` (мягкое пятно). Работает только при запущенной подсветке, иначе молча игнорируется. |
| `api.notify(title, text)` | Системное уведомление из трея (уважает настройку «Уведомления в трее»). |
| `api.log(message)` | Строка в лог — для отладки. |

## Настройки

Настройки плагина живут в общем `config.json`, секция `plugins`:

```json
{
  "plugins": {
    "my_plugin": {"enabled": true, "interval_min": 45}
  }
}
```

В `start(api, settings)` приходит словарь этой секции. Значения по умолчанию
держите в коде (`{**DEFAULTS, **settings}`). При изменении настроек менеджер
сам вызывает `stop()` и `start()` заново.

### Форма настроек по схеме

Чтобы настройки можно было менять прямо в окне менеджера (а не только правкой
`config.json`), объявите у объекта атрибут `settings_schema` — список полей.
Менеджер построит по нему форму сам, без кода GUI:

```python
class MyPlugin:
    name = "my_plugin"
    title = "Мой плагин"
    description = "Что я делаю"
    version = "1.0"                 # показывается в менеджере
    settings_schema = [
        {"key": "interval_min", "type": "int",
         "label": "Интервал, мин", "default": 45, "min": 1, "max": 240},
        {"key": "color", "type": "color", "label": "Цвет", "default": "#00c8ff"},
        {"key": "loud", "type": "bool", "label": "Громко", "default": False},
        {"key": "mode", "type": "choice", "label": "Режим", "default": "soft",
         "choices": [("soft", "Мягко"), ("hard", "Резко")]},
        {"type": "note", "label": "Любой поясняющий текст без поля."},
    ]
```

Типы полей: `bool`, `int`, `float`, `choice`, `color`, `text`, `note`
(статичная подсказка). Ключ `enabled` задавать не нужно — включением
управляет сам менеджер. Схема — обычные данные (без Qt), так что плагин
остаётся переносимым.

## Правила хорошего тона

- **Не блокируйте `start()`** — он вызывается из GUI-потока.
- **Используйте `Event.wait(t)` вместо `time.sleep(t)`** в циклах — плагин
  остановится мгновенно, а не через полный интервал.
- **Ловите свои исключения** внутри потока: упавший поток плагина не уронит
  программу, но и работать перестанет молча.
- Не трогайте Qt из потоков плагина — только методы `api`.

## Публикация в каталоге

Каталог на вкладке «Плагины» читает файл
[`plugins-index.json`](../plugins-index.json) из основного репозитория.
Чтобы опубликовать свой плагин — пришлите pull request, добавив запись:

```json
{
  "name": "my_plugin",
  "title": "Мой плагин",
  "description": "Что он делает",
  "author": "ваш-ник",
  "kind": "community",
  "version": "1.0",
  "url": "https://raw.githubusercontent.com/.../my_plugin.py"
}
```

`kind: official` зарезервирован за плагинами из этого репозитория.

## Пример

Готовый рабочий пример — [`examples/plugins/break_reminder.py`](../examples/plugins/break_reminder.py):
напоминание о перерыве, вспыхивающее лентой каждые N минут. Скопируйте его
в папку плагинов и включите — а потом правьте под себя.
