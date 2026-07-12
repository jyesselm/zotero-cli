#!/bin/bash
# Weekly reading-list refresh: regenerate READING-LIST.md via `zot discover`.
# Review-only — adds nothing to Zotero. Installed as a weekly cron job.
# Change cadence: `crontab -e`.  Remove: delete the line mentioning this script.
ZOT="/opt/homebrew/Caskroom/mambaforge/base/envs/py3/bin/zot"
LOG="$HOME/notes/300-reference/science/.discover.log"
{
  echo "=== $(date '+%Y-%m-%d %H:%M') ==="
  "$ZOT" discover
  echo "exit $?"
} >>"$LOG" 2>&1
