from specfcg.cards.migrate import migrate
from specfcg.cards.parser import parse_card

LEGACY = """# copy_file

**Intent**: Copy {source} into {dest}.
**Inputs**: source (required): the file. dest (required): the folder.
**Preconditions**: The browser shows {source}.
**Postconditions**: A copy of {source} exists in {dest}.
**Effects/Outputs**: Creates a duplicate.
**Steps**:
1. Long-press {source}.
2. Tap the copy command.
**Evidence**: traces copy-file; 3/3 successes
"""


def test_migration_removes_only_the_steps_section():
    migrated = migrate(LEGACY)
    assert "**Steps**" not in migrated and "copy command" not in migrated
    assert "**Postconditions**: A copy of {source} exists in {dest}." in migrated
    assert parse_card(migrated).name == "copy_file"
    assert migrate(migrated) == migrated  # idempotent


def test_migration_keeps_every_other_line_byte_for_byte():
    """Only the Steps block moves; the rest of the file is untouched.

    A migration that rewrites headings or normalises whitespace would show up
    as a diff on all 93 cards, and nobody could tell a migration from an edit.
    """
    migrated = migrate(LEGACY)
    before = LEGACY.split("**Steps**:")[0]
    after = migrated.split("**Evidence**")[0]
    assert after == before


def test_migration_handles_a_steps_section_at_end_of_file():
    text = "# x\n\n**Intent**: y\n**Steps**:\n1. Tap.\n"
    migrated = migrate(text)
    assert "**Steps**" not in migrated
    assert "Tap." not in migrated
    assert migrated.endswith("\n")
