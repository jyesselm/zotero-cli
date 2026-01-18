"""Interactive fzf-based browser for Zotero."""

import json
import os
import re
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


def parse_search_query(query: str) -> dict:
    """Parse a search query with field prefixes.

    Supports:
        a:name or author:name - filter by author
        y:2024 or year:2024 - filter by year
        t:tag or tag:tag - filter by tag
        j:journal or journal:journal - filter by journal
        plain text - search title/abstract

    Returns dict with keys: author, year, tag, journal, query
    """
    result = {
        "author": None,
        "year": None,
        "tag": None,
        "journal": None,
        "query": None,
    }

    # Extract field:value patterns
    patterns = [
        (r'\b(?:a|author):(\S+)', 'author'),
        (r'\b(?:y|year):(\S+)', 'year'),
        (r'\b(?:t|tag):(\S+)', 'tag'),
        (r'\b(?:j|journal):(\S+)', 'journal'),
    ]

    remaining = query
    for pattern, field in patterns:
        match = re.search(pattern, remaining, re.IGNORECASE)
        if match:
            result[field] = match.group(1)
            remaining = remaining[:match.start()] + remaining[match.end():]

    # Remaining text is the general query
    remaining = remaining.strip()
    if remaining:
        result["query"] = remaining

    return result


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


def create_filter_script(db_path: Path, storage_path: Path) -> Path:
    """Create a filter script for fzf dynamic reloading."""
    script = f'''#!/usr/bin/env python3
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

DB_PATH = Path("{db_path}")
STORAGE_PATH = Path("{storage_path}")

def parse_year_filter(year_str):
    """Parse year filter supporting ranges and wildcards.

    Supports:
        2024 - exact year
        2020-2024 - range
        2020+ - 2020 and later
        -2020 - 2020 and earlier
        202* - wildcard (2020-2029)

    Returns: (min_year, max_year) or None
    """
    if not year_str:
        return None

    # Range: 2020-2024
    range_match = re.match(r'(\\d{{4}})-(\\d{{4}})', year_str)
    if range_match:
        return (int(range_match.group(1)), int(range_match.group(2)))

    # 2020+ (2020 and later)
    if year_str.endswith('+'):
        return (int(year_str[:-1]), 9999)

    # -2020 (2020 and earlier)
    if year_str.startswith('-'):
        return (0, int(year_str[1:]))

    # Wildcard: 202* -> 2020-2029
    if '*' in year_str:
        prefix = year_str.replace('*', '')
        min_year = int(prefix + '0' * (4 - len(prefix)))
        max_year = int(prefix + '9' * (4 - len(prefix)))
        return (min_year, max_year)

    # Exact year
    try:
        year = int(year_str)
        return (year, year)
    except ValueError:
        return None

def wildcard_to_sql(value):
    """Convert wildcard * to SQL LIKE pattern %."""
    if value and '*' in value:
        return value.replace('*', '%')
    return value

def parse_query(query):
    result = {{"author": None, "year": None, "tag": None, "journal": None, "query": None}}
    patterns = [
        (r'\\b(?:a|author):(\\S+)', 'author'),
        (r'\\b(?:y|year):(\\S+)', 'year'),
        (r'\\b(?:t|tag):(\\S+)', 'tag'),
        (r'\\b(?:j|journal):(\\S+)', 'journal'),
    ]
    remaining = query
    for pattern, field in patterns:
        match = re.search(pattern, remaining, re.IGNORECASE)
        if match:
            result[field] = match.group(1)
            remaining = remaining[:match.start()] + remaining[match.end():]
    remaining = remaining.strip()
    if remaining:
        result["query"] = remaining
    return result

def search_items(filters):
    temp_db = Path(tempfile.mktemp(suffix=".sqlite"))
    shutil.copy2(DB_PATH, temp_db)
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row

    try:
        sql = """
            SELECT DISTINCT i.itemID, i.key, it.typeName,
                MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date,
                MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract,
                MAX(CASE WHEN f.fieldName='publicationTitle' THEN idv.value END) as journal
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            LEFT JOIN itemData id ON i.itemID = id.itemID
            LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
            LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
            LEFT JOIN deletedItems di ON i.itemID = di.itemID
            WHERE di.itemID IS NULL
            AND it.typeName NOT IN ('attachment', 'note')
        """
        params = []

        if filters["tag"]:
            tag_pattern = wildcard_to_sql(filters["tag"])
            if '*' not in filters["tag"]:
                tag_pattern = f"%{{tag_pattern}}%"
            sql += """
                AND i.itemID IN (
                    SELECT itemID FROM itemTags it2
                    JOIN tags t ON it2.tagID = t.tagID
                    WHERE LOWER(t.name) LIKE LOWER(?)
                )
            """
            params.append(tag_pattern)

        sql += " GROUP BY i.itemID"

        # Wrap for text filtering
        needs_wrap = filters["query"] or filters["year"] or filters["journal"]
        if needs_wrap:
            sql = f"SELECT * FROM ({{sql}}) AS subq WHERE 1=1"
            if filters["query"]:
                sql += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(abstract) LIKE LOWER(?))"
                params.extend([f"%{{filters['query']}}%", f"%{{filters['query']}}%"])
            if filters["year"]:
                year_range = parse_year_filter(filters["year"])
                if year_range:
                    min_year, max_year = year_range
                    if min_year == max_year:
                        sql += " AND date LIKE ?"
                        params.append(f"{{min_year}}%")
                    else:
                        sql += " AND CAST(SUBSTR(date, 1, 4) AS INTEGER) BETWEEN ? AND ?"
                        params.extend([min_year, max_year])
            if filters["journal"]:
                journal_pattern = wildcard_to_sql(filters["journal"])
                if '*' not in filters["journal"]:
                    journal_pattern = f"%{{journal_pattern}}%"
                sql += " AND LOWER(journal) LIKE LOWER(?)"
                params.append(journal_pattern)

        sql += " ORDER BY date DESC LIMIT 500"

        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            item_id = row["itemID"]

            # Get authors
            cursor2 = conn.execute("""
                SELECT c.firstName, c.lastName FROM itemCreators ic
                JOIN creators c ON ic.creatorID = c.creatorID
                WHERE ic.itemID = ? ORDER BY ic.orderIndex
            """, (item_id,))
            authors = [f"{{r['firstName']}} {{r['lastName']}}".strip() for r in cursor2.fetchall()]

            # Filter by author if specified (supports wildcards)
            if filters["author"]:
                author_filter = filters["author"].lower()
                if '*' in author_filter:
                    # Wildcard matching
                    import fnmatch
                    pattern = author_filter
                    if not any(fnmatch.fnmatch(a.lower(), pattern) for a in authors):
                        continue
                else:
                    # Substring matching
                    if not any(author_filter in a.lower() for a in authors):
                        continue

            first_author = authors[0].split()[-1] if authors else ""

            # Get tags
            cursor2 = conn.execute("""
                SELECT t.name FROM itemTags it
                JOIN tags t ON it.tagID = t.tagID
                WHERE it.itemID = ? ORDER BY t.name
            """, (item_id,))
            tags = [r["name"] for r in cursor2.fetchall()]

            # Extract year
            date = row["date"] or ""
            year = date[:4] if date else ""

            # Format output
            tags_str = ",".join(tags) if tags else ""
            authors_str = ",".join(authors) if authors else ""
            title = row["title"] or ""
            journal = row["journal"] or ""

            results.append(f"{{item_id}}\\t{{year}}\\t{{first_author}}\\t{{title}}\\t{{tags_str}}\\t{{authors_str}}\\t{{journal}}")

        return results
    finally:
        conn.close()
        temp_db.unlink()

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    filters = parse_query(query)
    for line in search_items(filters):
        print(line)
'''
    script_path = Path(tempfile.mktemp(suffix="_zot_filter.py"))
    script_path.write_text(script)
    script_path.chmod(0o755)
    return script_path


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

    # Create scripts
    preview_script = create_preview_script(db.db_path, db.storage_path)
    filter_script = create_filter_script(db.db_path, db.storage_path)

    try:
        # Get initial items
        items = db.search(limit=500)
        if not items:
            return []

        # Format items for fzf
        lines = [format_item_for_fzf(item) for item in items]
        input_text = "\n".join(lines)

        # Build fzf command with dynamic reload
        header = "a:name y:2020-2024 y:2020+ t:method/* j:nat* | Enter=Zotero Ctrl-O=PDF Ctrl-T=tag"

        fzf_cmd = [
            "fzf",
            "--ansi",
            "--multi",
            "--delimiter=\t",
            "--with-nth=2,3,4,5",  # Show Year, Author, Title, Tags
            f"--preview=python3 {preview_script} {{}}",
            "--preview-window=right:50%:wrap",
            f"--header={header}",
            f"--bind=change:reload:python3 {filter_script} {{q}} || true",
            "--bind=ctrl-o:execute-silent(echo open {{1}} > /tmp/zot_action)+abort",
            "--bind=ctrl-t:execute-silent(echo tag {{1}} > /tmp/zot_action)+abort",
            "--bind=ctrl-y:execute-silent(echo copy {{1}} > /tmp/zot_action)+abort",
            "--color=header:italic",
            "--layout=reverse",
            "--border=rounded",
            "--prompt=zot> ",
            "--disabled",  # Disable fzf filtering, we handle it via reload
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
        # Clean up scripts
        if preview_script.exists():
            preview_script.unlink()
        if filter_script.exists():
            filter_script.unlink()


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
