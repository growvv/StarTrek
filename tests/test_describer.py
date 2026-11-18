from specfcg.planner.describer import TaskDescriber


def test_description_states_the_goal_then_each_subgoal_in_order(
    sample_card, another_card
):
    text = TaskDescriber().describe(
        "Create a note titled Grocery list",
        [(sample_card, {"title": "Grocery list"}), (another_card, {})],
    )
    assert text.startswith("Overall goal: Create a note titled Grocery list")
    assert text.index("1. create_note") < text.index("2. share_note")
    assert "title = Grocery list" in text
    assert "Postconditions: A note with the given title appears" in text
    assert "tap" not in text.lower() and "click" not in text.lower()


def test_a_value_bound_from_an_earlier_subgoal_says_where_it_came_from(
    sample_card, another_card
):
    text = TaskDescriber().describe(
        "Share the note just created",
        [(sample_card, {}), (another_card, {"note": "Draft"})],
    )
    assert "note = Draft (from subgoal 1)" in text


def test_an_unbound_input_is_a_named_gap_not_a_failure(sample_card):
    text = TaskDescriber().describe("Do it", [(sample_card, {})])
    assert "title = <unbound: not named in the goal or earlier outputs>" in text


def test_the_description_carries_reliability_from_the_card(sample_card):
    text = TaskDescriber().describe("Do it", [(sample_card, {})])
    assert "Reliability: 2/3 observed successes" in text


def test_an_empty_path_still_states_the_goal():
    text = TaskDescriber().describe("Do nothing", [])
    assert text.startswith("Overall goal: Do nothing")
    assert "Subgoals" not in text
