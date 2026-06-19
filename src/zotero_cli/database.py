"""Database access layer for Zotero SQLite database."""

import random
import re
import shutil
import sqlite3
import string
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from zotero_cli.models import Collection, Tag, ZoteroItem

DEFAULT_ZOTERO_PATH = Path.home() / "Zotero"
DEFAULT_DB_PATH = DEFAULT_ZOTERO_PATH / "zotero.sqlite"
DEFAULT_STORAGE_PATH = DEFAULT_ZOTERO_PATH / "storage"


def _generate_key() -> str:
    """Generate a random 8-char Zotero item key."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def build_filename(citekey: str, title: str, suffix: str = ".pdf") -> str:
    """Build a terminal-safe, dash-separated filename: 'Weeks2024-Title-words.pdf'.

    Strips filesystem-illegal characters, replaces whitespace with dashes,
    collapses repeats, and truncates. Used for both stored attachments and
    the browsable mirror so they stay consistent.
    """
    citekey = (citekey or "").strip()
    title = (title or "").strip()
    raw = f"{citekey} {title}".strip() if citekey else (title or "untitled")
    raw = re.sub(r'[/\\:*?"<>|]', "", raw)  # strip filesystem-illegal chars
    raw = re.sub(r"\s+", "-", raw)          # spaces -> dashes (terminal-friendly)
    raw = re.sub(r"-+", "-", raw).strip("-")[:120].rstrip("-. ")
    return f"{raw or 'untitled'}{suffix}"


def _storage_filename(metadata: dict, original: Path) -> str:
    """Build a Finder-searchable storage filename from CrossRef metadata.

    Uses first-author surname + year as a citekey prefix, then the title.
    Falls back to the original filename if metadata is too sparse.
    """
    authors = metadata.get("authors") or []
    last = authors[0].get("last", "").strip() if authors else ""
    year = (metadata.get("year") or "").strip()
    title = (metadata.get("title") or "").strip()
    citekey = f"{last}{year}"
    if not citekey and not title:
        return original.name
    return build_filename(citekey, title, original.suffix or ".pdf")


class ZoteroDatabase:
    """Interface to Zotero SQLite database."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        storage_path: Path = DEFAULT_STORAGE_PATH,
    ):
        self.db_path = db_path
        self.storage_path = storage_path
        self._temp_db: Path | None = None

    @contextmanager
    def connection(self):
        """Get a database connection (copies DB to avoid locks)."""
        # Copy database to temp file to avoid locking issues
        self._temp_db = Path(tempfile.mktemp(suffix=".sqlite"))
        shutil.copy2(self.db_path, self._temp_db)

        conn = sqlite3.connect(self._temp_db)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
            if self._temp_db and self._temp_db.exists():
                self._temp_db.unlink()

    @contextmanager
    def write_connection(self):
        """Get a direct database connection for writes (use with caution)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def search(
        self,
        query: str | None = None,
        author: str | None = None,
        tag: str | None = None,
        collection: str | None = None,
        year: str | None = None,
        item_type: str | None = None,
        limit: int = 50,
    ) -> list[ZoteroItem]:
        """Search for items matching criteria."""
        with self.connection() as conn:
            # Base query
            sql = """
                SELECT DISTINCT i.itemID, i.key, it.typeName,
                    MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                    MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date,
                    MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract,
                    MAX(CASE WHEN f.fieldName='publicationTitle' THEN idv.value END) as journal,
                    MAX(CASE WHEN f.fieldName='DOI' THEN idv.value END) as doi,
                    MAX(CASE WHEN f.fieldName='url' THEN idv.value END) as url
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

            # Add filters
            if tag:
                sql += """
                    AND i.itemID IN (
                        SELECT itemID FROM itemTags it2
                        JOIN tags t ON it2.tagID = t.tagID
                        WHERE t.name = ? OR t.name LIKE ?
                    )
                """
                params.extend([tag, f"{tag}/%"])

            if collection:
                sql += """
                    AND i.itemID IN (
                        SELECT itemID FROM collectionItems ci
                        JOIN collections c ON ci.collectionID = c.collectionID
                        WHERE c.collectionName LIKE ?
                    )
                """
                params.append(f"%{collection}%")

            if item_type:
                sql += " AND it.typeName = ?"
                params.append(item_type)

            sql += " GROUP BY i.itemID"

            # Text search filter (after grouping)
            if query or author or year:
                sql = f"SELECT * FROM ({sql}) AS subq WHERE 1=1"

                if query:
                    sql += " AND (title LIKE ? OR abstract LIKE ?)"
                    params.extend([f"%{query}%", f"%{query}%"])

                if year:
                    sql += " AND date LIKE ?"
                    params.append(f"{year}%")

            sql += " ORDER BY date DESC"
            sql += f" LIMIT {limit}"

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            items = []
            for row in rows:
                item = ZoteroItem(
                    item_id=row["itemID"],
                    key=row["key"],
                    item_type=row["typeName"],
                    title=row["title"] or "",
                    date=row["date"] or "",
                    abstract=row["abstract"] or "",
                    journal=row["journal"] or "",
                    doi=row["doi"] or "",
                    url=row["url"] or "",
                )
                # Get additional data
                item.authors = self._get_authors(conn, item.item_id)
                item.tags = self._get_item_tags(conn, item.item_id)
                item.collections = self._get_item_collections(conn, item.item_id)
                item.pdf_path = self._get_pdf_path(conn, item.item_id)

                # Author filter
                if author:
                    if not any(author.lower() in a.lower() for a in item.authors):
                        continue

                items.append(item)

            return items

    def get_item(self, item_id: int | None = None, key: str | None = None) -> ZoteroItem | None:
        """Get a single item by ID or key."""
        with self.connection() as conn:
            if key:
                cursor = conn.execute("SELECT itemID FROM items WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    item_id = row["itemID"]
                else:
                    return None

            if not item_id:
                return None

            items = self.search(limit=1)
            # Re-search with specific ID
            cursor = conn.execute(
                """
                SELECT i.itemID, i.key, it.typeName,
                    MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                    MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date,
                    MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract,
                    MAX(CASE WHEN f.fieldName='publicationTitle' THEN idv.value END) as journal,
                    MAX(CASE WHEN f.fieldName='DOI' THEN idv.value END) as doi,
                    MAX(CASE WHEN f.fieldName='url' THEN idv.value END) as url
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                LEFT JOIN itemData id ON i.itemID = id.itemID
                LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
                LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
                WHERE i.itemID = ?
                GROUP BY i.itemID
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            item = ZoteroItem(
                item_id=row["itemID"],
                key=row["key"],
                item_type=row["typeName"],
                title=row["title"] or "",
                date=row["date"] or "",
                abstract=row["abstract"] or "",
                journal=row["journal"] or "",
                doi=row["doi"] or "",
                url=row["url"] or "",
            )
            item.authors = self._get_authors(conn, item.item_id)
            item.tags = self._get_item_tags(conn, item.item_id)
            item.collections = self._get_item_collections(conn, item.item_id)
            item.pdf_path = self._get_pdf_path(conn, item.item_id)
            return item

    def _get_authors(self, conn: sqlite3.Connection, item_id: int) -> list[str]:
        """Get authors for an item."""
        cursor = conn.execute(
            """
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        )
        return [
            f"{row['firstName']} {row['lastName']}".strip()
            for row in cursor.fetchall()
        ]

    def _get_item_tags(self, conn: sqlite3.Connection, item_id: int) -> list[str]:
        """Get tags for an item."""
        cursor = conn.execute(
            """
            SELECT t.name FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID = ?
            ORDER BY t.name
            """,
            (item_id,),
        )
        return [row["name"] for row in cursor.fetchall()]

    def _get_item_collections(self, conn: sqlite3.Connection, item_id: int) -> list[str]:
        """Get collections for an item."""
        cursor = conn.execute(
            """
            SELECT c.collectionName FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE ci.itemID = ?
            ORDER BY c.collectionName
            """,
            (item_id,),
        )
        return [row["collectionName"] for row in cursor.fetchall()]

    def _get_pdf_path(self, conn: sqlite3.Connection, item_id: int) -> Path | None:
        """Get PDF attachment path for an item."""
        cursor = conn.execute(
            """
            SELECT ia.path, i.key
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            WHERE ia.parentItemID = ?
            AND (ia.contentType = 'application/pdf' OR ia.path LIKE '%.pdf')
            LIMIT 1
            """,
            (item_id,),
        )
        row = cursor.fetchone()
        if row and row["key"]:
            storage_dir = self.storage_path / row["key"]
            if storage_dir.exists():
                pdfs = list(storage_dir.glob("*.pdf"))
                if pdfs:
                    return pdfs[0]
        return None

    def get_all_tags(self) -> list[Tag]:
        """Get all tags with usage counts."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT t.tagID, t.name, COUNT(it.itemID) as count
                FROM tags t
                LEFT JOIN itemTags it ON t.tagID = it.tagID
                GROUP BY t.tagID
                ORDER BY t.name
                """
            )
            return [
                Tag(tag_id=row["tagID"], name=row["name"], count=row["count"])
                for row in cursor.fetchall()
            ]

    def get_all_collections(self) -> list[Collection]:
        """Get all collections with item counts."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT c.collectionID, c.collectionName, c.parentCollectionID,
                       COUNT(ci.itemID) as count
                FROM collections c
                LEFT JOIN collectionItems ci ON c.collectionID = ci.collectionID
                GROUP BY c.collectionID
                ORDER BY c.collectionName
                """
            )
            return [
                Collection(
                    collection_id=row["collectionID"],
                    name=row["collectionName"],
                    parent_id=row["parentCollectionID"],
                    item_count=row["count"],
                )
                for row in cursor.fetchall()
            ]

    def add_tag(self, item_id: int, tag_name: str) -> bool:
        """Add a tag to an item."""
        with self.write_connection() as conn:
            # Get or create tag
            cursor = conn.execute("SELECT tagID FROM tags WHERE name = ?", (tag_name,))
            row = cursor.fetchone()
            if row:
                tag_id = row["tagID"]
            else:
                cursor = conn.execute("INSERT INTO tags (name) VALUES (?)", (tag_name,))
                tag_id = cursor.lastrowid

            # Check if already tagged
            cursor = conn.execute(
                "SELECT 1 FROM itemTags WHERE itemID = ? AND tagID = ?",
                (item_id, tag_id),
            )
            if cursor.fetchone():
                return False  # Already tagged

            # Add tag
            conn.execute(
                "INSERT INTO itemTags (itemID, tagID, type) VALUES (?, ?, 0)",
                (item_id, tag_id),
            )
            return True

    def remove_tag(self, item_id: int, tag_name: str) -> bool:
        """Remove a tag from an item."""
        with self.write_connection() as conn:
            cursor = conn.execute("SELECT tagID FROM tags WHERE name = ?", (tag_name,))
            row = cursor.fetchone()
            if not row:
                return False

            tag_id = row["tagID"]
            cursor = conn.execute(
                "DELETE FROM itemTags WHERE itemID = ? AND tagID = ?",
                (item_id, tag_id),
            )
            return cursor.rowcount > 0

    def rename_tag(self, old_name: str, new_name: str) -> int:
        """Rename a tag globally. Returns number of items affected."""
        with self.write_connection() as conn:
            # Check if old tag exists
            cursor = conn.execute("SELECT tagID FROM tags WHERE name = ?", (old_name,))
            row = cursor.fetchone()
            if not row:
                return 0

            old_tag_id = row["tagID"]

            # Check if new tag already exists
            cursor = conn.execute("SELECT tagID FROM tags WHERE name = ?", (new_name,))
            row = cursor.fetchone()

            if row:
                # Merge into existing tag
                new_tag_id = row["tagID"]
                # Move items to new tag (ignore conflicts)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO itemTags (itemID, tagID, type)
                    SELECT itemID, ?, type FROM itemTags WHERE tagID = ?
                    """,
                    (new_tag_id, old_tag_id),
                )
                # Delete old tag associations
                conn.execute("DELETE FROM itemTags WHERE tagID = ?", (old_tag_id,))
                # Delete old tag
                conn.execute("DELETE FROM tags WHERE tagID = ?", (old_tag_id,))
            else:
                # Simply rename
                conn.execute(
                    "UPDATE tags SET name = ? WHERE tagID = ?",
                    (new_name, old_tag_id),
                )

            # Return count of items with this tag
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM itemTags WHERE tagID = ?",
                (row["tagID"] if row else old_tag_id,),
            )
            return cursor.fetchone()["count"]

    def delete_tag(self, name: str) -> int:
        """Delete a tag entirely, removing it from all items.

        Returns the number of items the tag was removed from. Use for
        clearing junk/auto-imported tags that have no place in the scheme.
        """
        with self.write_connection() as conn:
            row = conn.execute("SELECT tagID FROM tags WHERE name = ?", (name,)).fetchone()
            if not row:
                return 0
            tag_id = row["tagID"]
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM itemTags WHERE tagID = ?", (tag_id,)
            ).fetchone()["c"]
            conn.execute("DELETE FROM itemTags WHERE tagID = ?", (tag_id,))
            conn.execute("DELETE FROM tags WHERE tagID = ?", (tag_id,))
            return count

    def get_untagged_items(self, limit: int = 100) -> list[ZoteroItem]:
        """Get items with no tags."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT i.itemID, i.key, it.typeName,
                    MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                    MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date,
                    MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                LEFT JOIN itemData id ON i.itemID = id.itemID
                LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
                LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
                LEFT JOIN deletedItems di ON i.itemID = di.itemID
                WHERE di.itemID IS NULL
                AND it.typeName NOT IN ('attachment', 'note')
                AND NOT EXISTS (SELECT 1 FROM itemTags it2 WHERE it2.itemID = i.itemID)
                GROUP BY i.itemID
                ORDER BY date DESC
                LIMIT ?
                """,
                (limit,),
            )
            items = []
            for row in cursor.fetchall():
                item = ZoteroItem(
                    item_id=row["itemID"],
                    key=row["key"],
                    item_type=row["typeName"],
                    title=row["title"] or "",
                    date=row["date"] or "",
                    abstract=row["abstract"] or "",
                )
                item.authors = self._get_authors(conn, item.item_id)
                items.append(item)
            return items

    def get_items_in_collection(self, collection_name: str) -> list[ZoteroItem]:
        """Get all items in a collection by name."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                SELECT i.itemID, i.key, it.typeName,
                    MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                    MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date,
                    MAX(CASE WHEN f.fieldName='abstractNote' THEN idv.value END) as abstract
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                JOIN collectionItems ci ON i.itemID = ci.itemID
                JOIN collections c ON ci.collectionID = c.collectionID
                LEFT JOIN itemData id ON i.itemID = id.itemID
                LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
                LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
                LEFT JOIN deletedItems di ON i.itemID = di.itemID
                WHERE di.itemID IS NULL
                AND it.typeName NOT IN ('attachment', 'note')
                AND c.collectionName = ?
                GROUP BY i.itemID
                ORDER BY date DESC
                """,
                (collection_name,),
            )
            items = []
            for row in cursor.fetchall():
                item = ZoteroItem(
                    item_id=row["itemID"],
                    key=row["key"],
                    item_type=row["typeName"],
                    title=row["title"] or "",
                    date=row["date"] or "",
                    abstract=row["abstract"] or "",
                )
                item.authors = self._get_authors(conn, item.item_id)
                item.tags = self._get_item_tags(conn, item.item_id)
                items.append(item)
            return items

    def tag_collection(self, collection_name: str, tag_name: str) -> int:
        """Add a tag to all items in a collection. Returns count of items tagged."""
        items = self.get_items_in_collection(collection_name)
        count = 0
        for item in items:
            if self.add_tag(item.item_id, tag_name):
                count += 1
        return count

    def find_duplicates(self) -> list[list[ZoteroItem]]:
        """Find duplicate items by title. Returns groups of duplicates."""
        with self.connection() as conn:
            # Find titles that appear more than once
            cursor = conn.execute(
                """
                SELECT LOWER(idv.value) as norm_title, GROUP_CONCAT(i.itemID) as item_ids
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                JOIN itemData id ON i.itemID = id.itemID
                JOIN fieldsCombined f ON id.fieldID = f.fieldID
                JOIN itemDataValues idv ON id.valueID = idv.valueID
                LEFT JOIN deletedItems di ON i.itemID = di.itemID
                WHERE di.itemID IS NULL
                AND it.typeName NOT IN ('attachment', 'note')
                AND f.fieldName = 'title'
                GROUP BY norm_title
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC
                """
            )

            duplicate_groups = []
            for row in cursor.fetchall():
                item_ids = [int(x) for x in row["item_ids"].split(",")]
                group = []
                for item_id in item_ids:
                    item = self._get_item_basic(conn, item_id)
                    if item:
                        item.tags = self._get_item_tags(conn, item_id)
                        group.append(item)
                if len(group) > 1:
                    # Sort by number of tags (most tags first)
                    group.sort(key=lambda x: len(x.tags), reverse=True)
                    duplicate_groups.append(group)

            return duplicate_groups

    def _get_item_basic(self, conn, item_id: int) -> ZoteroItem | None:
        """Get basic item info (used internally)."""
        cursor = conn.execute(
            """
            SELECT i.itemID, i.key, it.typeName,
                MAX(CASE WHEN f.fieldName='title' THEN idv.value END) as title,
                MAX(CASE WHEN f.fieldName='date' THEN idv.value END) as date
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            LEFT JOIN itemData id ON i.itemID = id.itemID
            LEFT JOIN fieldsCombined f ON id.fieldID = f.fieldID
            LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
            WHERE i.itemID = ?
            GROUP BY i.itemID
            """,
            (item_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return ZoteroItem(
            item_id=row["itemID"],
            key=row["key"],
            item_type=row["typeName"],
            title=row["title"] or "",
            date=row["date"] or "",
        )

    def delete_item(self, item_id: int) -> bool:
        """Move an item to trash. Returns True if successful."""
        with self.write_connection() as conn:
            # Check if item exists and not already deleted
            cursor = conn.execute(
                "SELECT 1 FROM items i LEFT JOIN deletedItems di ON i.itemID = di.itemID "
                "WHERE i.itemID = ? AND di.itemID IS NULL",
                (item_id,),
            )
            if not cursor.fetchone():
                return False

            # Add to deletedItems (Zotero's trash)
            conn.execute(
                "INSERT INTO deletedItems (itemID, dateDeleted) VALUES (?, datetime('now'))",
                (item_id,),
            )
            return True

    def delete_duplicate_untagged(self, dry_run: bool = True) -> list[tuple[int, str]]:
        """Delete duplicate items that have no tags (keep the tagged one).

        Returns list of (item_id, title) that were/would be deleted.
        """
        duplicates = self.find_duplicates()
        to_delete = []

        for group in duplicates:
            # Keep the first one (most tags), delete the rest if they have no tags
            for item in group[1:]:  # Skip first (most tagged)
                if len(item.tags) == 0:
                    to_delete.append((item.item_id, item.title))
                    if not dry_run:
                        self.delete_item(item.item_id)

        return to_delete

    def find_existing_item(
        self, doi: str | None = None, title: str | None = None
    ) -> int | None:
        """Find a non-deleted item by DOI (preferred) or exact title.

        Returns the itemID of the first match, or None. Used to avoid adding
        duplicates. DOI is checked first; title is an exact, case-insensitive
        fallback for items that lack a DOI.
        """
        with self.connection() as conn:
            if doi:
                row = conn.execute(
                    """
                    SELECT i.itemID
                    FROM items i
                    JOIN itemData id ON i.itemID = id.itemID
                    JOIN fieldsCombined f ON id.fieldID = f.fieldID
                    JOIN itemDataValues idv ON id.valueID = idv.valueID
                    LEFT JOIN deletedItems di ON i.itemID = di.itemID
                    WHERE f.fieldName = 'DOI' AND idv.value = ?
                    AND di.itemID IS NULL
                    LIMIT 1
                    """,
                    (doi,),
                ).fetchone()
                if row:
                    return row["itemID"]

            if title:
                row = conn.execute(
                    """
                    SELECT i.itemID
                    FROM items i
                    JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                    JOIN itemData id ON i.itemID = id.itemID
                    JOIN fieldsCombined f ON id.fieldID = f.fieldID
                    JOIN itemDataValues idv ON id.valueID = idv.valueID
                    LEFT JOIN deletedItems di ON i.itemID = di.itemID
                    WHERE f.fieldName = 'title' AND LOWER(idv.value) = LOWER(?)
                    AND di.itemID IS NULL
                    AND it.typeName NOT IN ('attachment', 'note')
                    LIMIT 1
                    """,
                    (title,),
                ).fetchone()
                if row:
                    return row["itemID"]

        return None

    def add_item(self, metadata: dict, pdf_path: Path) -> int:
        """Add a journalArticle with a PDF attachment to the library.

        Inserts the item, its fields, authors, and a PDF attachment, then
        copies the PDF into Zotero storage. Returns the new item's ID.

        Note: writes directly to the live database, so Zotero should be closed.
        Callers are responsible for duplicate checking via find_existing_item.
        """
        item_key = _generate_key()
        attachment_key = _generate_key()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self.write_connection() as conn:
            item_type_id = conn.execute(
                "SELECT itemTypeID FROM itemTypes WHERE typeName = 'journalArticle'"
            ).fetchone()["itemTypeID"]
            attachment_type_id = conn.execute(
                "SELECT itemTypeID FROM itemTypes WHERE typeName = 'attachment'"
            ).fetchone()["itemTypeID"]
            library_id = conn.execute(
                "SELECT libraryID FROM libraries LIMIT 1"
            ).fetchone()["libraryID"]

            # Insert main item
            cursor = conn.execute(
                """
                INSERT INTO items
                    (itemTypeID, libraryID, key, dateAdded, dateModified,
                     clientDateModified, version, synced)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                """,
                (item_type_id, library_id, item_key, now, now, now),
            )
            item_id = cursor.lastrowid

            def add_field(field_name: str, value: str | None) -> None:
                if not value:
                    return
                row = conn.execute(
                    "SELECT fieldID FROM fieldsCombined WHERE fieldName = ?",
                    (field_name,),
                ).fetchone()
                if not row:
                    return
                field_id = row["fieldID"]

                row = conn.execute(
                    "SELECT valueID FROM itemDataValues WHERE value = ?", (value,)
                ).fetchone()
                if row:
                    value_id = row["valueID"]
                else:
                    value_id = conn.execute(
                        "INSERT INTO itemDataValues (value) VALUES (?)", (value,)
                    ).lastrowid

                conn.execute(
                    "INSERT INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
                    (item_id, field_id, value_id),
                )

            add_field("title", metadata.get("title"))
            add_field("DOI", metadata.get("doi"))
            add_field("abstractNote", metadata.get("abstract"))
            add_field("publicationTitle", metadata.get("journal"))
            add_field("date", metadata.get("year"))
            add_field("volume", metadata.get("volume"))
            add_field("issue", metadata.get("issue"))
            add_field("pages", metadata.get("pages"))

            # Add authors
            author_type_id = conn.execute(
                "SELECT creatorTypeID FROM creatorTypes WHERE creatorType = 'author'"
            ).fetchone()["creatorTypeID"]

            for i, author in enumerate(metadata.get("authors", [])):
                first = author.get("first", "")
                last = author.get("last", "")
                row = conn.execute(
                    "SELECT creatorID FROM creators WHERE firstName = ? AND lastName = ?",
                    (first, last),
                ).fetchone()
                if row:
                    creator_id = row["creatorID"]
                else:
                    creator_id = conn.execute(
                        "INSERT INTO creators (firstName, lastName) VALUES (?, ?)",
                        (first, last),
                    ).lastrowid

                conn.execute(
                    """
                    INSERT INTO itemCreators (itemID, creatorID, creatorTypeID, orderIndex)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_id, creator_id, author_type_id, i),
                )

            # Create PDF attachment
            cursor = conn.execute(
                """
                INSERT INTO items
                    (itemTypeID, libraryID, key, dateAdded, dateModified,
                     clientDateModified, version, synced)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0)
                """,
                (attachment_type_id, library_id, attachment_key, now, now, now),
            )
            attachment_id = cursor.lastrowid

            filename = _storage_filename(metadata, pdf_path)
            conn.execute(
                """
                INSERT INTO itemAttachments
                    (itemID, parentItemID, linkMode, contentType, path, syncState)
                VALUES (?, ?, 1, 'application/pdf', ?, 0)
                """,
                (attachment_id, item_id, f"storage:{filename}"),
            )

        # Copy PDF into Zotero storage (after the write transaction commits)
        dest_dir = self.storage_path / attachment_key
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, dest_dir / filename)

        return item_id
