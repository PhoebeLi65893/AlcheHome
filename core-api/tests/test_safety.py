import pytest

from app.agent.safety import EMERGENCY_REPLIES, check_emergency


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("I smell gas in the kitchen", "gas"),
        ("There's a gas leak near my water heater!", "gas"),
        ("my whole house smells like rotten eggs", "gas"),
        ("The carbon monoxide alarm is going off", "carbon_monoxide"),
        ("my CO detector keeps beeping", "carbon_monoxide"),
        ("my kitchen is on fire", "fire"),
        ("I saw smoke coming from the wall", "fire"),
        ("The outlet is sparking", "electrical"),
        ("sparks came out of the breaker panel", "electrical"),
        ("I got shocked touching the switch", "electrical"),
        ("water is pouring through the ceiling near the electrical panel", "flood_electric"),
        ("the ceiling is collapsing in my bedroom", "structural"),
    ],
)
def test_emergencies_are_detected(text, category):
    assert check_emergency(text) == category
    assert "911" in EMERGENCY_REPLIES[category]


@pytest.mark.parametrize(
    "text",
    [
        "my sink is leaking",
        "the gas stove igniter keeps clicking",
        "I want someone to clean my fireplace",
        "the outlet in the kitchen does not work",
        "the smoke detector battery is chirping",
        "my water heater is dripping in the garage",
        "I need a plumber",
    ],
)
def test_ordinary_problems_are_not_flagged(text):
    assert check_emergency(text) is None


def test_detection_ignores_case_and_extra_whitespace():
    assert check_emergency("I   SMELL\n GAS") == "gas"
