# Agent Rewind

Undo the AI. Keep my edits.

Agent Rewind explores how to reverse a coding agent's changes while preserving later human edits to the same file.

The first demo will use a sample repository. An agent changes one setting, a person adds another, and Rewind previews which changes it can reverse. Overlapping edits are flagged for review.

The evaluation will compare full restore, skipping edited files, and selective reversal against a Git baseline. It will measure agent changes removed, human edits preserved, and conflicts requiring review.
