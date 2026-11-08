# Agent Rewind

Undo the AI. Keep my edits.

Agent Rewind previews how to reverse a coding agent's changes while preserving later human edits to the same file.

## Run the first demo

With Python 3.10+ and Git installed, run this from the project directory:

```powershell
python rewind.py
```

The first example restores the original cache setting and keeps the logging setting added later. The second example flags a conflict where the human and the agent edited the same line. Both examples print previews using sample data.

The prototype uses three versions of a text file: before the agent's edit, after the agent's edit, and the current version. It uses Git's three-way merge to apply the inverse change to the current version. The result is a preview.

A future evaluation will compare full restore, skipping edited files, and selective reversal. It will measure agent changes removed, human edits preserved, and conflicts requiring review.
