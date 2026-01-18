# zotero-cli

A powerful command-line interface for managing your Zotero library without the GUI. Search, tag, organize, and browse your references directly from the terminal.

## Features

- **Fast search** across titles, authors, abstracts, tags, and collections
- **Interactive browser** with fzf for fuzzy finding and previews
- **Smart tag suggestions** based on paper content
- **Bulk operations** for tagging entire collections
- **Duplicate detection** and cleanup
- **Obsidian integration** for literature notes
- **Citation generation** in multiple formats

## Installation

```bash
# Clone or navigate to the repo
cd ~/local/code/python/developing/zotero-cli

# Install in development mode
pip install -e .

# Install fzf for interactive mode (macOS)
brew install fzf
```

## Quick Start

```bash
# Launch interactive browser
zot

# Search for papers
zot search "RNA structure"

# View your tag hierarchy
zot tags --tree

# Add a tag to a paper
zot tag 123 "method/dms"
```

---

## Commands Reference

### Interactive Mode

Launch an fzf-powered browser to search and manage your library.

```bash
zot                     # Launch interactive browser
zot i                   # Same as above
zot i "SHAPE"           # Start with a search query
```

**Keybindings:**
| Key | Action |
|-----|--------|
| `Enter` | Show item details |
| `Ctrl-O` | Open PDF |
| `Ctrl-T` | Add tag (opens tag selector) |
| `Ctrl-Y` | Copy DOI to clipboard |
| `Tab` | Select multiple items |
| `Esc` | Exit |

**Search syntax:**
| Prefix | Example | Description |
|--------|---------|-------------|
| `a:` | `a:weeks` | Author contains "weeks" |
| `a:` | `a:week*` | Author starts with "week" |
| `y:` | `y:2024` | Exact year |
| `y:` | `y:2020-2024` | Year range (inclusive) |
| `y:` | `y:2020+` | 2020 and later |
| `y:` | `y:-2015` | 2015 and earlier |
| `t:` | `t:method/dms` | Tag contains "method/dms" |
| `t:` | `t:method/*` | Any tag under method/ |
| `j:` | `j:nat*` | Journal starts with "nat" |
| (text) | `RNA structure` | Search title & abstract |

**Combine filters:** `a:weeks y:2020+ thermodynamics`

Results show: Year, Author, Title, Tags. Preview pane shows full details.

---

### Search & Browse

#### Search

```bash
# Full-text search in titles and abstracts
zot search "tetraloop receptor"

# Filter by author
zot search --author "Weeks"
zot search -a "Weeks"

# Filter by tag
zot search --tag "method/chemical-mapping"
zot search -t "method/dms"

# Filter by year
zot search --year 2024
zot search -y 2024

# Filter by collection
zot search --collection "RNA"
zot search -c "my-writings"

# Combine filters
zot search "thermodynamics" --author "Turner" --year 2020

# Limit results
zot search "RNA" --limit 50
zot search "RNA" -n 50
```

#### List

```bash
# List recent items
zot list

# List untagged items
zot list --untagged
zot list -u

# Control number of results
zot list --limit 100
zot list -n 100
```

---

### View Items

#### Show Details

```bash
# Full item details (metadata, tags, abstract, PDF path)
zot show 123
```

Output includes:
- Title, authors, date, journal
- DOI and Zotero key
- Tags and collections
- PDF location
- Full abstract

#### Abstract Only

```bash
zot abstract 123
```

#### Open PDF

```bash
# Open in default PDF viewer
zot open 123

# Open with specific app
zot open 123 --app "Preview"
zot open 123 -a "Skim"
```

#### Get PDF Path

```bash
# Print path (useful for scripting)
zot path 123
# Output: /Users/you/Zotero/storage/ABC123/Paper.pdf
```

#### Add PDF to Zotero

```bash
# Open PDF in Zotero (use "Retrieve Metadata" to import)
zot add paper.pdf

# Add and move original to trash
zot add paper.pdf --trash
zot add paper.pdf -t

# Add and permanently delete original
zot add paper.pdf --delete
zot add paper.pdf -d
```

---

### Tag Management

#### View Tags

```bash
# List all tags with counts
zot tags

# Show as hierarchy tree
zot tags --tree
zot tags -t
```

Example tree output:
```
Tags
├── cited/
│   ├── 2019-rnamake (12)
│   ├── 2024-qmap-seq (43)
│   └── 2024-quant-framework-dms (25)
├── method/
│   ├── chemical-mapping (31)
│   ├── dms (5)
│   ├── ml (3)
│   └── ...
├── topic/
│   ├── thermodynamics (13)
│   ├── tc-thermodynamics (18)
│   └── ...
```

#### Add Tag

```bash
zot tag 123 "method/shape"
zot tag 123 "topic/thermodynamics"
```

#### Remove Tag

```bash
zot untag 123 "old-tag"
```

#### Rename Tag Globally

```bash
# Rename across all items
zot retag "rna_flexibility" "rna-flexibility"
# Output: Renamed 'rna_flexibility' → 'rna-flexibility' (5 items)
```

#### Bulk Tag Collection

```bash
# Add tag to all items in a collection
zot tag-collection "mg-stablization" "topic/mg-binding"
zot tag-collection "Deep learning" "method/ml"
```

---

### Smart Tag Suggestions

The tool analyzes titles and abstracts to suggest relevant tags.

#### Suggest for Single Item

```bash
# Preview suggestions
zot suggest 123

# Apply suggestions automatically
zot suggest 123 --apply
zot suggest 123 -a

# Adjust confidence threshold (default: 0.7)
zot suggest 123 --threshold 0.8
zot suggest 123 -t 0.8
```

Example output:
```
RNA secondary structure packages evaluated and improved...
Current tags: none

                  Suggested Tags
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Tag                       ┃ Confidence ┃ Reason             ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ topic/secondary-structure │        90% │ matched 'secondary │
│ method/comput             │        75% │ matched 'benchmark'│
└───────────────────────────┴────────────┴────────────────────┘
```

#### Suggest for All Untagged

```bash
# Preview suggestions for untagged items
zot suggest-all
zot suggest-all --limit 50

# Apply high-confidence suggestions
zot suggest-all --apply --threshold 0.85
```

**Recognized patterns include:**
- Methods: `chemical-mapping`, `dms`, `shape`, `cryo-em`, `nmr`, `fret`, `ml`
- Systems: `ribosome`, `spliceosome`, `aptamer`, `ttr`, `riboswitch`
- Topics: `secondary-structure`, `tertiary-structure`, `thermodynamics`
- Types: `review`, `method`, `benchmark`

---

### Duplicate Management

#### Find Duplicates

```bash
zot duplicates
```

Output shows duplicate groups with tag counts:
```
Found 18 duplicate groups:

Viral RNA structure analysis using DMS-MaPseq
    515  4 tags  KEEP
     50  no tags

High-throughput determination of RNA tertiary contact...
    544  5 tags  KEEP
    638  no tags
```

#### Remove Untagged Duplicates

```bash
# Preview what would be deleted (dry run)
zot dedup

# Actually delete (moves to Zotero trash)
zot dedup --apply
```

**Note:** Close Zotero before running `--apply` to avoid database locks.

---

### Collections

```bash
# List all collections with item counts
zot collections

# Show as hierarchy tree
zot collections --tree
zot collections -t
```

---

### Citations

```bash
# Inline citation: "Author (Year)"
zot cite 123
# Output: Weeks (2024)

# BibTeX format
zot cite 123 --format bibtex
zot cite 123 -f bibtex

# APA format
zot cite 123 --format apa
zot cite 123 -f apa
```

---

### Obsidian Integration

Create literature notes in your Obsidian vault with full metadata.

#### Create Literature Note

```bash
# Auto-detect vault location
zot note 123

# Specify vault path
zot note 123 --vault ~/Obsidian/Main
zot note 123 -v ~/Obsidian/Main

# Custom folder within vault
zot note 123 --folder "Literature"
zot note 123 -f "Literature"

# Overwrite existing note
zot note 123 --overwrite
```

**Generated note includes:**
- YAML frontmatter (title, authors, year, DOI, tags)
- Zotero links (open item, open PDF)
- Abstract
- Sections for notes, key points, questions

#### Get Links

```bash
# Zotero URI (opens item in Zotero)
zot link 123
# Output: zotero://select/items/@ABC123

# PDF URI
zot link 123 --type pdf
# Output: zotero://open-pdf/library/items/ABC123

# Obsidian wikilink
zot link 123 --type obsidian
# Output: [[Weeks2024]]
```

#### Find Related Notes

```bash
# Search vault for notes mentioning this item
zot related 123
zot related 123 --vault ~/Obsidian/Main
```

**Configuration:**
```bash
# Set default vault path
export OBSIDIAN_VAULT=~/Obsidian/Main
```

---

## Tag System

### Recommended Hierarchy

```
cited/              # Papers you've cited
  cited/2019-rnamake
  cited/2024-qmap-seq
  cited/2024-quant-framework-dms

method/             # Experimental methods
  method/chemical-mapping
  method/dms
  method/shape
  method/cryo-em
  method/xray
  method/nmr
  method/fret
  method/afm
  method/ml

system/             # Biological systems
  system/ribosome
  system/spliceosome
  system/aptamer
  system/riboswitch
  system/ttr
  system/kink-turn

topic/              # Research topics
  topic/thermodynamics
  topic/tc-thermodynamics
  topic/3d-thermodynamics
  topic/secondary-structure
  topic/tertiary-structure
  topic/rna-dynamics
  topic/rna-protonation
  topic/structure-prediction

type/               # Paper category
  type/review
  type/method
  type/my-paper
  type/book
  type/benchmark

status/             # Reading workflow
  status/to-read
  status/key-paper
  status/to-cite

lab/                # Teaching resources
  lab/intro-paper

project/            # Active projects
  project/current-paper
  project/grant-r01
```

### Naming Conventions

- Use **lowercase**
- Use **hyphens** not underscores: `rna-dynamics` not `rna_dynamics`
- Use **hierarchical** format: `method/chemical-mapping`
- Keep names **short but descriptive**

---

## Workflows

### Organizing a New Paper

```bash
# 1. Find the paper
zot search "author name" --year 2024

# 2. View details
zot show 123

# 3. Get tag suggestions
zot suggest 123

# 4. Add tags
zot tag 123 "method/chemical-mapping"
zot tag 123 "system/ribosome"
zot tag 123 "cited/2024-qmap-seq"
```

### Cleaning Up Your Library

```bash
# 1. Find duplicates
zot duplicates

# 2. Remove untagged duplicates (close Zotero first!)
zot dedup --apply

# 3. See what's untagged
zot list --untagged

# 4. Auto-tag with high confidence
zot suggest-all --apply --threshold 0.85

# 5. Manually tag the rest with interactive mode
zot i
```

### Converting Collections to Tags

```bash
# Tag all items in old collections
zot tag-collection "mg-stablization" "topic/mg-binding"
zot tag-collection "tertiary-contact-thermo" "topic/tc-thermodynamics"
zot tag-collection "rna_dynamics" "topic/rna-dynamics"

# Now you can search by tag instead of collection
zot search --tag "topic/mg-binding"
```

### Creating Literature Notes

```bash
# For a single important paper
zot note 123 --folder "References"

# Batch create notes for key papers
for id in 123 456 789; do
  zot note $id --folder "References"
done
```

---

## Tips

1. **Close Zotero** before write operations (`tag`, `dedup --apply`, etc.) to avoid database locks

2. **Use interactive mode** (`zot` or `zot i`) for quick browsing and tagging

3. **Tags vs Collections**: Use tags for permanent metadata (what it's about), collections for workflow (what you're working on)

4. **Start with `cited/` tags**: Track which of your papers cited each reference

5. **Use `suggest-all`** periodically to catch untagged items

---

## Troubleshooting

### "Database is locked"
Close Zotero and try again. Zotero locks its database while running.

### "fzf not found"
Install fzf: `brew install fzf` (macOS) or `apt install fzf` (Linux)

### "Vault not found"
Set your Obsidian vault path:
```bash
export OBSIDIAN_VAULT=~/path/to/vault
```
Or use the `--vault` flag.

---

## Database Location

Default Zotero paths:
- Database: `~/Zotero/zotero.sqlite`
- PDFs: `~/Zotero/storage/`

The tool reads from these locations automatically.
