# Agent Rewind

Undo the AI. Keep my edits.

Agent Rewind previews how to reverse a coding agent's changes while preserving later human edits to the same file.

## Run the first demo

With Python 3.10+ and Git installed, run this from the project directory:

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

A future evaluation will compare full restore, skipping edited files, and selective reversal. It will measure agent changes removed, human edits preserved, and conflicts requiring review.
