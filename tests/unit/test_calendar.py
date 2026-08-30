from allocsolver.models.calendar import Month, workable_hours


def test_parse_and_str_roundtrip():
    assert str(Month.parse("2027-07")) == "2027-07"


def test_add_crosses_year_boundary():
    assert Month(2027, 12).add(1) == Month(2028, 1)


def test_ufy_boundary():
    assert Month(2027, 6).ufy() == 2026
    assert Month(2027, 7).ufy() == 2027
    assert Month(2027, 7).is_ufy_start()
    assert not Month(2027, 6).is_ufy_start()


def test_range_inclusive():
    months = Month.range(Month(2027, 1), Month(2027, 3))
    assert months == [Month(2027, 1), Month(2027, 2), Month(2027, 3)]


def test_workable_hours_excludes_weekends_and_holidays():
    # January 2027 has New Year's Day (a Friday) plus weekends removed.
    hours = workable_hours(Month(2027, 1))
    assert 0 < hours < 23 * 8  # fewer than every calendar weekday-count at 8h/day
