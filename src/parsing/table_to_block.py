import re
from dataclasses import dataclass

from models.blocks import Block
from models.templates import BlockSchema


@dataclass
class ParaInfo:
    text: str
    is_label: bool
    is_bullet: bool


def _paragraph_text(paragraph: dict) -> str:
    parts = [pe["textRun"]["content"] for pe in paragraph.get("elements", []) if "textRun" in pe]
    return "".join(parts).strip()


def named_style_bold_defaults(document: dict) -> dict[str, bool]:
    """Maps namedStyleType -> whether that style is bold *by default*, from the document's
    own namedStyles. A run's own textStyle.bold, when present, always overrides this."""
    styles = document.get("namedStyles", {}).get("styles", [])
    return {
        s["namedStyleType"]: bool(s.get("textStyle", {}).get("bold", False))
        for s in styles
        if "namedStyleType" in s
    }


def _is_bold_paragraph(paragraph: dict, style_defaults: dict[str, bool]) -> bool:
    """True if the paragraph's first substantive text run is effectively bold, resolved
    against the named style's default rather than only the run's own override."""
    named_style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
    default_bold = style_defaults.get(named_style, False)
    for pe in paragraph.get("elements", []):
        run = pe.get("textRun")
        if run and run.get("content", "").strip():
            explicit = run.get("textStyle", {}).get("bold")
            return default_bold if explicit is None else bool(explicit)
    return False


def _iter_cell_paragraphs(content: list[dict], style_defaults: dict[str, bool]) -> list[ParaInfo]:
    """Linear scan of a table cell's content, transparently flattening into any nested table it meets."""
    out: list[ParaInfo] = []
    for elem in content:
        paragraph = elem.get("paragraph")
        if paragraph is not None:
            text = _paragraph_text(paragraph)
            if not text:
                continue
            is_bullet = "bullet" in paragraph
            out.append(
                ParaInfo(
                    text=text,
                    is_label=_is_bold_paragraph(paragraph, style_defaults) and not is_bullet,
                    is_bullet=is_bullet,
                )
            )
            continue
        table = elem.get("table")
        if table is not None:
            for row in table.get("tableRows", []):
                for cell in row.get("tableCells", []):
                    out.extend(_iter_cell_paragraphs(cell.get("content", []), style_defaults))
    return out


def _split_primary(paragraphs: list[ParaInfo]) -> tuple[str, str]:
    """Left cell: first paragraph is the name (by position, regardless of style);
    remaining paragraph(s) are the description."""
    if not paragraphs:
        return "untitled", ""
    name = paragraphs[0].text
    description = " ".join(p.text for p in paragraphs[1:])
    return name, description


def _split_details(
    paragraphs: list[ParaInfo], schema: BlockSchema
) -> list[tuple[str, str, list[ParaInfo]]]:
    """Right cell: each bold-labeled paragraph starts a new field; everything until the
    next label is that field's value. Returns (raw_label, canonical_name, value_paragraphs)."""
    fields: list[tuple[str, str, list[ParaInfo]]] = []
    current_label: str | None = None
    current_values: list[ParaInfo] = []

    def flush() -> None:
        if current_label is not None:
            fields.append((current_label, schema.canonical_name(current_label), current_values))

    for p in paragraphs:
        if p.is_label:
            flush()
            current_label = p.text
            current_values = []
        else:
            current_values.append(p)
    flush()
    return fields


def _render_field(raw_label: str, schema: BlockSchema, values: list[ParaInfo]) -> str:
    """Render shape (labeled line vs. bullet list) is auto-detected from the collected
    content, not declared in config."""
    display = schema.display_label(raw_label)
    bullets = [v for v in values if v.is_bullet]
    if bullets:
        lines = "\n".join(f"- {v.text}" for v in bullets)
        return f"**{display}:**\n{lines}"
    return f"**{display}:** {' '.join(v.text for v in values)}"


def _slug_tag(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _collect_tags(
    name: str, fields: list[tuple[str, str, list[ParaInfo]]], schema: BlockSchema
) -> list[str]:
    tags: list[str] = []
    for tag_field in schema.tag_fields:
        if tag_field == "name":
            tags.append(_slug_tag(name))
            continue
        for _raw_label, canonical, values in fields:
            if canonical == tag_field:
                tags.extend(_slug_tag(v.text) for v in values)
    return tags


def extract_block(row: dict, schema: BlockSchema, style_defaults: dict[str, bool]) -> Block:
    """One blocks-table row -> one flat-Markdown Block. Deterministic, no LLM."""
    cells = row.get("tableCells", [])
    primary = _iter_cell_paragraphs(cells[0].get("content", []), style_defaults) if cells else []
    details = (
        _iter_cell_paragraphs(cells[1].get("content", []), style_defaults) if len(cells) > 1 else []
    )

    name, description = _split_primary(primary)
    fields = _split_details(details, schema)

    body_lines = [f"## {name}", ""]
    if description:
        body_lines += [description, ""]
    for raw_label, _canonical, values in fields:
        body_lines.append(_render_field(raw_label, schema, values))
        body_lines.append("")
    body = "\n".join(body_lines).strip() + "\n"

    return Block(
        id="",
        body=body,
        schema=schema.name,
        tags=_collect_tags(name, fields, schema),
        created_by="dissected",
    )
