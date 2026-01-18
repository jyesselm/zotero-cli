"""Interactive fzf-based browser for Zotero."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from zotero_cli.database import ZoteroDatabase
from zotero_cli.models import ZoteroItem


def format_item_for_fzf(item: ZoteroItem) -> str:
    """Format item as a single line for fzf.

    Format: ID | Year | FirstAuthor | Title | Tags
    This allows fzf to search across all fields.
    """
    tags = ",".join(item.tags) if item.tags else ""
    authors = ",".join(item.authors) if item.authors else ""
    return (
        f"{item.item_id}\t"
        f"{item.year}\t"
        f"{item.first_author}\t"
        f"{item.title}\t"
        f"{tags}\t"
        f"{authors}\t"
        f"{item.journal}"
    )


def parse_fzf_line(line: str) -> int | None:
    """Extract item ID from fzf output line."""
    if not line:
        return None
    parts = line.split("\t")
    if parts:
        try:
            return int(parts[0])
        except ValueError:
            return None
    return None


def create_preview_script(db_path: Path, storage_path: Path) -> Path:
    """Create a preview script for fzf."""
    script = f'''#!/usr/bin/env python3
import sqlite3
import shutil
import sys
import tempfile
from pathlib import Path

DB_PATH = Path("{db_path}")
STORAGE_PATH = Path("{storage_path}")

def get_item_preview(item_id: int) -> str:
    # Copy DB to avoid locks
    temp_db = Path(tempfile.mktemp(suffix=".sqlite"))
    shutil.copy2(DB_PATH, temp_db)

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row

    try:
        # Get item data
        cursor = conn.execute("""
            SELECT i.itemID, i.key, it.typeName,
                MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date,
                MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract,
                MAX(CASE WHEN f.fieldName='publicationTitle' THEN idv.value END) as journal,
                MAX(CASE WHEN f.fieldName='DOI' THEN idv.value END) as doi
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            LEFT JOIN itemData id ON i.itemID = id.itemID
            LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
            LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE i.itemID = ?
            GROUP BY i.itemID
        """, (item_id,))
        row = cursor.fetchone()

        if not row:
            return "Item not found"

        # Get authors
        cursor = conn.execute("""
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
        """, (item_id,))
        authors = [f"{{r['firstName']}} {{r['lastName']}}".strip() for r in cursor.fetchall()]

        # Get tags
        cursor = conn.execute("""
            SELECT t.name FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID = ?
            ORDER BY t.name
        """, (item_id,))
        tags = [r["name"] for r in cursor.fetchall()]

        # Get PDF path
        cursor = conn.execute("""
            SELECT i.key
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            WHERE ia.parentItemID = ?
            AND (ia.contentType = 'application/pdf' OR ia.path LIKE '%.pdf')
            LIMIT 1
        """, (item_id,))
        pdf_row = cursor.fetchone()
        has_pdf = False
        if pdf_row:
            storage_dir = STORAGE_PATH / pdf_row["key"]
            has_pdf = storage_dir.exists() and list(storage_dir.glob("*.pdf"))

        # Format output
        lines = []
        lines.append(f"\\033[1;36m{{row['title'] or 'No title'}}\\033[0m")
        lines.append("")
        lines.append(f"\\033[1mAuthors:\\033[0m {{', '.join(authors) if authors else 'Unknown'}}")
        lines.append(f"\\033[1mDate:\\033[0m {{row['date'] or '-'}}")
        lines.append(f"\\033[1mJournal:\\033[0m {{row['journal'] or '-'}}")
        lines.append(f"\\033[1mType:\\033[0m {{row['typeName']}}")
        lines.append(f"\\033[1mDOI:\\033[0m {{row['doi'] or '-'}}")
        lines.append(f"\\033[1mKey:\\033[0m {{row['key']}}")
        lines.append(f"\\033[1mPDF:\\033[0m {{'Yes' if has_pdf else 'No'}}")
        lines.append("")

        if tags:
            lines.append(f"\\033[1mTags:\\033[0m \\033[33m{{', '.join(tags)}}\\033[0m")
        else:
            lines.append(f"\\033[1mTags:\\033[0m \\033[2mnone\\033[0m")
        lines.append("")

        if row["abstract"]:
            lines.append("\\033[1mAbstract:\\033[0m")
            # Word wrap abstract
            abstract = row["abstract"]
            words = abstract.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 > 70:
                    lines.append(current_line)
                    current_line = word
                else:
                    current_line = current_line + " " + word if current_line else word
            if current_line:
                lines.append(current_line)

        return "\\n".join(lines)
    finally:
        conn.close()
        temp_db.unlink()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    line = sys.argv[1]
    parts = line.split("\\t")
    if not parts:
        sys.exit(1)

    try:
        item_id = int(parts[0])
        print(get_item_preview(item_id))
    except (ValueError, IndexError):
        print("Invalid input")
'''

    script_path = Path(tempfile.mktemp(suffix="_zot_preview.py"))
    script_path.write_text(script)
    script_path.chmod(0o755)
    return script_path


def run_interactive(
    db: ZoteroDatabase,
    initial_query: str = "",
    action: str = "show",
) -> list[int]:
    """Run interactive fzf browser.

    Args:
        db: Database instance
        initial_query: Initial search query
        action: Action to perform on selection (show, open, tag)

    Returns:
        List of selected item IDs
    """
    # Check if fzf is available
    if subprocess.run(["which", "fzf"], capture_output=True).returncode != 0:
        raise RuntimeError("fzf is not installed. Install with: brew install fzf")

    # Get all items
    items = db.search(limit=1000)

    if not items:
        return []

    # Create preview script
    preview_script = create_preview_script(db.db_path, db.storage_path)

    try:
        # Format items for fzf
        lines = [format_item_for_fzf(item) for item in items]
        input_text = "\n".join(lines)

        # Build fzf command
        header = "Search: <field>:<value> | Enter=select | Ctrl-O=open PDF | Ctrl-T=add tag | Ctrl-Y=copy DOI"

        fzf_cmd = [
            "fzf",
            "--ansi",
            "--multi",
            "--delimiter=\t",
            "--with-nth=2,3,4,5",  # Show Year, Author, Title, Tags
            f"--preview=python3 {preview_script} {{}}",
            "--preview-window=right:50%:wrap",
            f"--header={header}",
            "--bind=ctrl-o:execute-silent(echo open {{1}} > /tmp/zot_action)+abort",
            "--bind=ctrl-t:execute-silent(echo tag {{1}} > /tmp/zot_action)+abort",
            "--bind=ctrl-y:execute-silent(echo copy {{1}} > /tmp/zot_action)+abort",
            "--color=header:italic",
            "--layout=reverse",
            "--border=rounded",
            "--prompt=zot> ",
        ]

        if initial_query:
            fzf_cmd.append(f"--query={initial_query}")

        # Run fzf
        result = subprocess.run(
            fzf_cmd,
            input=input_text,
            capture_output=True,
            text=True,
        )

        # Check for action file
        action_file = Path("/tmp/zot_action")
        if action_file.exists():
            action_content = action_file.read_text().strip()
            action_file.unlink()

            parts = action_content.split()
            if len(parts) >= 2:
                action_type = parts[0]
                item_id = int(parts[1])
                return [(action_type, item_id)]

        # Parse selected items
        if result.returncode == 0 and result.stdout.strip():
            selected = []
            for line in result.stdout.strip().split("\n"):
                item_id = parse_fzf_line(line)
                if item_id:
                    selected.append(("select", item_id))
            return selected

        return []

    finally:
        # Clean up preview script
        if preview_script.exists():
            preview_script.unlink()


def run_tag_selector(db: ZoteroDatabase, item_id: int) -> str | None:
    """Run fzf to select a tag to add."""
    tags = db.get_all_tags()

    # Get current item tags
    item = db.get_item(item_id=item_id)
    current_tags = set(item.tags) if item else set()

    # Format tags for fzf
    lines = []
    for tag in tags:
        if tag.name not in current_tags:
            lines.append(f"{tag.name}\t({tag.count})")

    if not lines:
        return None

    input_text = "\n".join(lines)

    fzf_cmd = [
        "fzf",
        "--ansi",
        "--delimiter=\t",
        "--with-nth=1",
        "--header=Select tag to add (or type new tag)",
        "--print-query",
        "--layout=reverse",
        "--border=rounded",
        "--prompt=tag> ",
    ]

    result = subprocess.run(
        fzf_cmd,
        input=input_text,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and result.stdout.strip():
        lines = result.stdout.strip().split("\n")
        # First line is query, second is selection (if any)
        if len(lines) >= 2 and lines[1]:
            return lines[1].split("\t")[0]
        elif lines[0]:
            return lines[0]  # Use typed query as new tag

    return None
