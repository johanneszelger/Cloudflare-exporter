import json
import shutil

import pytest

from state import State  # assuming your class is in state.py


@pytest.fixture(autouse=True)
def run_around_tests():
    shutil.rmtree("/data", ignore_errors=True)


def test_initializes_empty_state():
    s = State()
    assert s.state == {}  # no file yet, should start empty


def test_update_new_key_and_value():
    s = State()

    current = {"metric1": 5}
    prev = {"metric1": 3}
    s.update("serviceA", current, prev)

    assert "serviceA" in s.state
    assert "metric1" in s.state["serviceA"]

    entry = s.state["serviceA"]["metric1"]
    assert entry["current_hour_count"] == 5
    assert entry["previous_hour_count"] == 3
    assert entry["counter"] == (5 - 0) + (3 - 0)  # first update


def test_update_existing_key_and_value():
    s = State()
    s.update("serviceA", {"metric1": 5}, {"metric1": 3})
    entry = s.state["serviceA"]["metric1"]
    assert entry["counter"] == 5 + 3
    s.update("serviceA", {"metric1": 7}, {"metric1": 4})

    assert entry["current_hour_count"] == 7
    assert entry["previous_hour_count"] == 4
    assert entry["counter"] == 7 + 4


def test_update_resets_on_lower_value():
    s = State()
    s.update("serviceA", {"metric1": 5}, {"metric1": 3})
    # now provide lower current value (new hour)
    s.update("serviceA", {"metric1": 2}, {"metric1": 6})

    entry = s.state["serviceA"]["metric1"]
    assert entry["current_hour_count"] == 2
    assert entry["previous_hour_count"] == 6
    # After reset, it should recalc counter without adding weird negatives
    assert entry["counter"] == 5 + 3 + 2 + 1

def test_update_previous_empty():
    s = State()
    s.update("serviceA", {"metric1": 5}, None)
    # now provide lower current value (new hour)
    s.update("serviceA", {"metric1": 2}, {"metric1": 6})

    entry = s.state["serviceA"]["metric1"]
    assert entry["current_hour_count"] == 2
    assert entry["previous_hour_count"] == 6
    # After reset, it should recalc counter without adding weird negatives
    assert entry["counter"] == 5 + 2 + 1