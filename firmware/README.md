# Firmware / Прошивка

**English** below · **Русский** ниже

---

## English

The board (Arduino/ESP) needs a sketch that speaks the **Adalight** serial
protocol. This folder contains a ready-to-flash reference sketch:
[`Gyver_Ambilight/Gyver_Ambilight.ino`](Gyver_Ambilight/Gyver_Ambilight.ino).

### Credit

The firmware is **not ours**. Original author — **AlexGyver**:

- Project page: <https://alexgyver.ru/arduino_ambilight/>
- Source: <https://github.com/AlexGyver/Arduino_Ambilight> (Gyver_Ambilight v1.3)

It is included here **with attribution** and only lightly adapted (a header note
and settings guidance). All credit for the firmware belongs to the original
author; its original header is kept intact. Its licensing follows the original
source, not this repository's MIT license.

### Why it works with this app

The app streams the classic Adalight frame: the magic header
`"Ada" + count_hi + count_lo + (hi ^ lo ^ 0x55)`, then 3 bytes (R, G, B) per LED.
The sketch reads exactly that, so it is compatible out of the box.

### Flashing

1. Install the **Arduino IDE** and the **FastLED** library
   (Library Manager → search "FastLED").
2. Open `Gyver_Ambilight.ino` and set the values at the top:
   - `NUM_LEDS` — total number of LEDs (top + right + bottom + left);
   - `DI_PIN` — the data pin your strip is wired to;
   - `serialRate` — baud rate (keep it equal to the app's **Speed**);
   - `AUTO_BRIGHT` — set to `0` if you have no photoresistor.
3. Select your board and port, then **Upload**.

### Match the app's settings

| Sketch | App (Connection) |
|---|---|
| `NUM_LEDS` | total LED count (per-side counts add up to this) |
| `serialRate` | **Speed** (baud), e.g. 115200 |
| `WS2812, …, GRB` | **Channel order = RGB** (the strip's GRB is applied on the board) |
| `DI_PIN` | — (hardware wiring) |

> If your LED hues look swapped, first try changing the app's **Channel order**;
> with this sketch it should be **RGB**.

---

## Русский

Плате (Arduino/ESP) нужна прошивка, понимающая serial-протокол **Adalight**.
В этой папке лежит готовый эталонный скетч:
[`Gyver_Ambilight/Gyver_Ambilight.ino`](Gyver_Ambilight/Gyver_Ambilight.ino).

### Автор

Прошивка **не наша**. Изначальный автор — **AlexGyver**:

- Страница проекта: <https://alexgyver.ru/arduino_ambilight/>
- Исходник: <https://github.com/AlexGyver/Arduino_Ambilight> (Gyver_Ambilight v1.3)

Она добавлена сюда **с указанием авторства** и лишь слегка адаптирована (шапка с
пояснением и подсказки по настройкам). Всё авторство прошивки принадлежит
изначальному автору; его оригинальная шапка сохранена. Её лицензия следует за
первоисточником, а не за MIT этого репозитория.

### Почему работает с приложением

Приложение шлёт классический кадр Adalight: заголовок
`"Ada" + count_hi + count_lo + (hi ^ lo ^ 0x55)`, затем по 3 байта (R, G, B) на
каждый диод. Скетч читает ровно это — поэтому совместим «из коробки».

### Прошивка

1. Установите **Arduino IDE** и библиотеку **FastLED**
   (Менеджер библиотек → «FastLED»).
2. Откройте `Gyver_Ambilight.ino` и задайте настройки сверху:
   - `NUM_LEDS` — общее число диодов (сверху + справа + снизу + слева);
   - `DI_PIN` — пин, к которому подключён дата-провод ленты;
   - `serialRate` — скорость (держите равной **Скорости** в приложении);
   - `AUTO_BRIGHT` — поставьте `0`, если фоторезистора нет.
3. Выберите плату и порт, нажмите **Загрузка**.

### Сопоставление с настройками приложения

| Скетч | Приложение (Подключение) |
|---|---|
| `NUM_LEDS` | общее число диодов (суммы по сторонам дают его) |
| `serialRate` | **Скорость** (baud), напр. 115200 |
| `WS2812, …, GRB` | **Порядок цвета = RGB** (GRB применяет сама плата) |
| `DI_PIN` | — (аппаратная разводка) |

> Если оттенки перепутаны — сначала меняйте **Порядок цвета** в приложении;
> с этим скетчем он должен быть **RGB**.
