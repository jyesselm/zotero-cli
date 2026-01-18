# zotero-cli

Command-line interface for managing your Zotero library.

## Installation

```bash
pip install -e .
```

Requires `fzf` for interactive mode:
```bash
brew install fzf
```

## Usage

### Interactive Mode (fzf)

```bash
zot                     # Launch interactive browser
zot i                   # Same as above
zot i "RNA structure"   # Start with query
```

**Keybindings in interactive mode:**
- `Enter` - Show item details
- `Ctrl-O` - Open PDF
- `Ctrl-T` - Add tag (opens tag selector)
- `Ctrl-Y` - Copy DOI to clipboard
- `Tab` - Select multiple items

**Search syntax:**
- Free text searches all fields (year, author, title, tags, journal)
- Type to filter, fzf does fuzzy matching

### Search & Browse

```bash
# Search for items
zot search "RNA structure"
zot search --author "Weeks"
zot search --tag "method/dms"
zot search --year 2024
zot search --collection "RNA"

# List items
zot list
zot list --untagged
zot list --limit 50
```

### View Items

```bash
zot show 123           # Full item details
zot abstract 123       # Just the abstract
zot open 123           # Open PDF
zot path 123           # Print PDF path
```

### Tag Management

```bash
zot tags                    # List all tags
zot tags --tree             # Show tag hierarchy
zot tag 123 "method/shape"  # Add tag
zot untag 123 "old-tag"     # Remove tag
zot retag "old" "new"       # Rename tag globally
```

### Bulk Operations

```bash
# Tag all items in a collection
zot tag-collection "mg-stablization" "topic/mg-binding"

# Find duplicate items
zot duplicates

# Remove untagged duplicates (keeps tagged version)
zot dedup              # Dry run (preview)
zot dedup --apply      # Actually delete
```

### Smart Suggestions

```bash
zot suggest 123             # Get tag suggestions
zot suggest 123 --apply     # Apply suggestions
zot suggest-all --limit 50  # Suggest for untagged items
zot suggest-all --apply     # Auto-tag untagged items
```

### Collections & Citations

```bash
zot collections             # List collections
zot collections --tree      # Show hierarchy
zot cite 123                # Inline citation
zot cite 123 --format bibtex
zot cite 123 --format apa
```

### Obsidian Integration

```bash
# Create literature note
zot note 123                           # Auto-detect vault
zot note 123 --vault ~/Obsidian/Main   # Specify vault
zot note 123 --folder "Literature"     # Custom folder

# Get links
zot link 123                  # Zotero URI (opens in Zotero)
zot link 123 --type pdf       # PDF URI
zot link 123 --type obsidian  # Obsidian wikilink [[Author2024]]

# Find related notes
zot related 123               # Search vault for related notes
```

**Configuration:**
Set `OBSIDIAN_VAULT` environment variable to your vault path:
```bash
export OBSIDIAN_VAULT=~/Obsidian/Main
```

## Tag System

Recommended tag hierarchy:

```
cited/          # Papers cited in your publications
  cited/2019-rnamake
  cited/2024-qmap-seq

method/         # Experimental/computational methods
  method/chemical-mapping
  method/dms
  method/shape
  method/cryo-em
  method/ml

system/         # Biological systems
  system/ribosome
  system/aptamer
  system/ttr

type/           # Paper category
  type/review
  type/method
  type/my-paper

topic/          # Research topics
  topic/thermodynamics
  topic/tc-thermodynamics
  topic/tertiary-structure
  topic/rna-dynamics

status/         # Reading workflow
  status/to-read
  status/key-paper

lab/            # Teaching/lab resources
  lab/intro-paper
```
