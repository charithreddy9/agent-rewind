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

## External replay against recorded maintainer reverts

The external replay uses the Git histories of [Requests](https://github.com/psf/requests), [Flask](https://github.com/pallets/flask), and [Click](https://github.com/pallets/click). The script pins a history tip for each project and inspects up to the 12 newest first-parent commits with Git's standard revert marker. It includes only reverts with exactly one recorded target, where both commits have one parent and the target is an ancestor of the revert's parent. It takes the intersection of same-mode regular text files modified by both commits. Missing targets, non-UTF-8 blobs, binary blobs with NUL bytes, renames, additions, and deletions are outside this sample.

For each eligible file, the inputs are the target's parent, the target itself, and the revert's parent. The reference is the maintainer's committed file in the revert. An intervening edit means that the file blob in the revert's parent differs from the target's output. Exact results match the recorded revert byte for byte. Review means the tool emitted a textual conflict. An exact match checks agreement with the maintainer's choice for that file. No application tests or configuration rules are used in this replay.

| Strategy | Exact with intervening edits | Review with intervening edits | Exact without intervening edits |
| --- | ---: | ---: | ---: |
| Full restore | 0/3 | 0/3 | 10/10 |
| Skip files edited later | 0/3 | 0/3 | 10/10 |
| Git selective reversal | 2/3 | 1/3 | 10/10 |

Both exact matches with intervening edits were in Requests, at reverts `09fd857e` and `b14584f3`. The third Requests case, `1fcda912` on `docs/user/advanced.rst`, needs review. Flask and Click contribute unchanged-since-target controls only. All three strategies matched the maintainer in those controls.

The labels come from actual maintainer commits, and both the original and intervening changes are historical. These histories do not identify agent-authored edits. Git may also have produced the recorded reverts, so agreement measures reproduction of a maintenance outcome, not an independent semantic judgment. The selection favors reverts with explicit Git markers and common supported file changes. The three intervening-edit cases all come from one project, which limits generalization.

### Reproduce the external replay

From the Agent Rewind directory, use full local clones in a separate folder. The script reads Git objects and leaves the checkouts untouched.

```powershell
git clone --no-checkout https://github.com/psf/requests.git ../rewind-sources/requests
git clone --no-checkout https://github.com/pallets/flask.git ../rewind-sources/flask
git clone --no-checkout https://github.com/pallets/click.git ../rewind-sources/click
python external_history.py ../rewind-sources
```

The recorded run used Git 2.51.1 and Python 3.12.14. The script prints each case, the revert identifier, and aggregate counts. The corpus is referenced by commit IDs, so the Agent Rewind repository does not copy upstream source files.

### Expanded replay

The expanded run adds [pytest](https://github.com/pytest-dev/pytest), [Black](https://github.com/psf/black), [HTTPX](https://github.com/encode/httpx), and [Rich](https://github.com/Textualize/rich) using the same selection and scoring rules. All eligible file cases from the pinned windows are included. Rich yielded no eligible files. The table counts file cases, so multiple files from one revert are related observations.

| Project | Intervening edits | Selective exact | Selective review | Selective different |
| --- | ---: | ---: | ---: | ---: |
| Requests | 3 | 2 | 1 | 0 |
| pytest | 6 | 2 | 3 | 1 |
| Black | 5 | 3 | 0 | 2 |
| HTTPX | 1 | 1 | 0 | 0 |
| **Total** | **15** | **8** | **4** | **3** |

Full restore and skip-edited each matched zero of the 15 cases with intervening edits. All three strategies matched all 28 cases without intervening edits.

A clean but different result means the tool produced text that did not match the recorded revert. It does not by itself identify a broken candidate. For example, the recorded Black revert `b9ad4da2` added a changelog entry about the revert that an inverse patch would have no basis to generate. The other differences were in `src/_pytest/unittest.py` at `6a47389c` and `src/black/__init__.py` at `773e4a22`. They contain code differences, so byte agreement alone cannot establish whether the alternative is behaviorally correct.

Use the original three clones and add:

```powershell
git clone --no-checkout https://github.com/pytest-dev/pytest.git ../rewind-sources/pytest
git clone --no-checkout https://github.com/psf/black.git ../rewind-sources/black
git clone --no-checkout https://github.com/encode/httpx.git ../rewind-sources/httpx
git clone --no-checkout https://github.com/Textualize/rich.git ../rewind-sources/rich
python external_history.py ../rewind-sources --expanded
```

### Targeted upstream tests on the two code differences

We replayed the two clean, byte-different code files against the upstream tests most directly associated with each revert. Each run starts from a fresh archive of the maintainer's revert commit. We substitute only the target file with the Agent Rewind candidate or the file from immediately before the revert. The pre-revert file is a negative control. All other source and test files stay at the maintainer's revision, so this is a single-file experiment in a fixed context.

| Upstream revert and selected behavior | Maintainer | Agent Rewind | Pre-revert file |
| --- | ---: | ---: | ---: |
| [pytest `6a47389c`](https://github.com/pytest-dev/pytest/commit/6a47389c7813ec7ed395c0279c4b7685fde9f95a), unittest skip handling | 2/2 passed | 0/2 passed | 0/2 passed |
| [Black `773e4a22`](https://github.com/psf/black/commit/773e4a22d58be1f1aa82df7ad9a0f4c4e1328c10), numeric literal formatting | 2/2 passed | 2/2 passed | 0/2 passed |

The pytest candidate called `pytest.skip` after the module-level `pytest` import had been removed. Both tests exposed a `NameError`. The maintainer used the directly imported `skip` function. The pre-revert file instead surfaced `unittest.SkipTest` as an error or failure. The Black candidate agreed with the maintainer on the two tested numeric formatting behaviors despite different implementation text.

The pytest result demonstrates a behavioral regression in a rewind that had no textual conflict. The Black result provides limited evidence for the specific behaviors tested. Both code cases were selected after the textual comparison. Four upstream tests across two files cannot estimate a general regression rate or establish behavioral equivalence. The original upstream edits are a proxy for agent changes.

Reproduce with Python 3.12, Git, and the full pytest and Black clones from the expanded replay. Run the archived upstream code in a disposable environment. Each variant uses a fresh process with third-party pytest plugin autoload disabled. The runner supplies fixed placeholders for build-generated version modules missing from the archives.

```text
python -m pip install pluggy==1.6.0 iniconfig==2.3.0 packaging==26.0 pygments==2.19.2 attrs==25.4.0 pytest==8.4.2 click==8.0.4 appdirs==1.4.4 toml==0.10.2 regex==2025.11.3 pathspec==0.12.1 mypy-extensions==1.1.0
python -B behavior_replay.py ../rewind-sources
```

The recorded replay used Python 3.12.14 and Git 2.51.1.
