# Плагины Adalight

Плагин — это один `.py`-файл, который расширяет Adalight: реагирует на внешние
события вспышками на ленте, шлёт уведомления, ведёт свою фоновую работу.
Пересобирать программу не нужно.

## Куда класть

| ОС | Папка |
|---|---|
| Windows | `%APPDATA%\adalight\plugins\` |
| Linux | `~/.config/adalight/plugins/` |

Кнопка **«Открыть папку плагинов»** на вкладке «Плагины» открывает её.
После добавления файла перезапустите Adalight — плагин появится в списке.

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
| `api.trigger_flash(color, x, y, radius=0.25, duration=1.5)` | Вспышка на ленте: `color` — `"#rrggbb"`; `x`, `y` — точка экрана в долях (`0,0` — левый верх, `1,1` — правый низ); `radius` — размер пятна; `duration` — длительность в секундах. Работает только при запущенной подсветке, иначе молча игнорируется. |
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

## Правила хорошего тона

- **Не блокируйте `start()`** — он вызывается из GUI-потока.
- **Используйте `Event.wait(t)` вместо `time.sleep(t)`** в циклах — плагин
  остановится мгновенно, а не через полный интервал.
- **Ловите свои исключения** внутри потока: упавший поток плагина не уронит
  программу, но и работать перестанет молча.
- Не трогайте Qt из потоков плагина — только методы `api`.

## Пример

Готовый рабочий пример — [`examples/plugins/break_reminder.py`](../examples/plugins/break_reminder.py):
напоминание о перерыве, вспыхивающее лентой каждые N минут. Скопируйте его
в папку плагинов и включите — а потом правьте под себя.
