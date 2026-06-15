"""Command-line interface for Zotero."""

import subprocess
import sys
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from zotero_cli.database import ZoteroDatabase
from zotero_cli.models import ZoteroItem
from zotero_cli.suggest import suggest_tags

app = typer.Typer(
    name="zot",
    help="Command-line interface for managing Zotero library",
    invoke_without_command=True,
)
console = Console()


def get_db() -> ZoteroDatabase:
    """Get database instance."""
    return ZoteroDatabase()


def format_item_row(item: ZoteroItem) -> tuple:
    """Format item for table display."""
    authors = item.first_author if item.authors else ""
    tags = ", ".join(item.tags[:3])
    if len(item.tags) > 3:
        tags += f" (+{len(item.tags) - 3})"
    return (
        str(item.item_id),
        item.year,
        authors,
        item.short_title(50),
        tags,
    )


@app.command()
def search(
    query: str = typer.Argument(None, help="Search query for title/abstract"),
    author: str = typer.Option(None, "--author", "-a", help="Filter by author name"),
    tag: str = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    collection: str = typer.Option(None, "--collection", "-c", help="Filter by collection"),
    year: str = typer.Option(None, "--year", "-y", help="Filter by year"),
    item_type: str = typer.Option(None, "--type", help="Filter by item type"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """Search for items in your Zotero library."""
    db = get_db()
    items = db.search(
        query=query,
        author=author,
        tag=tag,
        collection=collection,
        year=year,
        item_type=item_type,
        limit=limit,
    )

    if not items:
        rprint("[yellow]No items found.[/yellow]")
        return

    table = Table(title=f"Search Results ({len(items)} items)")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Year", no_wrap=True)
    table.add_column("Author", max_width=15)
    table.add_column("Title", max_width=45)
    table.add_column("Tags", style="cyan", max_width=25)

    for item in items:
        table.add_row(*format_item_row(item))

    console.print(table)


@app.command("list")
def list_items(
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    untagged: bool = typer.Option(False, "--untagged", "-u", help="Show only untagged items"),
):
    """List recent items in your library."""
    db = get_db()

    if untagged:
        items = db.get_untagged_items(limit=limit)
        title = f"Untagged Items ({len(items)} items)"
    else:
        items = db.search(limit=limit)
        title = f"Recent Items ({len(items)} items)"

    if not items:
        rprint("[yellow]No items found.[/yellow]")
        return

    table = Table(title=title)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Year", no_wrap=True)
    table.add_column("Author", max_width=15)
    table.add_column("Title", max_width=45)
    table.add_column("Tags", style="cyan", max_width=25)

    for item in items:
        table.add_row(*format_item_row(item))

    console.print(table)


@app.command()
def show(
    item_id: int = typer.Argument(..., help="Item ID to show"),
):
    """Show detailed information about an item."""
    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    # Title panel
    console.print(Panel(item.title, title="Title", border_style="blue"))

    # Metadata
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold", width=12)
    table.add_column("Value")

    table.add_row("Type", item.item_type)
    table.add_row("Authors", ", ".join(item.authors) if item.authors else "-")
    table.add_row("Date", item.date or "-")
    table.add_row("Journal", item.journal or "-")
    table.add_row("DOI", item.doi or "-")
    table.add_row("Key", item.key)
    table.add_row("ID", str(item.item_id))

    console.print(table)

    # Tags
    if item.tags:
        rprint(f"\n[bold]Tags:[/bold] [cyan]{', '.join(item.tags)}[/cyan]")
    else:
        rprint("\n[bold]Tags:[/bold] [dim]none[/dim]")

    # Collections
    if item.collections:
        rprint(f"[bold]Collections:[/bold] {', '.join(item.collections)}")

    # PDF
    if item.pdf_path:
        rprint(f"[bold]PDF:[/bold] [green]{item.pdf_path}[/green]")
    else:
        rprint("[bold]PDF:[/bold] [dim]not found[/dim]")

    # Abstract
    if item.abstract:
        console.print(Panel(item.abstract, title="Abstract", border_style="dim"))


@app.command()
def abstract(
    item_id: int = typer.Argument(..., help="Item ID"),
):
    """Show just the abstract for an item."""
    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if item.abstract:
        rprint(f"[bold]{item.short_title()}[/bold]\n")
        rprint(item.abstract)
    else:
        rprint("[yellow]No abstract available.[/yellow]")


@app.command("open")
def open_pdf(
    item_id: int = typer.Argument(..., help="Item ID"),
    app_name: str = typer.Option(None, "--app", "-a", help="Application to open with"),
):
    """Open the PDF for an item."""
    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if not item.pdf_path:
        rprint(f"[red]No PDF found for item {item_id}.[/red]")
        raise typer.Exit(1)

    rprint(f"Opening: [green]{item.pdf_path}[/green]")

    if sys.platform == "darwin":
        if app_name:
            subprocess.run(["open", "-a", app_name, str(item.pdf_path)])
        else:
            subprocess.run(["open", str(item.pdf_path)])
    elif sys.platform == "linux":
        subprocess.run(["xdg-open", str(item.pdf_path)])
    else:
        subprocess.run(["start", str(item.pdf_path)], shell=True)


@app.command()
def path(
    item_id: int = typer.Argument(..., help="Item ID"),
):
    """Print the PDF path for an item."""
    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if item.pdf_path:
        print(item.pdf_path)
    else:
        rprint("[red]No PDF found.[/red]")
        raise typer.Exit(1)


# Tag commands
@app.command()
def tags(
    tree: bool = typer.Option(False, "--tree", "-t", help="Show as hierarchy"),
):
    """List all tags with counts."""
    db = get_db()
    all_tags = db.get_all_tags()

    if tree:
        # Group by category
        categories: dict[str, list] = {}
        standalone = []

        for tag in all_tags:
            if tag.category:
                if tag.category not in categories:
                    categories[tag.category] = []
                categories[tag.category].append(tag)
            else:
                standalone.append(tag)

        tree_view = Tree("[bold]Tags[/bold]")

        for cat in sorted(categories.keys()):
            branch = tree_view.add(f"[bold cyan]{cat}/[/bold cyan]")
            for tag in sorted(categories[cat], key=lambda t: t.name):
                branch.add(f"{tag.name.split('/')[-1]} [dim]({tag.count})[/dim]")

        if standalone:
            branch = tree_view.add("[bold]other[/bold]")
            for tag in sorted(standalone, key=lambda t: t.name):
                branch.add(f"{tag.name} [dim]({tag.count})[/dim]")

        console.print(tree_view)
    else:
        table = Table(title="All Tags")
        table.add_column("Tag", style="cyan")
        table.add_column("Count", justify="right")

        for tag in all_tags:
            table.add_row(tag.name, str(tag.count))

        console.print(table)


@app.command()
def tag(
    item_id: int = typer.Argument(..., help="Item ID to tag"),
    tag_name: str = typer.Argument(..., help="Tag to add"),
):
    """Add a tag to an item."""
    db = get_db()

    # Verify item exists
    item = db.get_item(item_id=item_id)
    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if db.add_tag(item_id, tag_name):
        rprint(f"[green]Added tag '{tag_name}' to:[/green] {item.short_title()}")
    else:
        rprint(f"[yellow]Item already has tag '{tag_name}'[/yellow]")


@app.command()
def untag(
    item_id: int = typer.Argument(..., help="Item ID"),
    tag_name: str = typer.Argument(..., help="Tag to remove"),
):
    """Remove a tag from an item."""
    db = get_db()

    item = db.get_item(item_id=item_id)
    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if db.remove_tag(item_id, tag_name):
        rprint(f"[green]Removed tag '{tag_name}' from:[/green] {item.short_title()}")
    else:
        rprint(f"[yellow]Item doesn't have tag '{tag_name}'[/yellow]")


@app.command()
def retag(
    old_tag: str = typer.Argument(..., help="Tag to rename"),
    new_tag: str = typer.Argument(..., help="New tag name"),
):
    """Rename a tag globally."""
    db = get_db()
    count = db.rename_tag(old_tag, new_tag)

    if count > 0:
        rprint(f"[green]Renamed '{old_tag}' → '{new_tag}' ({count} items)[/green]")
    else:
        rprint(f"[yellow]Tag '{old_tag}' not found.[/yellow]")


# Collection commands
@app.command()
def collections(
    tree: bool = typer.Option(False, "--tree", "-t", help="Show as hierarchy"),
):
    """List all collections."""
    db = get_db()
    all_collections = db.get_all_collections()

    if tree:
        # Build tree structure
        tree_view = Tree("[bold]Collections[/bold]")
        coll_map = {c.collection_id: c for c in all_collections}

        # Find root collections
        roots = [c for c in all_collections if c.parent_id is None]

        def add_children(parent_tree, parent_id):
            children = [c for c in all_collections if c.parent_id == parent_id]
            for child in sorted(children, key=lambda c: c.name):
                branch = parent_tree.add(f"{child.name} [dim]({child.item_count})[/dim]")
                add_children(branch, child.collection_id)

        for root in sorted(roots, key=lambda c: c.name):
            branch = tree_view.add(f"[cyan]{root.name}[/cyan] [dim]({root.item_count})[/dim]")
            add_children(branch, root.collection_id)

        console.print(tree_view)
    else:
        table = Table(title="All Collections")
        table.add_column("Collection", style="cyan")
        table.add_column("Items", justify="right")

        for coll in all_collections:
            table.add_row(coll.name, str(coll.item_count))

        console.print(table)


@app.command()
def cite(
    item_id: int = typer.Argument(..., help="Item ID"),
    fmt: str = typer.Option("inline", "--format", "-f", help="Format: inline, bibtex, apa"),
):
    """Generate citation for an item."""
    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if fmt == "bibtex":
        authors_bibtex = " and ".join(item.authors) if item.authors else ""
        print(f"@article{{{item.citation_key},")
        print(f"  title = {{{item.title}}},")
        print(f"  author = {{{authors_bibtex}}},")
        print(f"  year = {{{item.year}}},")
        if item.journal:
            print(f"  journal = {{{item.journal}}},")
        if item.doi:
            print(f"  doi = {{{item.doi}}},")
        print("}")
    elif fmt == "apa":
        authors = ", ".join(item.authors) if item.authors else "Unknown"
        print(f"{authors} ({item.year}). {item.title}. {item.journal or ''}".strip())
    else:
        # Inline format: Author (Year)
        print(f"{item.first_author} ({item.year})")


# Bulk operations
@app.command("tag-collection")
def tag_collection(
    collection_name: str = typer.Argument(..., help="Collection name"),
    tag_name: str = typer.Argument(..., help="Tag to add to all items"),
):
    """Add a tag to all items in a collection."""
    db = get_db()

    # Check collection exists
    collections = db.get_all_collections()
    matching = [c for c in collections if c.name == collection_name]

    if not matching:
        rprint(f"[red]Collection '{collection_name}' not found.[/red]")
        rprint("\nAvailable collections:")
        for c in sorted(collections, key=lambda x: x.name)[:10]:
            rprint(f"  {c.name}")
        raise typer.Exit(1)

    count = db.tag_collection(collection_name, tag_name)
    rprint(f"[green]Added '{tag_name}' to {count} items in '{collection_name}'[/green]")


@app.command()
def duplicates():
    """Find duplicate items by title."""
    db = get_db()
    groups = db.find_duplicates()

    if not groups:
        rprint("[green]No duplicates found![/green]")
        return

    rprint(f"[yellow]Found {len(groups)} duplicate groups:[/yellow]\n")

    for group in groups:
        rprint(f"[bold]{group[0].short_title(60)}[/bold]")
        for item in group:
            tag_info = f"[cyan]{len(item.tags)} tags[/cyan]" if item.tags else "[dim]no tags[/dim]"
            keep = "[green]KEEP[/green]" if item == group[0] else ""
            rprint(f"  {item.item_id:>5}  {tag_info:20} {keep}")
        rprint()


@app.command()
def dedup(
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview or apply changes"),
):
    """Remove duplicate items that have no tags (keeps the tagged version).

    By default runs in dry-run mode. Use --apply to actually delete.
    """
    db = get_db()

    if dry_run:
        rprint("[yellow]DRY RUN - no changes will be made[/yellow]\n")

    to_delete = db.delete_duplicate_untagged(dry_run=dry_run)

    if not to_delete:
        rprint("[green]No untagged duplicates to remove![/green]")
        return

    rprint(f"[yellow]{'Would delete' if dry_run else 'Deleted'} {len(to_delete)} untagged duplicates:[/yellow]\n")

    for item_id, title in to_delete:
        short_title = title[:55] + "..." if len(title) > 55 else title
        rprint(f"  [red]{'×' if not dry_run else '-'}[/red] {item_id:>5}  {short_title}")

    if dry_run:
        rprint(f"\n[dim]Run with --apply to delete these {len(to_delete)} items[/dim]")
    else:
        rprint(f"\n[green]Moved {len(to_delete)} items to Zotero trash[/green]")


# Obsidian integration commands
@app.command()
def note(
    item_id: int = typer.Argument(..., help="Item ID to create note for"),
    vault: str = typer.Option(None, "--vault", "-v", help="Path to Obsidian vault"),
    folder: str = typer.Option("References", "--folder", "-f", help="Folder for literature notes"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing note"),
):
    """Create an Obsidian literature note for an item."""
    from pathlib import Path

    from zotero_cli.obsidian import create_literature_note, detect_vault_path

    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    # Determine vault path
    if vault:
        vault_path = Path(vault)
    else:
        vault_path = detect_vault_path()
        if not vault_path:
            rprint("[red]Could not detect Obsidian vault.[/red]")
            rprint("Set OBSIDIAN_VAULT environment variable or use --vault option.")
            raise typer.Exit(1)

    if not vault_path.exists():
        rprint(f"[red]Vault path does not exist: {vault_path}[/red]")
        raise typer.Exit(1)

    try:
        note_path = create_literature_note(
            item=item,
            vault_path=vault_path,
            folder=folder,
            overwrite=overwrite,
        )
        rprint(f"[green]Created note:[/green] {note_path}")
        rprint(f"[dim]Obsidian link: [[{note_path.stem}]][/dim]")
    except FileExistsError as e:
        rprint(f"[yellow]{e}[/yellow]")
        rprint("Use --overwrite to replace existing note.")
        raise typer.Exit(1)


@app.command()
def link(
    item_id: int = typer.Argument(..., help="Item ID to get link for"),
    link_type: str = typer.Option("select", "--type", "-t", help="Link type: select, pdf, obsidian"),
):
    """Get a link for an item (Zotero URI or Obsidian link)."""
    from zotero_cli.obsidian import get_zotero_uri

    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    if link_type == "select":
        uri = get_zotero_uri(item, "select")
        print(uri)
    elif link_type == "pdf":
        uri = get_zotero_uri(item, "open-pdf")
        print(uri)
    elif link_type == "obsidian":
        # Generate obsidian wikilink
        print(f"[[{item.citation_key}]]")
    else:
        rprint(f"[red]Unknown link type: {link_type}[/red]")
        raise typer.Exit(1)


@app.command("related")
def find_related(
    item_id: int = typer.Argument(..., help="Item ID to find related notes for"),
    vault: str = typer.Option(None, "--vault", "-v", help="Path to Obsidian vault"),
):
    """Find Obsidian notes that might be related to a Zotero item."""
    from pathlib import Path

    from zotero_cli.obsidian import detect_vault_path, find_related_notes

    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    # Determine vault path
    if vault:
        vault_path = Path(vault)
    else:
        vault_path = detect_vault_path()
        if not vault_path:
            rprint("[red]Could not detect Obsidian vault.[/red]")
            raise typer.Exit(1)

    rprint(f"[bold]{item.short_title()}[/bold]")
    rprint(f"Searching vault: {vault_path}\n")

    related = find_related_notes(item, vault_path)

    if not related:
        rprint("[yellow]No related notes found.[/yellow]")
        return

    rprint(f"[green]Found {len(related)} related notes:[/green]")
    for note_path in related:
        rel_path = note_path.relative_to(vault_path)
        rprint(f"  [[{note_path.stem}]] - {rel_path.parent}")


@app.command()
def suggest(
    item_id: int = typer.Argument(..., help="Item ID to get suggestions for"),
    apply: bool = typer.Option(False, "--apply", "-a", help="Apply suggested tags"),
    threshold: float = typer.Option(0.7, "--threshold", "-t", help="Min confidence (0-1)"),
):
    """Suggest tags for an item based on title and abstract."""
    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    rprint(f"[bold]{item.short_title()}[/bold]")
    if item.tags:
        rprint(f"Current tags: [cyan]{', '.join(item.tags)}[/cyan]\n")
    else:
        rprint("Current tags: [dim]none[/dim]\n")

    suggestions = suggest_tags(item, item.tags)
    suggestions = [s for s in suggestions if s.confidence >= threshold]

    if not suggestions:
        rprint("[yellow]No tag suggestions found.[/yellow]")
        return

    table = Table(title="Suggested Tags")
    table.add_column("Tag", style="cyan")
    table.add_column("Confidence", justify="right")
    table.add_column("Reason", style="dim")

    for sug in suggestions:
        conf_color = "green" if sug.confidence >= 0.8 else "yellow"
        table.add_row(
            sug.tag,
            f"[{conf_color}]{sug.confidence:.0%}[/{conf_color}]",
            sug.reason,
        )

    console.print(table)

    if apply:
        rprint("\n[bold]Applying tags...[/bold]")
        for sug in suggestions:
            if db.add_tag(item_id, sug.tag):
                rprint(f"  [green]+[/green] {sug.tag}")
            else:
                rprint(f"  [dim]=[/dim] {sug.tag} (already exists)")


@app.command("suggest-all")
def suggest_all(
    limit: int = typer.Option(20, "--limit", "-n", help="Max items to process"),
    threshold: float = typer.Option(0.8, "--threshold", "-t", help="Min confidence"),
    apply: bool = typer.Option(False, "--apply", "-a", help="Apply suggested tags"),
):
    """Suggest tags for all untagged items."""
    db = get_db()
    items = db.get_untagged_items(limit=limit)

    if not items:
        rprint("[yellow]No untagged items found.[/yellow]")
        return

    rprint(f"[bold]Processing {len(items)} untagged items...[/bold]\n")

    for item in items:
        suggestions = suggest_tags(item, [])
        suggestions = [s for s in suggestions if s.confidence >= threshold]

        if suggestions:
            rprint(f"[bold]{item.item_id}[/bold] {item.short_title(50)}")
            tag_strs = [f"[cyan]{s.tag}[/cyan] ({s.confidence:.0%})" for s in suggestions[:5]]
            rprint(f"  → {', '.join(tag_strs)}")

            if apply:
                for sug in suggestions:
                    db.add_tag(item.item_id, sug.tag)
                rprint("  [green]✓ Applied[/green]")
            rprint()


def _fetch_abstract_pubmed(doi: str) -> str | None:
    """Fetch abstract from PubMed using DOI."""
    import json
    import urllib.request
    import urllib.error
    import xml.etree.ElementTree as ET

    # First, convert DOI to PMID using NCBI's ID converter
    try:
        url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "zotero-cli/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        records = data.get("records", [])
        if not records or "pmid" not in records[0]:
            return None

        pmid = records[0]["pmid"]

        # Now fetch the abstract from PubMed
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
        req = urllib.request.Request(url, headers={"User-Agent": "zotero-cli/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read().decode()

        # Parse XML to extract abstract
        root = ET.fromstring(xml_data)
        abstract_elem = root.find(".//AbstractText")
        if abstract_elem is not None and abstract_elem.text:
            return abstract_elem.text

        # Try finding multiple AbstractText elements (structured abstracts)
        abstract_parts = root.findall(".//AbstractText")
        if abstract_parts:
            parts = []
            for part in abstract_parts:
                label = part.get("Label", "")
                text = part.text or ""
                if label and text:
                    parts.append(f"{label}: {text}")
                elif text:
                    parts.append(text)
            if parts:
                return " ".join(parts)

        return None

    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ET.ParseError):
        return None


@app.command("fix")
def fix_metadata(
    item_id: int = typer.Argument(..., help="Item ID to fix"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be updated"),
):
    """Fill in missing metadata from CrossRef using DOI.

    Looks up the item's DOI and fills in missing fields like
    abstract, journal, volume, pages, etc.
    """
    import json
    import urllib.request
    import urllib.error
    import re

    db = get_db()
    item = db.get_item(item_id=item_id)

    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)

    rprint(f"[bold]{item.title}[/bold]")

    if not item.doi:
        rprint("[red]No DOI found. Cannot look up metadata.[/red]")
        rprint("[dim]Tip: Add DOI manually in Zotero, then run this again.[/dim]")
        raise typer.Exit(1)

    rprint(f"[dim]DOI: {item.doi}[/dim]\n")

    # Fetch from CrossRef
    url = f"https://api.crossref.org/works/{item.doi}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "zotero-cli/1.0",
                "Accept": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        rprint(f"[red]Failed to fetch from CrossRef: {e}[/red]")
        raise typer.Exit(1)

    if "message" not in data:
        rprint("[red]Invalid response from CrossRef[/red]")
        raise typer.Exit(1)

    msg = data["message"]

    # Extract metadata
    updates = {}

    # Abstract - try CrossRef first, then PubMed
    if not item.abstract:
        abstract = None
        if msg.get("abstract"):
            abstract = re.sub(r'<[^>]+>', '', msg["abstract"])  # Strip HTML
        else:
            # Try PubMed
            rprint("[dim]No abstract in CrossRef, trying PubMed...[/dim]")
            abstract = _fetch_abstract_pubmed(item.doi)

        if abstract:
            updates["abstractNote"] = abstract

    # Journal
    if not item.journal and msg.get("container-title"):
        journal = msg["container-title"]
        if isinstance(journal, list):
            journal = journal[0]
        updates["publicationTitle"] = journal

    # Volume, issue, pages
    if msg.get("volume"):
        updates["volume"] = msg["volume"]
    if msg.get("issue"):
        updates["issue"] = msg["issue"]
    if msg.get("page"):
        updates["pages"] = msg["page"]

    # Publisher
    if msg.get("publisher"):
        updates["publisher"] = msg["publisher"]

    # URL
    if not item.url and msg.get("URL"):
        updates["url"] = msg["URL"]

    if not updates:
        rprint("[green]All metadata already present![/green]")
        return

    # Show what will be updated
    rprint("[cyan]Updates available:[/cyan]")
    for field, value in updates.items():
        display_value = value[:60] + "..." if len(str(value)) > 60 else value
        rprint(f"  [bold]{field}:[/bold] {display_value}")

    if dry_run:
        rprint("\n[yellow]Dry run - no changes made[/yellow]")
        return

    # Apply updates
    with db.write_connection() as conn:
        for field_name, value in updates.items():
            # Get field ID
            cursor = conn.execute(
                "SELECT fieldID FROM fieldsCombined WHERE fieldName = ?",
                (field_name,)
            )
            row = cursor.fetchone()
            if not row:
                continue
            field_id = row["fieldID"]

            # Get or create value
            cursor = conn.execute(
                "SELECT valueID FROM itemDataValues WHERE value = ?",
                (value,)
            )
            row = cursor.fetchone()
            if row:
                value_id = row["valueID"]
            else:
                cursor = conn.execute(
                    "INSERT INTO itemDataValues (value) VALUES (?)",
                    (value,)
                )
                value_id = cursor.lastrowid

            # Check if field already exists
            cursor = conn.execute(
                "SELECT 1 FROM itemData WHERE itemID = ? AND fieldID = ?",
                (item_id, field_id)
            )
            if cursor.fetchone():
                # Update existing
                conn.execute(
                    "UPDATE itemData SET valueID = ? WHERE itemID = ? AND fieldID = ?",
                    (value_id, item_id, field_id)
                )
            else:
                # Insert new
                conn.execute(
                    "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
                    (item_id, field_id, value_id)
                )

    rprint(f"\n[green]Updated {len(updates)} fields![/green]")


@app.command("incomplete")
def incomplete_items(
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """List items with DOI but missing metadata (abstract, volume, etc)."""
    db = get_db()

    with db.connection() as conn:
        cursor = conn.execute("""
            SELECT i.itemID,
                MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                MAX(CASE WHEN f.fieldName='DOI' THEN idv.value END) as doi,
                MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract,
                MAX(CASE WHEN f.fieldName='volume' THEN idv.value END) as volume
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            LEFT JOIN itemData id ON i.itemID = id.itemID
            LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
            LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
            LEFT JOIN deletedItems di ON i.itemID = di.itemID
            WHERE di.itemID IS NULL
            AND it.typeName NOT IN ('attachment', 'note')
            GROUP BY i.itemID
            HAVING doi IS NOT NULL AND (abstract IS NULL OR volume IS NULL)
            ORDER BY i.dateAdded DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()

        if not rows:
            rprint("[green]All items with DOIs have complete metadata![/green]")
            return

        table = Table(title=f"Items with incomplete metadata ({len(rows)})")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Title", max_width=50)
        table.add_column("Missing", style="yellow")

        for row in rows:
            missing = []
            if not row["abstract"]:
                missing.append("abstract")
            if not row["volume"]:
                missing.append("vol/pages")
            title = row["title"][:47] + "..." if len(row["title"] or "") > 50 else row["title"]
            table.add_row(str(row["itemID"]), title, ", ".join(missing))

        console.print(table)
        rprint(f"\n[dim]Run 'zot fix <ID>' to fill in missing data from CrossRef[/dim]")


@app.command("recent")
def recent_items(
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
):
    """List recently added items (newest first).

    Useful for finding newly imported PDFs.
    """
    db = get_db()

    with db.connection() as conn:
        cursor = conn.execute("""
            SELECT i.itemID, i.key, i.dateAdded,
                MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            LEFT JOIN itemData id ON i.itemID = id.itemID
            LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
            LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
            LEFT JOIN deletedItems di ON i.itemID = di.itemID
            WHERE di.itemID IS NULL
            AND it.typeName NOT IN ('attachment', 'note')
            GROUP BY i.itemID
            ORDER BY i.dateAdded DESC
            LIMIT ?
        """, (limit,))

        table = Table(title=f"Recently Added ({limit})")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Added", no_wrap=True)
        table.add_column("Title", max_width=60)

        for row in cursor.fetchall():
            date_added = row["dateAdded"][:10] if row["dateAdded"] else ""
            title = row["title"] or "[No title - needs metadata]"
            if not row["title"]:
                title = f"[yellow]{title}[/yellow]"
            table.add_row(str(row["itemID"]), date_added, title)

        console.print(table)


def _extract_doi_from_pdf(pdf_path: Path) -> str | None:
    """Extract DOI from PDF using pdftotext."""
    import re
    try:
        result = subprocess.run(
            ["pdftotext", "-l", "3", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        text = result.stdout

        patterns = [
            r'doi[:\s]*\s*(10\.\d{4,}/[^\s\]>"]+)',
            r'DOI[:\s]*\s*(10\.\d{4,}/[^\s\]>"]+)',
            r'https?://(?:dx\.)?doi\.org/(10\.\d{4,}/[^\s\]>"]+)',
            r'(10\.\d{4,}/[^\s\]>"]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                doi = match.group(1).rstrip('.,;:)')
                if re.match(r'^10\.\d{4,}/', doi):
                    return doi
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _fetch_crossref_metadata(doi: str) -> dict | None:
    """Fetch full metadata from CrossRef."""
    import json
    import urllib.request
    import re

    url = f"https://api.crossref.org/works/{doi}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "zotero-cli/1.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        if "message" not in data:
            return None

        msg = data["message"]
        result = {"doi": doi}

        # Title
        if msg.get("title"):
            result["title"] = msg["title"][0] if isinstance(msg["title"], list) else msg["title"]

        # Authors
        authors = []
        for author in msg.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            authors.append({"first": given, "last": family})
        result["authors"] = authors

        # Abstract
        if msg.get("abstract"):
            result["abstract"] = re.sub(r'<[^>]+>', '', msg["abstract"])

        # Journal
        if msg.get("container-title"):
            j = msg["container-title"]
            result["journal"] = j[0] if isinstance(j, list) else j

        # Date
        for date_field in ["published-print", "published-online", "created"]:
            if date_field in msg:
                date_parts = msg[date_field].get("date-parts", [[]])
                if date_parts and date_parts[0]:
                    result["year"] = str(date_parts[0][0])
                    break

        # Volume, issue, pages
        if msg.get("volume"):
            result["volume"] = msg["volume"]
        if msg.get("issue"):
            result["issue"] = msg["issue"]
        if msg.get("page"):
            result["pages"] = msg["page"]

        return result

    except Exception:
        return None


def _process_pdf(db: ZoteroDatabase, pdf: Path) -> dict:
    """Add a single PDF to Zotero, skipping it if already in the library.

    Extracts the DOI, checks for an existing item (by DOI, then title),
    fetches metadata from CrossRef/PubMed, and inserts the item.

    Returns a dict with a 'status' key, one of:
      - 'added'       -> also has 'item_id' and 'metadata'
      - 'duplicate'   -> also has 'item_id' and 'title'
      - 'no_doi'      -> no DOI could be extracted
      - 'no_metadata' -> also has 'doi'; CrossRef lookup failed
    """
    doi = _extract_doi_from_pdf(pdf)
    if not doi:
        return {"status": "no_doi"}

    # Duplicate check by DOI before doing any network lookup
    existing = db.find_existing_item(doi=doi)
    if existing:
        item = db.get_item(item_id=existing)
        return {"status": "duplicate", "item_id": existing, "title": item.title if item else ""}

    metadata = _fetch_crossref_metadata(doi)
    if not metadata or not metadata.get("title"):
        return {"status": "no_metadata", "doi": doi}

    # Secondary duplicate check by title (catches items added without a DOI)
    existing = db.find_existing_item(title=metadata["title"])
    if existing:
        item = db.get_item(item_id=existing)
        return {
            "status": "duplicate",
            "item_id": existing,
            "title": item.title if item else metadata["title"],
        }

    # Fill in abstract from PubMed if CrossRef didn't have one
    if not metadata.get("abstract"):
        abstract = _fetch_abstract_pubmed(doi)
        if abstract:
            metadata["abstract"] = abstract

    item_id = db.add_item(metadata, pdf)
    return {"status": "added", "item_id": item_id, "metadata": metadata}


def _remove_original(pdf: Path, to_trash: bool, quiet: bool = False) -> None:
    """Delete or (on macOS) move the original PDF to the trash."""
    if to_trash and sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{pdf}"']
        )
        if not quiet:
            rprint(f"[green]Moved to trash:[/green] {pdf.name}")
    else:
        pdf.unlink()
        if not quiet:
            rprint(f"[green]Deleted:[/green] {pdf.name}")


@app.command("check")
def check_pdf(
    pdf_path: str = typer.Argument(..., help="Path to PDF file"),
):
    """Check if a PDF's paper is already in your library.

    Extracts DOI from the PDF and searches for it in Zotero.
    """
    from pathlib import Path

    pdf = Path(pdf_path).expanduser().resolve()

    if not pdf.exists():
        rprint(f"[red]File not found: {pdf}[/red]")
        raise typer.Exit(1)

    # Extract DOI
    doi = _extract_doi_from_pdf(pdf)

    if not doi:
        rprint(f"[yellow]No DOI found in:[/yellow] {pdf.name}")
        raise typer.Exit(1)

    rprint(f"[dim]DOI:[/dim] {doi}")

    # Check if exists
    db = get_db()
    with db.connection() as conn:
        cursor = conn.execute("""
            SELECT i.itemID
            FROM items i
            JOIN itemData id ON i.itemID = id.itemID
            JOIN fieldsCombined f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            LEFT JOIN deletedItems di ON i.itemID = di.itemID
            WHERE f.fieldName = 'DOI' AND idv.value = ?
            AND di.itemID IS NULL
        """, (doi,))
        existing = cursor.fetchone()

        if existing:
            item = db.get_item(item_id=existing["itemID"])
            rprint(f"\n[green]✓ Found in library (ID: {existing['itemID']}):[/green]")
            rprint(f"  [bold]{item.title}[/bold]")
            if item.authors:
                rprint(f"  [dim]Authors:[/dim] {', '.join(item.authors[:3])}")
            if item.year:
                rprint(f"  [dim]Year:[/dim] {item.year}")
            if item.tags:
                rprint(f"  [dim]Tags:[/dim] {', '.join(item.tags)}")
        else:
            rprint(f"\n[yellow]✗ Not in library[/yellow]")
            rprint(f"[dim]Use 'zot add {pdf}' to add it[/dim]")


@app.command("add")
def add_pdf(
    pdf_path: str = typer.Argument(..., help="Path to PDF file"),
    delete: bool = typer.Option(False, "--delete", "-d", help="Delete original after adding"),
    move_to_trash: bool = typer.Option(False, "--trash", "-t", help="Move original to trash after adding"),
):
    """Add a PDF directly to Zotero with automatic metadata lookup.

    Extracts DOI from PDF, fetches metadata from CrossRef/PubMed, and adds
    directly to the Zotero database (no UI interaction needed). Papers already
    in your library (matched by DOI or title) are not added again.

    Example:
        zot add paper.pdf --trash
    """
    from pathlib import Path

    pdf = Path(pdf_path).expanduser().resolve()

    if not pdf.exists():
        rprint(f"[red]File not found: {pdf}[/red]")
        raise typer.Exit(1)

    if not pdf.suffix.lower() == ".pdf":
        rprint(f"[yellow]Warning: File may not be a PDF: {pdf.suffix}[/yellow]")

    db = get_db()
    rprint(f"[dim]Processing {pdf.name}...[/dim]")
    result = _process_pdf(db, pdf)
    status = result["status"]

    if status == "no_doi":
        rprint("[red]No DOI found in PDF. Cannot add without metadata.[/red]")
        rprint("[dim]Tip: Add manually in Zotero or provide a PDF with DOI.[/dim]")
        raise typer.Exit(1)

    if status == "no_metadata":
        rprint(f"[red]Could not fetch metadata from CrossRef for DOI: {result['doi']}[/red]")
        raise typer.Exit(1)

    if status == "duplicate":
        rprint(f"\n[yellow]⚠ Already in library (ID: {result['item_id']}):[/yellow]")
        rprint(f"  [bold]{result['title']}[/bold]")
        rprint(f"\n[dim]Use 'zot show {result['item_id']}' to view details[/dim]")
        if delete:
            _remove_original(pdf, to_trash=False)
        elif move_to_trash:
            _remove_original(pdf, to_trash=True)
        raise typer.Exit(0)

    # status == "added"
    metadata = result["metadata"]
    rprint(f"\n[green]✓ Added to Zotero (ID: {result['item_id']}):[/green]")
    rprint(f"  [bold]{metadata.get('title')}[/bold]")
    if metadata.get("authors"):
        author_str = ", ".join(f"{a['first']} {a['last']}" for a in metadata["authors"][:3])
        if len(metadata["authors"]) > 3:
            author_str += f" +{len(metadata['authors'])-3} more"
        rprint(f"  [dim]Authors:[/dim] {author_str}")
    if metadata.get("year"):
        rprint(f"  [dim]Year:[/dim] {metadata['year']}")
    if metadata.get("journal"):
        rprint(f"  [dim]Journal:[/dim] {metadata['journal']}")
    if metadata.get("abstract"):
        abstract = metadata["abstract"]
        preview = abstract[:80] + "..." if len(abstract) > 80 else abstract
        rprint(f"  [dim]Abstract:[/dim] {preview}")

    # Delete/trash original
    if delete:
        _remove_original(pdf, to_trash=False)
    elif move_to_trash:
        _remove_original(pdf, to_trash=True)


@app.command("scan")
def scan_dir(
    directory: str = typer.Argument(..., help="Directory to scan for PDFs"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Include subdirectories"),
    keep: bool = typer.Option(False, "--keep", "-k", help="Keep PDFs (don't move to trash)"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without changes"),
):
    """Scan a directory and add all PDFs to Zotero, then trash the originals.

    For each PDF the DOI is extracted and metadata fetched from CrossRef/PubMed.
    Papers already in your library (matched by DOI or title) are skipped. Added
    and duplicate PDFs are moved to the trash unless --keep is given; PDFs that
    could not be processed are always left in place.

    Example:
        zot scan ~/Downloads/papers
    """
    from pathlib import Path

    dir_path = Path(directory).expanduser().resolve()
    if not dir_path.is_dir():
        rprint(f"[red]Not a directory: {dir_path}[/red]")
        raise typer.Exit(1)

    glob_pat = "**/*" if recursive else "*"
    pdfs = sorted(
        p for p in dir_path.glob(glob_pat) if p.is_file() and p.suffix.lower() == ".pdf"
    )

    if not pdfs:
        rprint(f"[yellow]No PDFs found in {dir_path}[/yellow]")
        return

    rprint(f"[bold]Scanning {len(pdfs)} PDF(s) in {dir_path}[/bold]")
    if dry_run:
        rprint("[yellow]DRY RUN - no changes will be made[/yellow]")
    rprint()

    db = get_db()
    counts = {"added": 0, "duplicate": 0, "no_doi": 0, "no_metadata": 0}

    for pdf in pdfs:
        if dry_run:
            doi = _extract_doi_from_pdf(pdf)
            if not doi:
                counts["no_doi"] += 1
                rprint(f"  [red]?[/red] {pdf.name} [dim]— no DOI[/dim]")
            elif db.find_existing_item(doi=doi):
                counts["duplicate"] += 1
                rprint(f"  [yellow]=[/yellow] {pdf.name} [dim]— already in library[/dim]")
            else:
                counts["added"] += 1
                rprint(f"  [green]+[/green] {pdf.name} [dim]— would add ({doi})[/dim]")
            continue

        result = _process_pdf(db, pdf)
        status = result["status"]
        counts[status] += 1

        if status == "added":
            title = (result["metadata"].get("title") or "")[:50]
            rprint(f"  [green]+[/green] {pdf.name} [dim]— {title}[/dim]")
        elif status == "duplicate":
            rprint(f"  [yellow]=[/yellow] {pdf.name} [dim]— in library (ID {result['item_id']})[/dim]")
        elif status == "no_doi":
            rprint(f"  [red]?[/red] {pdf.name} [dim]— no DOI, skipped[/dim]")
        else:  # no_metadata
            rprint(f"  [red]✗[/red] {pdf.name} [dim]— metadata lookup failed, skipped[/dim]")

        # Trash originals that are now in the library
        if not keep and status in ("added", "duplicate"):
            _remove_original(pdf, to_trash=True, quiet=True)

    rprint()
    rprint(
        f"[bold]Summary:[/bold] "
        f"[green]{counts['added']} added[/green], "
        f"[yellow]{counts['duplicate']} duplicate[/yellow], "
        f"[dim]{counts['no_doi']} no-DOI, {counts['no_metadata']} failed[/dim]"
    )
    if dry_run:
        rprint("[dim]Run without --dry-run to apply.[/dim]")
    elif not keep and (counts["added"] or counts["duplicate"]):
        moved = counts["added"] + counts["duplicate"]
        left = counts["no_doi"] + counts["no_metadata"]
        rprint(f"[dim]Moved {moved} PDF(s) to trash. {left} left in place.[/dim]")


@app.command("i")
def interactive(
    query: str = typer.Argument("", help="Initial search query"),
):
    """Launch interactive fzf browser.

    Search syntax (type in fzf):
      - a:weeks - author contains "weeks"
      - a:week* - author starts with "week"
      - y:2024 - exact year
      - y:2020-2024 - year range
      - y:2020+ - 2020 and later
      - t:method/* - tags under method/
      - j:nat* - journal starts with "nat"
      - plain text - search title/abstract

    Combine: a:weeks y:2020+ thermodynamics

    Keybindings:
      - Enter: Open in Zotero & copy PDF path
      - Ctrl-O: Open PDF
      - Ctrl-T: Add tag
      - Ctrl-Y: Copy DOI
    """
    from zotero_cli.interactive import run_interactive, run_tag_selector
    from zotero_cli.obsidian import get_zotero_uri

    db = get_db()

    try:
        results = run_interactive(db, initial_query=query)
    except RuntimeError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not results:
        return

    for action, item_id in results:
        if action == "select":
            # Open in Zotero and copy PDF path to clipboard
            item = db.get_item(item_id=item_id)
            if item:
                # Copy PDF path to clipboard
                if item.pdf_path:
                    subprocess.run(["pbcopy"], input=str(item.pdf_path).encode(), check=True)
                    rprint(f"[green]Copied path:[/green] {item.pdf_path}")
                else:
                    rprint(f"[yellow]No PDF for this item[/yellow]")

                # Open in Zotero
                zotero_uri = get_zotero_uri(item, "select")
                rprint(f"[green]Opening in Zotero:[/green] {item.short_title()}")
                subprocess.run(["open", zotero_uri])
        elif action == "open":
            # Open PDF
            item = db.get_item(item_id=item_id)
            if item and item.pdf_path:
                rprint(f"Opening: [green]{item.pdf_path}[/green]")
                subprocess.run(["open", str(item.pdf_path)])
            else:
                rprint(f"[yellow]No PDF for item {item_id}[/yellow]")
        elif action == "tag":
            # Add tag
            selected_tag = run_tag_selector(db, item_id)
            if selected_tag:
                if db.add_tag(item_id, selected_tag):
                    item = db.get_item(item_id=item_id)
                    rprint(f"[green]Added '{selected_tag}' to:[/green] {item.short_title() if item else item_id}")
                else:
                    rprint(f"[yellow]Already has tag '{selected_tag}'[/yellow]")
        elif action == "copy":
            # Copy DOI
            item = db.get_item(item_id=item_id)
            if item and item.doi:
                subprocess.run(["pbcopy"], input=item.doi.encode(), check=True)
                rprint(f"[green]Copied DOI:[/green] {item.doi}")
            else:
                rprint(f"[yellow]No DOI for item {item_id}[/yellow]")


@app.callback()
def main(ctx: typer.Context):
    """Zotero CLI - manage your library from the command line.

    Run without arguments to launch interactive mode.
    """
    if ctx.invoked_subcommand is None:
        # Launch interactive mode by default
        interactive("")


if __name__ == "__main__":
    app()
