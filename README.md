# Agent Rewind

Undo the AI. Keep my edits.

You asked a coding agent to change a file, then added a change of your own. Agent Rewind compares the Git history with your working copy and previews which agent edits it can reverse while keeping yours.

| Demo file | What changed | What Rewind proposes |
| --- | --- | --- |
| `config.py` | The agent enabled caching. You later added `LOG_LEVEL = "debug"`. | Restore `CACHE_ENABLED = False` and keep your logging setting. |
| `worker.py` | The agent changed retries from `3` to `5`. You then changed the same line to `8`. | Flag the overlap for review and show all three versions. |

## Try the browser demo

With Python 3.10+ and Git installed, run this from the project directory:

```powershell
python demo.py
Invoke-Item .\rewind-demo.html
```

The script builds a temporary Git history and saves a standalone report with **one clean rewind and one conflict**. Expand `config.py` to see the proposed diff. The `worker.py` conflict opens by default. Use `--output another-demo.html` to generate a second report at a new path.

## Run the terminal demo

```powershell
python rewind.py
```

The first example restores the original cache setting and keeps the logging setting added later. The second example flags a conflict where the human and the agent edited the same line. Both examples print previews using sample data.

## Preview your own files

Save three UTF-8 versions of the same text file, then run:

```powershell
python rewind.py --before before.py --after after.py --current current.py
```

Use the original file for `--before`, the version immediately after the agent's changes for `--after`, and the version with any later edits for `--current`. The command reads the inputs and prints a diff or a conflict preview. Exit codes are 0 for a clean preview, 1 for conflicts, and 2 for input or execution errors.

To save a clean result, add `--output rewound.py`:

```powershell
python rewind.py --before before.py --after after.py --current current.py --output rewound.py
```

Choose a new output path. If the path already exists, the command reports an error. If the merge has conflicts, the command prints the conflict preview and leaves the output path untouched.

The prototype uses three versions of a text file: before the agent's edit, after the agent's edit, and the current version. It uses Git's three-way merge to apply the inverse change to the current version. The result is a preview.

## Read the earlier versions from Git

If the agent's edit is your latest commit, run this from your checkout:

```powershell
python rewind.py --before-ref HEAD~1 --after-ref HEAD --current config.py
```

For an older edit, use the two commit IDs that bracket the agent's changes. The current file can include uncommitted edits. Git mode reads the same repository-relative path from both commits, so use a text file that exists at that path in both versions. Add `--output rewound.py` to save a clean result.

## Preview all files changed between two commits

Run this from inside the Git checkout you want to review:

```powershell
python rewind.py --before-ref HEAD~1 --after-ref HEAD --all
```

Rewind reads the working copy of each modified UTF-8 text file and prints a diff or conflict preview. It reports additions, deletions, renames (as additions and deletions), mode changes, binary files, and missing working files as skipped. The summary counts clean changes, files already in the desired state, conflicts, and skips. Exit codes are 0 for a complete clean preview, 1 if anything needs review or was skipped, and 2 for setup errors. Batch mode writes no files.

Add `--json` to write a machine-readable batch report to standard output:

```powershell
python rewind.py --before-ref HEAD~1 --after-ref HEAD --all --json
```

The report includes a schema version, resolved commit IDs, summary counts, and one entry per path. Entries contain a diff for clean rewinds, a conflict preview for overlaps, or a reason for skips. The same exit codes apply.

For a browser review, save a standalone HTML report and open it locally:

```powershell
python -X utf8 rewind.py --before-ref HEAD~1 --after-ref HEAD --all --html | Out-File -Encoding utf8 rewind-report.html
Invoke-Item .\rewind-report.html
```

The report opens conflicts by default and lets you expand clean diffs and skip reasons. It contains file contents from the preview, so review it before sharing.

## Compare rewind strategies

Run the six-case evaluation with:

```powershell
python benchmark.py
```

| Strategy | Exact matches on five clean cases | Flagged the overlapping edit |
| --- | ---: | --- |
| Full restore | 1/5 | No |
| Skip files edited later | 1/5 | No |
| Selective reversal using Git's three-way merge | 5/5 | Yes |

These hand-written fixtures illustrate the tradeoffs in a single text file. They are the starting point for a broader evaluation across real change histories.
