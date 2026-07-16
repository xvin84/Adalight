from datetime import time as dtime

import pytest

from adalight.schedule import ScheduleRule, brightness_at, parse_rules, parse_time


def test_parse_time():
    assert parse_time("08:30") == dtime(8, 30)
    assert parse_time(" 23:05 ") == dtime(23, 5)


def test_parse_time_compact_digits():
    assert parse_time("1816") == dtime(18, 16)
    assert parse_time("930") == dtime(9, 30)
    assert parse_time("0000") == dtime(0, 0)


@pytest.mark.parametrize("bad", ["8", "25:00", "12:60", "ab:cd", "", "1:2:3", "2500", "12345"])
def test_parse_time_rejects(bad):
    with pytest.raises(ValueError):
        parse_time(bad)


def test_parse_rules():
    rules = parse_rules([{"start": "08:00", "end": "20:00", "brightness": "0.9"}])
    assert rules == [ScheduleRule(dtime(8, 0), dtime(20, 0), 0.9)]


@pytest.mark.parametrize(
    "raw",
    [
        [{"start": "08:00", "end": "08:00", "brightness": 0.5}],   # пустой интервал
        [{"start": "08:00", "end": "09:00", "brightness": 3.0}],   # яркость вне диапазона
        [{"start": "08:00", "brightness": 0.5}],                   # нет конца
        [{"start": "08:00", "end": "09:00", "brightness": "x"}],   # мусор в яркости
    ],
)
def test_parse_rules_rejects(raw):
    with pytest.raises(ValueError):
        parse_rules(raw)


def make_rules():
    return parse_rules(
        [
            {"start": "08:00", "end": "20:00", "brightness": 0.9},
            {"start": "20:00", "end": "00:00", "brightness": 0.5},
            {"start": "00:00", "end": "08:00", "brightness": 0.35},
        ]
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (dtime(8, 0), 0.9),     # начало включительно
        (dtime(12, 0), 0.9),
        (dtime(19, 59), 0.9),
        (dtime(20, 0), 0.5),    # конец исключительно -> следующий интервал
        (dtime(23, 59), 0.5),
        (dtime(0, 0), 0.35),
        (dtime(7, 59), 0.35),
    ],
)
def test_brightness_at_full_day(now, expected):
    assert brightness_at(now, make_rules(), default=1.0) == expected


def test_brightness_at_default_outside_rules():
    rules = parse_rules([{"start": "10:00", "end": "12:00", "brightness": 0.5}])
    assert brightness_at(dtime(9, 0), rules, default=0.77) == 0.77
    assert brightness_at(dtime(12, 0), rules, default=0.77) == 0.77


def test_brightness_at_wraps_midnight():
    rules = parse_rules([{"start": "22:00", "end": "06:00", "brightness": 0.2}])
    assert brightness_at(dtime(23, 0), rules, default=1.0) == 0.2
    assert brightness_at(dtime(3, 0), rules, default=1.0) == 0.2
    assert brightness_at(dtime(12, 0), rules, default=1.0) == 1.0


def test_first_match_wins():
    rules = parse_rules(
        [
            {"start": "08:00", "end": "20:00", "brightness": 0.9},
            {"start": "10:00", "end": "12:00", "brightness": 0.1},
        ]
    )
    assert brightness_at(dtime(11, 0), rules, default=1.0) == 0.9
