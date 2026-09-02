from dataclasses import dataclass

from core.errors import DocsApiError


@dataclass
class BlocksTable:
    rows: list[dict]  # Docs API table row dicts, marker row already excluded


def _cell_text(cell: dict) -> str:
    """Flatten a table cell's own direct text (used only to read the marker-row label)."""
    parts = []
    for elem in cell.get("content", []):
        paragraph = elem.get("paragraph")
        if not paragraph:
            continue
        for pe in paragraph.get("elements", []):
            text_run = pe.get("textRun")
            if text_run:
                parts.append(text_run.get("content", ""))
    return "".join(parts).strip()


def find_blocks_table(document: dict, section_marker: str, table_columns: int) -> BlocksTable:
    """Finds the table whose first row is a marker row (left cell contains `section_marker`,
    right cell empty); that row is dropped, every row after it is one block."""
    body_content = document.get("body", {}).get("content", [])
    marker = section_marker.strip().lower()

    for elem in body_content:
        table = elem.get("table")
        if not table:
            continue
        rows = table.get("tableRows", [])
        if not rows:
            continue
        first_row_cells = rows[0].get("tableCells", [])
        if len(first_row_cells) != table_columns:
            continue
        left_text = _cell_text(first_row_cells[0])
        right_text = _cell_text(first_row_cells[1]) if table_columns > 1 else ""
        if marker in left_text.lower() and not right_text:
            return BlocksTable(rows=rows[1:])

    raise DocsApiError(
        f"No table found with a marker row matching {section_marker!r} "
        f"({table_columns} columns, empty right cell). Check templates.yaml."
    )
