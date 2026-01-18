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


@app.command("i")
def interactive(
    query: str = typer.Argument("", help="Initial search query"),
):
    """Launch interactive fzf browser.

    Search syntax:
      - Free text searches all fields
      - year:2024 - filter by year
      - author:Weeks - filter by author
      - tag:method/dms - filter by tag
      - journal:Nature - filter by journal

    Keybindings:
      - Enter: Open in Zotero & copy PDF path
      - Ctrl-O: Open PDF
      - Ctrl-T: Add tag
      - Ctrl-Y: Copy DOI
      - Tab: Select multiple
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
