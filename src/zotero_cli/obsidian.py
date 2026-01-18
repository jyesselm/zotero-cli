"""Obsidian integration for Zotero CLI."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from zotero_cli.models import ZoteroItem


@dataclass
class ObsidianConfig:
    """Configuration for Obsidian integration."""

    vault_path: Path
    literature_folder: str = "References"
    template: str | None = None
    use_citekey: bool = True  # Use Author2024 style filenames


DEFAULT_TEMPLATE = '''---
title: "{title}"
authors: [{authors}]
year: {year}
journal: "{journal}"
doi: "{doi}"
zotero_key: "{key}"
zotero_id: {item_id}
tags: [{tags}]
created: {created}
---

# {title}

**Authors:** {authors_full}
**Year:** {year}
**Journal:** {journal}
**DOI:** {doi_link}

## Zotero Links
- [Open in Zotero](zotero://select/items/0_{key})
- [Open PDF](zotero://open-pdf/library/items/{pdf_key})

## Tags
{tag_list}

## Abstract
{abstract}

## Notes

## Key Points
-

## Questions
-

## Related
-
'''


def get_zotero_uri(item: ZoteroItem, uri_type: str = "select") -> str:
    """Generate a Zotero URI for an item.

    Args:
        item: The Zotero item
        uri_type: Type of URI - "select" (open in Zotero) or "open-pdf"

    Returns:
        Zotero URI string
    """
    if uri_type == "select":
        # Format: zotero://select/items/0_{key} (0 = personal library)
        # This format works across Zotero 5, 6, and 7
        return f"zotero://select/items/0_{item.key}"
    elif uri_type == "open-pdf":
        return f"zotero://open-pdf/library/items/{item.key}"
    else:
        return f"zotero://select/items/0_{item.key}"


def generate_note_content(
    item: ZoteroItem,
    template: str | None = None,
    pdf_key: str | None = None,
) -> str:
    """Generate Obsidian note content for a Zotero item.

    Args:
        item: The Zotero item
        template: Optional custom template
        pdf_key: Key for PDF attachment (if different from item key)

    Returns:
        Formatted markdown content
    """
    if template is None:
        template = DEFAULT_TEMPLATE

    # Prepare template variables
    authors_list = ", ".join(f'"{a}"' for a in item.authors) if item.authors else ""
    authors_full = ", ".join(item.authors) if item.authors else "Unknown"
    tags_yaml = ", ".join(f'"{t}"' for t in item.tags) if item.tags else ""
    tag_list = "\n".join(f"- #{t.replace('/', '-')}" for t in item.tags) if item.tags else "- None"
    doi_link = f"[{item.doi}](https://doi.org/{item.doi})" if item.doi else "-"

    content = template.format(
        title=item.title.replace('"', '\\"'),
        authors=authors_list,
        authors_full=authors_full,
        year=item.year or "",
        journal=item.journal or "",
        doi=item.doi or "",
        doi_link=doi_link,
        key=item.key,
        item_id=item.item_id,
        tags=tags_yaml,
        tag_list=tag_list,
        created=datetime.now().strftime("%Y-%m-%d"),
        abstract=item.abstract or "No abstract available.",
        pdf_key=pdf_key or item.key,
    )

    return content


def get_note_filename(item: ZoteroItem, use_citekey: bool = True) -> str:
    """Generate a filename for the Obsidian note.

    Args:
        item: The Zotero item
        use_citekey: If True, use "Author2024" style, else use title

    Returns:
        Filename (without .md extension)
    """
    if use_citekey:
        return item.citation_key
    else:
        # Clean title for filename
        title = item.title[:50]
        # Remove invalid characters
        for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            title = title.replace(char, '')
        return title.strip()


def create_literature_note(
    item: ZoteroItem,
    vault_path: Path,
    folder: str = "References",
    template: str | None = None,
    use_citekey: bool = True,
    overwrite: bool = False,
) -> Path:
    """Create a literature note in Obsidian vault.

    Args:
        item: The Zotero item
        vault_path: Path to Obsidian vault
        folder: Folder within vault for literature notes
        template: Optional custom template
        use_citekey: Use citation key as filename
        overwrite: Overwrite existing note

    Returns:
        Path to created note

    Raises:
        FileExistsError: If note exists and overwrite=False
    """
    # Create folder if needed
    note_folder = vault_path / folder
    note_folder.mkdir(parents=True, exist_ok=True)

    # Generate filename
    filename = get_note_filename(item, use_citekey)
    note_path = note_folder / f"{filename}.md"

    # Check for existing
    if note_path.exists() and not overwrite:
        raise FileExistsError(f"Note already exists: {note_path}")

    # Generate content
    content = generate_note_content(item, template)

    # Write note
    note_path.write_text(content)

    return note_path


def find_related_notes(
    item: ZoteroItem,
    vault_path: Path,
    search_folders: list[str] | None = None,
) -> list[Path]:
    """Find notes in vault that might be related to this item.

    Searches for:
    - Notes mentioning the item key
    - Notes with matching tags
    - Notes mentioning author names

    Args:
        item: The Zotero item
        vault_path: Path to Obsidian vault
        search_folders: Folders to search (None = entire vault)

    Returns:
        List of paths to potentially related notes
    """
    related = []

    # Determine search paths
    if search_folders:
        search_paths = [vault_path / folder for folder in search_folders]
    else:
        search_paths = [vault_path]

    # Search terms
    search_terms = [item.key]
    if item.first_author:
        search_terms.append(item.first_author)
    search_terms.extend(item.tags[:3])  # Top 3 tags

    for search_path in search_paths:
        if not search_path.exists():
            continue

        for note_path in search_path.rglob("*.md"):
            try:
                content = note_path.read_text()
                for term in search_terms:
                    if term and term.lower() in content.lower():
                        if note_path not in related:
                            related.append(note_path)
                        break
            except Exception:
                continue

    return related


def get_obsidian_link(note_path: Path, vault_path: Path) -> str:
    """Generate an Obsidian wikilink for a note.

    Args:
        note_path: Path to the note
        vault_path: Path to the vault

    Returns:
        Obsidian wikilink string
    """
    relative = note_path.relative_to(vault_path)
    name = relative.stem
    return f"[[{name}]]"


def detect_vault_path() -> Path | None:
    """Try to detect the Obsidian vault path.

    Checks common locations and environment variables.

    Returns:
        Path to vault or None if not found
    """
    # Check environment variable
    import os
    if "OBSIDIAN_VAULT" in os.environ:
        path = Path(os.environ["OBSIDIAN_VAULT"])
        if path.exists():
            return path

    # Check common locations
    home = Path.home()
    common_paths = [
        home / "Documents" / "Obsidian",
        home / "Obsidian",
        home / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents",
        home / "Dropbox" / "Obsidian",
    ]

    for path in common_paths:
        if path.exists():
            # Look for .obsidian folder
            vaults = [p.parent for p in path.rglob(".obsidian") if p.is_dir()]
            if vaults:
                return vaults[0]

    return None
