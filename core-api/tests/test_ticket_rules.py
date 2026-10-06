import pytest

from app.tickets.schema import TOOL_DECLARATION, Category, validate_draft
from app.tickets.state import TERMINAL, TRANSITIONS, can_transition

GOOD = {
    "category": "plumbing",
    "issue_summary": "  Kitchen sink is   leaking under the cabinet since yesterday ",
    "urgency": "same-day",
    "location_zip": "92101",
    "severity": "medium",
}


def test_valid_arguments_are_normalized():
    draft, problems = validate_draft(GOOD)
    assert problems == []
    assert draft.category == Category.PLUMBING
    assert draft.urgency.value == "SAME_DAY"
    assert draft.severity.value == "MEDIUM"
    assert draft.issue_summary == "Kitchen sink is leaking under the cabinet since yesterday"


def test_severity_is_optional():
    args = {k: v for k, v in GOOD.items() if k != "severity"}
    draft, _ = validate_draft(args)
    assert draft.severity is None


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"location_zip": "9210"}, "a valid 5-digit ZIP code"),
        ({"location_zip": "abcde"}, "a valid 5-digit ZIP code"),
        ({"category": "ROOFING_MAGIC"}, "the type of repair"),
        ({"urgency": "whenever"}, "how urgent it is"),
        ({"issue_summary": "leak"}, "a short description of the problem"),
    ],
)
def test_invalid_arguments_report_problems_in_plain_words(change, expected):
    draft, problems = validate_draft({**GOOD, **change})
    assert draft is None
    assert problems == [expected]


def test_missing_arguments_listed_once_each():
    draft, problems = validate_draft({"category": "PLUMBING"})
    assert draft is None
    assert set(problems) == {
        "a short description of the problem",
        "how urgent it is",
        "a valid 5-digit ZIP code",
    }
    assert validate_draft(None)[0] is None


def test_tool_declaration_matches_validation_enums():
    props = TOOL_DECLARATION["parameters"]["properties"]
    assert props["category"]["enum"] == [c.value for c in Category]
    assert set(TOOL_DECLARATION["parameters"]["required"]) == {
        "category",
        "issue_summary",
        "urgency",
        "location_zip",
    }


@pytest.mark.parametrize(
    ("current", "target", "ok"),
    [
        ("DRAFT", "OPEN", True),
        ("OPEN", "MATCHING", True),
        ("MATCHING", "ASSIGNED", True),
        ("MATCHING", "UNMATCHED", True),
        ("UNMATCHED", "MATCHING", True),
        ("ASSIGNED", "IN_PROGRESS", True),
        ("IN_PROGRESS", "COMPLETED", True),
        ("COMPLETED", "RATED", True),
        ("OPEN", "CANCELLED", True),
        ("DRAFT", "ASSIGNED", False),
        ("OPEN", "COMPLETED", False),
        ("COMPLETED", "CANCELLED", False),
        ("CANCELLED", "OPEN", False),
        ("RATED", "OPEN", False),
    ],
)
def test_state_machine(current, target, ok):
    assert can_transition(current, target) is ok


def test_terminal_states_have_no_exits():
    for state in TERMINAL:
        assert TRANSITIONS[state] == set()
