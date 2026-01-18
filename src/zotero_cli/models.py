"""Data models for Zotero items."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ZoteroItem:
    """Represents a Zotero library item."""

    item_id: int
    key: str
    item_type: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    date: str = ""
    abstract: str = ""
    journal: str = ""
    doi: str = ""
    url: str = ""
    tags: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    pdf_path: Path | None = None

    @property
    def first_author(self) -> str:
        """Return first author's last name."""
        if self.authors:
            return self.authors[0].split()[-1]
        return ""

    @property
    def year(self) -> str:
        """Extract year from date field."""
        if self.date and len(self.date) >= 4:
            return self.date[:4]
        return ""

    @property
    def citation_key(self) -> str:
        """Generate a citation key like 'Author2024'."""
        return f"{self.first_author}{self.year}"

    def short_title(self, max_len: int = 60) -> str:
        """Return truncated title."""
        if len(self.title) <= max_len:
            return self.title
        return self.title[: max_len - 3] + "..."


@dataclass
class Tag:
    """Represents a Zotero tag."""

    tag_id: int
    name: str
    count: int = 0

    @property
    def category(self) -> str | None:
        """Get tag category (e.g., 'method' from 'method/dms')."""
        if "/" in self.name:
            return self.name.split("/")[0]
        return None

    @property
    def subcategory(self) -> str | None:
        """Get tag subcategory (e.g., 'dms' from 'method/dms')."""
        if "/" in self.name:
            parts = self.name.split("/")
            return parts[1] if len(parts) > 1 else None
        return None


@dataclass
class Collection:
    """Represents a Zotero collection."""

    collection_id: int
    name: str
    parent_id: int | None = None
    item_count: int = 0
