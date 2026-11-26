from pathlib import Path

from app.modules.identity.security import ROLE_PERMISSIONS


def test_permission_matrix_matches_role_permissions() -> None:
    text = (Path(__file__).resolve().parents[2] / "docs" / "architecture.md").read_text()
    start = text.index("<!-- permission-matrix:start -->")
    end = text.index("<!-- permission-matrix:end -->")
    lines = [line for line in text[start:end].splitlines() if line.startswith("|")]
    header, _, *rows = lines
    roles = [_cell(cell) for cell in header.split("|")[2:-1]]
    parsed = {role: set() for role in roles}
    seen_permissions: set[str] = set()

    for row in rows:
        cells = [_cell(cell) for cell in row.split("|")[1:-1]]
        permission, values = cells[0], cells[1:]
        assert permission
        assert permission not in seen_permissions
        seen_permissions.add(permission)
        assert len(values) == len(roles)
        for role, value in zip(roles, values, strict=True):
            assert value in {"", "✓"}
            if value == "✓":
                parsed[role].add(permission)

    assert {
        role: frozenset(permissions) for role, permissions in parsed.items()
    } == ROLE_PERMISSIONS


def _cell(value: str) -> str:
    return value.strip().strip("`")
