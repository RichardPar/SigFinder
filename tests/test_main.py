import threading

import sigfinder.main as main


def test_nmea_to_decimal_lat():
    # 49 degrees, 16.45 minutes -> 49 + 16.45/60
    val = main._nmea_to_decimal("4916.4500", "N")
    assert val is not None
    assert abs(val - (49 + 16.4500 / 60.0)) < 1e-8


def test_nmea_to_decimal_lon_west():
    # 123 degrees, 11.12 minutes West -> negative
    val = main._nmea_to_decimal("12311.1200", "W")
    assert val is not None
    assert val < 0
    assert abs(val - (-(123 + 11.1200 / 60.0))) < 1e-8


def test_get_logs_clears_buffer():
    # Ensure get_logs returns accumulated messages and clears the buffer
    with main.gui_log_lock:
        main.gui_log.clear()
        main.gui_log.extend(["$GPGGA,TEST1", "$GPRMC,TEST2"]) 

    msgs = main.get_logs()
    assert msgs == ["$GPGGA,TEST1", "$GPRMC,TEST2"]

    # subsequent call should return empty list
    msgs2 = main.get_logs()
    assert msgs2 == []
