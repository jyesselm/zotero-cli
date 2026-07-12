"""Command-line interface for Zotero."""

import json
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


def _ensure_zotero_closed() -> None:
    """Refuse to write while Zotero is open (avoids a locked/corrupt DB)."""
    if subprocess.run(["pgrep", "-fi", "zotero"], capture_output=True).returncode == 0:
        rprint("[red]Zotero is running — quit it fully (⌘Q) first, then retry.[/red]")
        raise typer.Exit(1)


@app.command("new-collection")
def new_collection(
    name: str = typer.Argument(..., help="Collection name"),
    parent: str = typer.Option(None, "--parent", "-p", help="Parent collection name"),
):
    """Create a new collection (optionally under a parent). Zotero must be closed."""
    _ensure_zotero_closed()
    db = get_db()
    parent_id = None
    if parent:
        parent_id = db.find_collection(parent)
        if parent_id is None:
            rprint(f"[red]Parent collection '{parent}' not found.[/red]")
            raise typer.Exit(1)
    cid = db.create_collection(name, parent_id)
    where = f" under '{parent}'" if parent else " at the root"
    rprint(f"[green]Created collection '{name}'[/green] (id {cid}){where}")
    rprint("[dim]Reopen Zotero to sync it.[/dim]")


@app.command("new-project")
def new_project(
    name: str = typer.Argument(..., help="Project name (e.g. 2025-atp-ttr-switch)"),
):
    """Create a project collection under Projects/ plus a colored cited/<name> tag.

    Zotero must be closed.
    """
    _ensure_zotero_closed()
    db = get_db()
    parent_id = db.find_collection("Projects")
    if parent_id is None:
        rprint("[yellow]No 'Projects' collection found — creating at the root.[/yellow]")
    cid = db.create_collection(name, parent_id)
    tag = f"cited/{name}"
    db.create_colored_tag(tag)
    rprint(f"[green]Created project '{name}'[/green] (id {cid}) + colored tag [cyan]{tag}[/cyan]")
    rprint("[dim]Reopen Zotero to sync. Tag the papers you cite with[/dim] "
           f"[cyan]{tag}[/cyan][dim].[/dim]")


@app.command("tags-export")
def tags_export(
    out: str = typer.Option(
        "~/.config/zotero-cli/tags.json", "--out", "-o", help="Output JSON path"
    ),
):
    """Export all item tags to a portable JSON (keyed by Zotero item key).

    Store the file somewhere synced (Dropbox, a git repo, ...) and run
    'zot tags-import' on another computer to replicate the tags.
    """
    import json
    from pathlib import Path

    db = get_db()
    mapping = db.export_tags()
    p = Path(out).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "item_count": len(mapping), "tags": mapping}
    p.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    total = sum(len(v) for v in mapping.values())
    rprint(f"[green]Exported {total} tags across {len(mapping)} items[/green] → {p}")


@app.command("tags-import")
def tags_import(
    path: str = typer.Argument(..., help="Tag-map JSON produced by tags-export"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without applying"),
):
    """Apply a tag-map JSON to this computer's library (matched by item key).

    Additive: adds missing tags, never removes. Run after the items
    themselves have synced to this machine.
    """
    import json
    from pathlib import Path

    db = get_db()
    data = json.loads(Path(path).expanduser().read_text())
    mapping = data.get("tags", data)
    applied, matched, missing = db.import_tags(mapping, dry_run=dry_run)
    word = "Would apply" if dry_run else "Applied"
    rprint(f"[green]{word} {applied} new tags[/green] to {matched} items")
    if missing:
        rprint(f"[yellow]{missing} items in the file aren't in this library yet[/yellow] "
               "[dim](let Zotero sync first, then re-run)[/dim]")
    if dry_run:
        rprint("[dim]Run without --dry-run to apply.[/dim]")


@app.command()
def deltag(
    tag_name: str = typer.Argument(..., help="Tag to delete globally"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a tag entirely, removing it from all items."""
    db = get_db()

    all_tags = db.get_all_tags()
    match = next((t for t in all_tags if t.name == tag_name), None)
    if not match:
        rprint(f"[yellow]Tag '{tag_name}' not found.[/yellow]")
        raise typer.Exit(1)

    if not yes:
        rprint(f"Delete tag [cyan]{tag_name}[/cyan] from [bold]{match.count}[/bold] items?")
        if not typer.confirm("Proceed?"):
            rprint("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    count = db.delete_tag(tag_name)
    rprint(f"[green]Deleted '{tag_name}' from {count} items[/green]")


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


@app.command()
def mirror(
    dest: str = typer.Option("~/local/papers", "--dest", "-d", help="Destination directory"),
    copy: bool = typer.Option(False, "--copy", help="Copy files instead of symlinking"),
    clean: bool = typer.Option(False, "--clean", help="Remove the destination tree first"),
):
    """Build a browsable Author/Year tree of your library PDFs.

    Creates symlinks (or copies, with --copy) under DEST, organized as
    Author/Year/Citekey-Title.pdf and pointing at Zotero's storage. Zotero's
    own storage is left untouched. Safe to rerun; use --clean to rebuild from
    scratch (e.g. after deleting papers).
    """
    import re as _re
    import shutil as _shutil
    from pathlib import Path

    from zotero_cli.database import build_filename

    dest_root = Path(dest).expanduser()
    db = get_db()
    items = [it for it in db.search(limit=100000) if it.pdf_path]

    if not items:
        rprint("[yellow]No items with PDFs found.[/yellow]")
        return

    if clean and dest_root.exists():
        _shutil.rmtree(dest_root)

    made = 0
    used: set[str] = set()
    for it in items:
        author = _re.sub(r'[/\\:*?"<>|]', "", it.first_author or "Unknown").strip() or "Unknown"
        year = it.year or "no-year"
        folder = dest_root / author / year
        folder.mkdir(parents=True, exist_ok=True)

        fname = build_filename(it.citation_key or author, it.title, it.pdf_path.suffix or ".pdf")
        link = folder / fname
        if str(link) in used:  # disambiguate two papers that map to the same name
            link = folder / f"{link.stem}-{it.item_id}{link.suffix}"
        used.add(str(link))

        if link.is_symlink() or link.exists():
            link.unlink()
        if copy:
            _shutil.copy2(it.pdf_path, link)
        else:
            link.symlink_to(it.pdf_path)
        made += 1

    kind = "copies" if copy else "symlinks"
    rprint(f"[green]Mirrored {made} PDFs[/green] as {kind} under [bold]{dest_root}[/bold]")
    rprint(f"[dim]Browse: open {dest_root}   |   rebuild: zot mirror --clean[/dim]")


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
def litnote(
    item_id: int = typer.Argument(..., help="Item ID to build a literature note for"),
    science_dir: str = typer.Option(
        "~/notes/300-reference/science",
        "--dir",
        "-d",
        help="Literature-note folder in the Obsidian vault",
    ),
    summary: str = typer.Option(
        None,
        "--summary",
        "-s",
        help="Path to the agent-written executive summary (else <dir>/<slug>.summary.md, "
        "else a placeholder). When present, the dashboard note is assembled too.",
    ),
):
    """Build an Obsidian literature note from a Zotero PDF (deterministic + assembly).

    Extracts real figure images, a paper-like cleaned reading note, and a
    'Cited in your notes' cross-link section, then writes:

      <dir>/<slug>.fulltext.md              paper-like reading note (inline figures)
      <dir>/attachments/<slug>/figN.png     clipped figures
      <dir>/<slug>.litnote.json             bundle for the summarizing agent
      <dir>/<slug>.md                        dashboard note (frontmatter + summary + figures)

    The executive summary is agent-written: pass it with --summary (or drop it at
    <dir>/<slug>.summary.md) and the dashboard note is assembled. On regeneration,
    human sections (## Notes onward) and status/updated are preserved. Read-only
    against Zotero. See LITNOTES.md.
    """
    from zotero_cli import litnote as ln

    db = get_db()
    item = db.get_item(item_id=item_id)
    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)
    if not item.pdf_path or not item.pdf_path.exists():
        rprint("[red]No PDF found for this item.[/red]")
        raise typer.Exit(1)

    sdir = Path(science_dir).expanduser()
    sdir.mkdir(parents=True, exist_ok=True)
    pdf = str(item.pdf_path)

    # Reuse the existing note's slug if this paper is already noted (re-match by key),
    # so regeneration updates in place instead of orphaning the original note.
    key2slug = ln.vault_key2slug(sdir)
    slug = key2slug.get(item.key) or ln.make_slug(item)
    reused = item.key in key2slug

    tag = "[yellow](regenerating existing)[/yellow]" if reused else ""
    rprint(f"[bold]{item.short_title()}[/bold]  →  [cyan]{slug}[/cyan] {tag}")

    # 1. figures + references + cleaned text
    bundle = ln.extract(pdf, sdir, slug)
    rprint(
        f"  figures: {bundle['n_fig_img']}/{bundle['n_fig_total']} clipped · "
        f"references: {bundle['references_n']} · {bundle['chars']:,} chars"
    )

    # 2. paper-like reading note
    fig_by_label = {f["label"]: f for f in bundle["figures"]}
    body = ln.build_reading_note(pdf, slug, fig_by_label, title=item.title)

    # 3. citation cross-links (only to papers that already have notes)
    lib = db.search(limit=100000)
    section, num2slug = ln.cited_notes(bundle["references"], item.key, lib, key2slug)
    body, n_inline = ln.link_inline(body, num2slug)
    cited_md = ln.cited_section_md(section, slug)

    # 4. write the deterministic artifacts.
    # build_reading_note already owns the `# title` H1 (it needs the title for
    # front-matter dedup); inject the provenance subtitle right after it.
    subtitle = (
        f"*Machine-extracted reading note · [[{slug}|dashboard]] · "
        f"[open in Zotero](zotero://select/library/items/{item.key})*"
    )
    head, _, rest = body.partition("\n")
    ft = sdir / f"{slug}.fulltext.md"
    ft.write_text(f"{head}\n\n{subtitle}\n{rest.lstrip(chr(10))}\n")
    # persist references so `zot relink` can recompute cross-links without re-extracting
    (sdir / f"{slug}.references.txt").write_text(bundle["references"])
    (sdir / f"{slug}.litnote.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "zotero_key": item.key,
                "title": item.title,
                "authors": item.authors,
                "year": item.year,
                "journal": item.journal,
                "doi": item.doi,
                "url": item.url,
                "citekey": item.citation_key,
                "paper_tags": [t for t in item.tags if "/" in t],
                "figures": [
                    {"label": f["label"], "caption": f["caption"], "has_image": bool(f["image"])}
                    for f in bundle["figures"]
                ],
                "cited_section_md": cited_md,
                "n_inline_links": n_inline,
            },
            indent=1,
            ensure_ascii=False,
        )
    )

    rprint(f"  [green]wrote[/green] {ft.name}  ·  {slug}.litnote.json")
    if section:
        rprint(f"  cited-in-notes: {len(section)} paper(s), {n_inline} inline link(s)")

    # 5. dashboard note — assembled if a summary is available
    summ_path = Path(summary).expanduser() if summary else (sdir / f"{slug}.summary.md")
    summ_text = summ_path.read_text().strip() if summ_path.exists() else None
    dash = sdir / f"{slug}.md"
    rendered = ln.render_dashboard(
        slug=slug, key=item.key, title=item.title, authors=item.authors,
        year=item.year, journal=item.journal, doi=item.doi, url=item.url,
        paper_tags=[t for t in item.tags if "/" in t], figures=bundle["figures"],
        summary=summ_text or "*Summary pending — run with `--summary` once written.*",
        cited_md=cited_md,
    )
    if dash.exists():
        rendered = ln.merge_preserving_human(dash.read_text(), rendered)
    dash.write_text(rendered)
    if summ_text:
        rprint(f"  [green]assembled dashboard[/green] {dash.name}  (summary: {summ_path.name})")
    else:
        rprint(f"  [yellow]dashboard written with placeholder summary[/yellow] {dash.name}")

    # 6. facets (methods/systems) — re-rendered from the sidecar every build so they
    # survive rebuild (the sidecar is the single source of truth).
    fac_path = sdir / f"{slug}.facets.json"
    if fac_path.exists():
        from zotero_cli import facets as facmod

        resolved = facmod.process(json.loads(fac_path.read_text()), ft.read_text())
        dash.write_text(facmod.apply_facets(dash.read_text(), resolved))
        extra = f", {len(resolved['unresolved'])} unresolved" if resolved["unresolved"] else ""
        rprint(f"  [green]facets[/green]: {len(resolved['methods_used'])} method(s), "
               f"{len(resolved['systems_used'])} system(s){extra}")

    rprint("\n[dim]Run `zot moc-sync` after a batch so MOC links resolve.[/dim]")


@app.command()
def relink(
    science_dir: str = typer.Option(
        "~/notes/300-reference/science",
        "--dir",
        "-d",
        help="Literature-note folder in the Obsidian vault",
    ),
):
    """Recompute every note's cross-links against the WHOLE current vault.

    As you add notes, older notes' 'Cited in your notes' sections go stale (they were
    computed when fewer notes existed). This re-derives each note's cited-in-notes
    section and its MOC links from the current set and rewrites just those managed
    regions (human sections untouched). Reference lists are cached to
    `<slug>.references.txt`; the first run extracts them from the PDFs (read-only).
    Run `zot moc-sync` afterwards to refresh the MOC files themselves.
    """
    from zotero_cli import litnote as ln

    sdir = Path(science_dir).expanduser()
    key2slug = ln.vault_key2slug(sdir)
    slug2key = {v: k for k, v in key2slug.items()}
    db = get_db()
    lib = db.search(limit=100000)

    changed = 0
    total_links = 0
    extracted = 0
    for note in sorted(sdir.glob("*.md")):
        if note.name.endswith(".fulltext.md") or note.stem.startswith("MOC - "):
            continue
        slug = note.stem
        key = slug2key.get(slug)
        if not key:
            continue
        item = db.get_item(key=key)
        if not item:
            continue

        # references: cached sidecar, else extract from the PDF and cache
        refpath = sdir / f"{slug}.references.txt"
        if refpath.exists():
            refs = refpath.read_text()
        elif item.pdf_path and item.pdf_path.exists():
            refs, _ = ln.extract_references(str(item.pdf_path))
            refpath.write_text(refs)
            extracted += 1
        else:
            refs = ""

        section, _num = ln.cited_notes(refs, key, lib, key2slug)
        cited_md = ln.cited_section_md(section, slug)
        paper_tags = [t for t in item.tags if "/" in t]

        text = note.read_text()
        new = ln.set_region(text, "moc", ln.moc_region_md(paper_tags),
                            after="## Links", before="## Summary")
        new = ln.set_cited_region(new, cited_md)
        # facets: re-render from the sidecar so body region + frontmatter stay in
        # sync corpus-wide (same source of truth as `zot litnote`).
        fac_path = sdir / f"{slug}.facets.json"
        ftpath = sdir / f"{slug}.fulltext.md"
        if fac_path.exists() and ftpath.exists():
            from zotero_cli import facets as facmod

            resolved = facmod.process(json.loads(fac_path.read_text()), ftpath.read_text())
            new = facmod.apply_facets(new, resolved)
        if new != text:
            note.write_text(new)
            changed += 1
        total_links += len(section)

    rprint(
        f"[green]relink:[/green] {changed} note(s) updated · {total_links} cross-links "
        f"across the vault · {extracted} reference list(s) newly extracted"
    )
    rprint("[dim]Run `zot moc-sync` to refresh the MOC files.[/dim]")


@app.command()
def facets(
    item_id: int = typer.Argument(..., help="Item ID whose note to (re)apply facets to"),
    json_path: str = typer.Option(None, "--json", "-j", help="Facets sidecar (else <dir>/<slug>.facets.json)"),
    science_dir: str = typer.Option("~/notes/300-reference/science", "--dir", "-d"),
    verify_only: bool = typer.Option(False, "--verify-only", help="Report grounding, write nothing"),
):
    """Apply agent-extracted Methods/Systems facets to a literature note.

    Reads a `<slug>.facets.json` sidecar (produced by the facet-extractor agent),
    VERIFIES each specific is grounded in `<slug>.fulltext.md`, NORMALIZES it to a
    canonical facet slug (closed FACET_VOCAB; unmatched → holding pen), then renders
    the `zot:auto:facets` body region + `methods_used`/`systems_used` frontmatter.
    Idempotent; only machine regions/keys touched.
    """
    from zotero_cli import facets as facmod
    from zotero_cli import litnote as ln

    db = get_db()
    item = db.get_item(item_id=item_id)
    if not item:
        rprint(f"[red]Item {item_id} not found.[/red]")
        raise typer.Exit(1)
    sdir = Path(science_dir).expanduser()
    slug = ln.vault_key2slug(sdir).get(item.key)
    if not slug:
        rprint("[red]No literature note for this item yet (run `zot litnote` first).[/red]")
        raise typer.Exit(1)

    fac = Path(json_path).expanduser() if json_path else (sdir / f"{slug}.facets.json")
    ftpath = sdir / f"{slug}.fulltext.md"
    if not fac.exists():
        rprint(f"[red]No facets sidecar: {fac}[/red]")
        raise typer.Exit(1)
    resolved = facmod.process(json.loads(fac.read_text()), ftpath.read_text())
    rprint(f"[bold]{slug}[/bold]")
    rprint(f"  methods: {resolved['methods_used']}")
    rprint(f"  systems: {resolved['systems_used']}")
    if resolved["unresolved"]:
        rprint(f"  [yellow]unresolved (holding pen):[/yellow] {[u['specific'] for u in resolved['unresolved']]}")
    if resolved["dropped"]:
        rprint(f"  [red]dropped (ungrounded):[/red] {[d['specific'] for d in resolved['dropped']]}")
    if verify_only:
        return
    note = sdir / f"{slug}.md"
    note.write_text(facmod.apply_facets(note.read_text(), resolved))
    rprint(f"  [green]applied to[/green] {note.name}")


@app.command("facets-review")
def facets_review(
    science_dir: str = typer.Option("~/notes/300-reference/science", "--dir", "-d"),
):
    """Corpus-wide holding pen: specifics that matched no facet, with counts.

    Recurring entries are candidates to promote into FACET_VOCAB/FACET_ALIASES
    (src/zotero_cli/facets.py) — agents propose, humans promote (keeps grouping clean).
    """
    from collections import Counter

    from zotero_cli import facets as facmod

    sdir = Path(science_dir).expanduser()
    counts: Counter = Counter()
    for fac in sdir.glob("*.facets.json"):
        slug = fac.name[: -len(".facets.json")]
        ftpath = sdir / f"{slug}.fulltext.md"
        if not ftpath.exists():
            continue
        resolved = facmod.process(json.loads(fac.read_text()), ftpath.read_text())
        for u in resolved["unresolved"]:
            counts[(u["kind"], u["specific"])] += 1
    if not counts:
        rprint("[green]Holding pen empty — every grounded specific resolved to a facet.[/green]")
        return
    rprint(f"[bold]Unresolved facets ({len(counts)} distinct):[/bold]")
    for (kind, spec), n in counts.most_common():
        rprint(f"  {n:>2}× [{kind[:-1]}] {spec}")


@app.command()
def discover(
    science_dir: str = typer.Option("~/notes/300-reference/science", "--dir", "-d"),
    since: int = typer.Option(2021, "--since", help="Only recommend papers published this year or later"),
    top: int = typer.Option(40, "--top", "-n", help="Max rows per section"),
    gaps: bool = typer.Option(False, "--gaps", help="Also list classic co-citation gaps you don't own"),
    offline: bool = typer.Option(False, "--offline", help="Skip OpenAlex (only the --gaps signal)"),
    out: str = typer.Option(
        "~/notes/300-reference/science/READING-LIST.md", "--out", "-o",
        help="Where to write the reading list note",
    ),
):
    """Reading list of RECENT papers you likely don't know and don't own — review only.

    Three engines (all recent, all deduped vs your library, nothing added to Zotero):
      B  papers that CITE your key papers (forward citations)
      D  what the new work in your field is built on (works those citing papers co-cite)
      C  recent papers matching your top method×system facets
    `--gaps` adds the older 'co-citation classics you're missing' section.
    """
    from zotero_cli import discover as disc

    sdir = Path(science_dir).expanduser()
    db = get_db()
    lib = db.search(limit=100000)
    hits: dict[str, dict] = {}  # doi -> merged candidate w/ engines + why

    def add(doi, title, year, venue, engine, why):
        if not doi:
            doi = "~" + title[:60].lower()  # keep title-only rows distinct
        h = hits.setdefault(doi, {"doi": doi if not doi.startswith("~") else "",
                                  "title": title, "year": year, "venue": venue,
                                  "engines": set(), "why": []})
        h["engines"].add(engine)
        h["why"].append(why)
        if year and not h["year"]:
            h["year"] = year

    b_list = canon = fs = []
    if not offline:
        key = [it for it in lib if "status/key-paper" in it.tags or "type/my-paper" in it.tags]
        rprint(f"[bold]B+D:[/bold] OpenAlex forward-citations of {len(key)} key papers (since {since})…")
        b_list, canon = disc.forward_and_canon(lib, key, since_year=since)
        rprint(f"   B: {len(b_list)} citing papers · D: {len(canon)} co-cited works")
        for r in b_list:
            add(r["doi"], r["title"], r["year"], r["venue"], "B", f"cites {len(r['via'])} of your papers")
        for r in canon:
            add(r["doi"], r["title"], r["year"], r["venue"], "D", f"co-cited by {r['freq']} new papers citing you")
        combos = disc.top_facet_combos(sdir, n=6)
        rprint(f"[bold]C:[/bold] facet search on {len(combos)} combos…")
        fs = disc.facet_search(lib, combos, per_combo=15, min_year=since)
        rprint(f"   C: {len(fs)} candidates")
        for r in fs:
            add(r["doi"], r["title"], r["year"], r["venue"], "C", "matches your method×system")

    def row(h):
        title = h["title"].replace("|", "\\|")[:150]
        link = f"[{title}](https://doi.org/{h['doi']})" if h["doi"] else title
        return f"| [ ] | {h['year'] or ''} | {link} | {h['venue'][:30]} | {'·'.join(sorted(h['engines']))}: {'; '.join(dict.fromkeys(h['why']))} |"

    lines = ["---", "type: reading-list", "tags: [reading-list]", "---",
             "# Reading list — recent papers to consider", "",
             f"*`zot discover` · recent (≥{since}), not in your Zotero, likely new to you. "
             "**Review only — nothing was added.** Tick a box, then add what you want. "
             "Engines: B=cites your work · D=what new work in your field builds on · C=your topics.*", ""]

    # Top picks — anything surfaced by >1 engine
    multi = sorted([h for h in hits.values() if len(h["engines"]) > 1],
                   key=lambda h: (-len(h["engines"]), -(h["year"] or 0)))
    if multi:
        lines += ["## ★ Top picks (flagged by more than one engine)", "",
                  "| ✓ | year | paper | venue | why |", "|---|---|---|---|---|"]
        lines += [row(h) for h in multi[:top]]
        lines.append("")

    for eng, title in (("B", "B — recent papers that cite your work"),
                       ("D", "D — what the new work in your field is built on"),
                       ("C", "C — recent papers matching your topics")):
        rows = sorted([h for h in hits.values() if eng in h["engines"]],
                      key=lambda h: -(h["year"] or 0))
        if rows:
            lines += [f"## {title}", "", "| ✓ | year | paper | venue | why |", "|---|---|---|---|---|"]
            lines += [row(h) for h in rows[:top]]
            lines.append("")

    if gaps or offline:
        g = disc.cocitation_gaps(sdir, lib, min_notes=3)
        rprint(f"[bold]gaps:[/bold] {len(g)} classic works cited by ≥3 of your notes, not owned.")
        lines += ["## Gaps — classics your library is missing (older; you may already know these)", "",
                  "| ✓ | cited by | paper | your notes |", "|---|---|---|---|"]
        for gg in g[:top]:
            ref = gg["ref"].replace("|", "\\|")
            ref = ref[:157] + "…" if len(ref) > 160 else ref
            cited = ", ".join(f"[[{s}]]" for s in gg["notes"][:3]) + (f" +{len(gg['notes'])-3}" if len(gg["notes"]) > 3 else "")
            lines.append(f"| [ ] | **{gg['count']}×** | {ref} | {cited} |")
        lines.append("")

    outp = Path(out).expanduser()
    outp.write_text("\n".join(lines) + "\n")
    rprint(f"\n[green]wrote[/green] {outp}  ({len(hits)} distinct recent papers"
           f"{', ' + str(len(multi)) + ' top picks' if multi else ''}) — review in Obsidian.")


@app.command("moc-sync")
def moc_sync(
    science_dir: str = typer.Option(
        "~/notes/300-reference/science",
        "--dir",
        "-d",
        help="Literature-note folder in the Obsidian vault",
    ),
):
    """(Re)generate tag MOCs (Maps of Content) from the literature notes.

    Builds `MOCs/MOC - <tag>.md` for every method/system/topic/type paper-tag in the
    corpus (topic/thermodynamics/* rolls up) plus a floor `MOC - key-papers`. Each MOC
    is a Dataview query + a marker-fenced static wikilink list; human text below the
    fence is preserved. Read-only against Zotero.
    """
    from zotero_cli import litnote as ln

    sdir = Path(science_dir).expanduser()
    if not sdir.exists():
        rprint(f"[red]Not found: {sdir}[/red]")
        raise typer.Exit(1)
    written = ln.build_mocs(sdir)
    rprint(f"[green]Wrote {len(written)} MOC(s):[/green]")
    for m in written:
        rprint(f"  [[{m}]]")


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
