# When a clean rewind still needs review

Agent Rewind v0.1 is a small, reproducible study of undoing an agent edit after a human has edited the same file. It asks whether a supplied configuration rule can catch a bad candidate that a textual merge treats as clean.

## Method

Each fixture has three snapshots: the file before the agent, immediately after the agent, and after the human. All four strategies receive the same snapshots.

1. **Full restore** returns the before snapshot.
2. **Skip edited** restores the before snapshot if the current file still matches the agent's output. Otherwise it keeps the current file.
3. **Git selective reversal** calls `git merge-file` with the current file, the after-agent snapshot as the base, and the before-agent snapshot as the other input.
4. **Git with rules** uses the same candidate and checks the configured top-level JSON numeric pairs after a successful textual merge. The benchmark uses the same checker as the CLI.

The 12 hand-written fixtures include nine cases with an exact expected text and three that require review. The review cases are a same-line overlap and two configuration dependencies. Exact means byte-equivalent UTF-8 text in these fixtures. We also record unnecessary review, missed review, and candidates that violate a fixture's independently expressed validity check.

Reproduce from the project root with `python benchmark.py` and `python -m unittest -v`. The recorded run used Git 2.51.1 and Python 3.12.14. The benchmark uses fixed inputs, requires no model calls, and prints each case result.

## Observed results

| Strategy | Exact | Wrong text | Extra review | Correct review | Missed review | Invalid candidate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full restore | 1 | 8 | 0 | 0 | 3 | 0 |
| Skip edited | 2 | 7 | 0 | 0 | 3 | 0 |
| Git selective reversal | 8 | 0 | 1 | 1 | 0 | 2 |
| Git with supplied rules | 8 | 0 | 1 | 3 | 0 | 0 |

The worker example retains the human's minimum of 6 while reverting the maximum from 8 to 4. The retry example retains a 30 ms deadline while reverting the retry delay from 20 ms to 50 ms. Git returns clean text in both cases. The rules flag both invalid candidates for review. Two matched valid examples check that the same rules permit equality and a delay that still fits the deadline.

The adjacent-line fixture produces a textual conflict even though its expected answer can preserve both changes. Adding rules does not resolve that conflict.

## Prior work and scope

[Git's merge-file documentation](https://git-scm.com/docs/git-merge-file) describes the three-input merge primitive. Agent Rewind uses that primitive as its baseline and as its rollback engine. [Hermes Agent's rollback documentation](https://hermes-agent.nousresearch.com/docs/user-guide/checkpoints-and-rollback) describes preserving later human edits by skipping changed files. The benchmark's skip strategy models that one decision in isolation. It does not execute or measure Hermes.

[Verified Three-Way Program Merge](https://www.microsoft.com/en-us/research/publication/verified-three-way-program-merge/) studies semantic conflict freedom in program merges. Agent Rewind's checks cover explicitly supplied numeric relations in individual JSON files. [UndoBench](https://github.com/tradertanmay/undobench) studies operational agent recovery, including failures around tool-side effects. This project evaluates text-file recovery and configuration checks.

The two dependency cases were designed around rules supplied to the tool. The result demonstrates those rules firing in a controlled setting. It does not estimate how often unsafe rewinds occur or how well the approach generalizes to real projects. It cannot discover missing rules, check cross-file behavior, or reverse external side effects. The next research step would be an independently labeled corpus of real edit sequences and rules derived from each project's existing tests or documented constraints.

## Replay on the project's Git history

A second evaluation uses four existing commits from this repository: the output flag, JSON reporting, the demo documentation, and a benchmark change. The script pins each full commit ID and reads the file before and after that commit. For each patch, it simulates three later edits: prepend a note, append a note, or edit one line introduced by the selected commit. The expected result for the first two cases is the before snapshot with the same note. The overlapping case requires review.

| Strategy | Exact results out of 8 note cases | Review flags out of 4 overlap cases |
| --- | ---: | ---: |
| Full restore | 0/8 | 0/4 |
| Skip files edited later | 0/8 | 0/4 |
| Git selective reversal | 8/8 | 4/4 |

Run `python history_benchmark.py` from a full clone. The recorded run used Git 2.51.1 and Python 3.12.14. The replay reads committed file versions and evaluates in memory.

The patches are real. The later edits and expected outcomes are scripted. Three file paths in one project and four commit selections give this replay narrow coverage. The two note positions model easy separable edits, and all overlap cases were selected to touch an agent-introduced line. The replay measures textual rollback only. It does not estimate the frequency of conflicts in developer workflows or evaluate semantic validation on external repositories.
