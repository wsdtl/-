from pathlib import Path

from tools.架构审查.校验项目一致性 import audit_project_consistency


def test_project_commands_buttons_layout_and_docs_are_consistent() -> None:
    root = Path(__file__).resolve().parents[2]
    command_count, button_count = audit_project_consistency(root)

    assert command_count > 0
    assert button_count > 0
