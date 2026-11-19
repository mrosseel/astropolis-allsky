from datetime import datetime

import pytest

import frameindex as fi


def test_parse_stamp_reads_space_as_digit():
    assert fi.parse_stamp("2026.10.26100:12:19") == datetime(2026, 10, 26, 0, 12, 19)


def test_parse_stamp_trailing_punctuation():
    assert fi.parse_stamp("2026.10.2521:05:49:\n") == datetime(2026, 10, 25, 21, 5, 49)


def test_parse_stamp_garbage():
    assert fi.parse_stamp("") is None
    assert fi.parse_stamp("2026.13.40 99:99:99") is None


def test_to_epoch_dst_fall_back():
    # 2026-10-25: Brussels clock goes from 03:00 CEST back to 02:00 CET.
    local = [
        datetime(2026, 10, 25, 2, 50),
        datetime(2026, 10, 25, 2, 10),
        datetime(2026, 10, 25, 2, 20),
    ]
    e = fi.to_epoch(local)
    assert e[1] - e[0] == 20 * 60
    assert e[2] - e[1] == 10 * 60


def test_longest_increasing_drops_ocr_errors():
    values = [10.0, 20.0, 99999.0, 40.0, None, 60.0, 5.0, 80.0]
    assert fi.longest_increasing(values) == {0, 1, 3, 5, 7}


def test_fill_gaps_interpolates_and_extrapolates():
    assert fi.fill_gaps([None, 10.0, None, None, 40.0, None]) == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]


def test_build_times_keeps_real_gap():
    readings = [
        "2026.10.25 22:00:00",
        "2026.10.25 22:00:15",
        "garbage",
        "2026.10.25 23:00:00",  # camera gap of one hour
        "2026.10.25 23:00:15",
    ]
    times, ok = fi.build_times(readings)
    assert ok == 4
    assert times[4] - times[3] == 15
    assert times[3] - times[1] == 3600 - 15


def test_build_times_rejects_unreadable_video():
    with pytest.raises(ValueError):
        fi.build_times(["x"] * 10 + ["2026.10.25 22:00:00", "2026.10.25 22:00:15"])


def test_frame_range():
    times = [0.0, 15.0, 30.0, 45.0, 3645.0, 3660.0]
    assert fi.frame_range(times, 10, 40) == (1, 2)
    assert fi.frame_range(times, 50, 3600) is None
    assert fi.frame_range(times, -100, 10000) == (0, 5)
