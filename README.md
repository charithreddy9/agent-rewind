# Agent Rewind

Undo the AI. Keep my edits.

You asked a coding agent to change a file, then added a change of your own. Agent Rewind compares the Git history with your working copy and previews which agent edits it can reverse while keeping yours.

| Demo file | What changed | What Rewind proposes |
| --- | --- | --- |
| `config.py` | The agent enabled caching. You later added `LOG_LEVEL = "debug"`. | Restore `CACHE_ENABLED = False` and keep your logging setting. |
| `worker.py` | The agent changed retries from `3` to `5`. You then changed the same line to `8`. | Flag the overlap for review and show all three versions. |
| `limits.json` | The agent raised the maximum from `4` to `8`. You later raised the minimum to `6`. | Flag the clean textual merge because restoring the maximum to `4` would violate the configured limit. |

## Try the browser demo

With Python 3.10+ and Git installed, run this from the project directory:

```powershell
python demo.py
Invoke-Item .\rewind-demo.html
```

The script builds a temporary Git history and saves a standalone report with **one clean rewind, one textual conflict, and one failed configuration rule**. Expand `config.py` to see the proposed diff. The two entries requiring review open by default. Use `--output another-demo.html` to generate a second report at a new path.

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

## Check proposed JSON changes against project rules

Save a UTF-8 file named `rewind-rules.json`. Use repository-relative paths and pairs of top-level JSON keys. Each pair requires a finite numeric lower value less than or equal to the upper value.

```json
{
  "config/limits.json": [["min_workers", "max_workers"]]
}
```

```powershell
python rewind.py --before-ref HEAD~1 --after-ref HEAD --all --rules rewind-rules.json --json
```

Rules run on listed files with proposed text changes after the textual merge succeeds. Missing keys, invalid JSON, and violated comparisons require review. Reports show how many files were checked. A validation failure returns exit code 1 and includes the proposed diff and reasons. This option is for batch previews.

## Compare rewind strategies

Run the 12-case evaluation and regression tests with:

```powershell
python benchmark.py
python -m unittest -v
```

| Strategy | Exact matches out of 9 cases with an expected result | Review flags out of 3 cases requiring review |
| --- | ---: | ---: |
| Full restore | 1/9 | 0/3 |
| Skip files edited later | 2/9 | 0/3 |
| Selective reversal using Git's three-way merge | 8/9 | 1/3 |
| Selective reversal with supplied rules | 8/9 | 3/3 |

The results come from hand-written fixtures, including cases designed around known configuration rules. See the [research note](RESEARCH.md) for the method, related work, full outcome counts, and limitations.
