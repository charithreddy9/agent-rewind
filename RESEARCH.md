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

### Test gate from the actual pre-revert trees

We reused the same two projects and test selections, starting each gate run
from the parent of the maintainer's revert. We ran the public CLI on the full
original edit and separately ran its gate on just the previously selected
source file. Each gate copies the pre-revert tree before testing. The
single-file variant changes only that source file, so its tests and fixtures
remain at the pre-revert revision.

| Project | Full batch preview | Full batch test gate | Single-file test gate |
| --- | --- | --- | --- |
| pytest | 1 clean | Baseline failed with exit 4. Both selected test nodes were added by the revert. | Same missing-test outcome. Candidate not run. |
| Black | 7 clean, 2 conflicts | Skipped because the batch needed textual review. | Baseline passed 2/2. Candidate passed 0/2 with the pre-revert fixtures. |

The Black maintainer revert changed the expected output in the numeric
literal fixtures alongside the implementation. The single-file gate detected
disagreement with the old fixtures. The earlier maintainer-context replay
showed agreement with the new fixtures for those same two tests. These outcomes
measure different contracts. Neither establishes what a complete Black batch
would do after resolving its conflicts.

Run with the same environment as the targeted upstream replay:

```text
python -B behavior_replay.py ../rewind-sources --gate
```

The JSON includes full batch and single-file statuses, exit codes, and test
output. The replay command itself returns success when it produces the report,
including when the gate flags a candidate. It uses disposable local checkouts
and stages only the generated version stub when needed.

For a larger evaluation, freeze the revert list and select tests available in
the pre-revert tree before inspecting candidate results. Track unresolved
merges, missing tests, baseline failures, and fixture changes separately.
Report how many full batches are testable as well as the outcomes of the
testable batches. These two selected cases do not estimate either rate.

### Frozen ten-revert gate cohort

We included every distinct revert with at least one intervening file edit
in the expanded textual replay. The 15 eligible file cases map to 10 full
batches across Requests, pytest, Black, and HTTPX. The full-batch denominator
includes conflicts and setup failures. The cohort and exact test selectors
were fixed before running this evaluation and are listed in
[gate_cohort.py](gate_cohort.py). The earlier two targeted replays informed
the design, so those cases are not unseen validation data. The selectors
are a mix of behavior checks and smoke tests. The smoke tests for
documentation and tooling cases do not exercise the edited behavior.

| Project and revert | Full-batch result |
| --- | --- |
| Requests `09fd857e` | Candidate passed 2 selected tests |
| Requests `1fcda912` | Gate skipped after 1 merge conflict |
| Requests `b14584f3` | Baseline could not import `collections.MutableMapping` on Python 3.12 |
| pytest `6a47389c` | Candidate passed 1 existing skip test |
| pytest `7b6e477e` | Gate skipped after 3 merge conflicts and 1 unsupported file change |
| pytest `b3ed595f` | Baseline failed during startup |
| Black `b9ad4da2` | Candidate passed 1 formatting smoke test |
| Black `773e4a22` | Gate skipped after 2 merge conflicts |
| Black `394edc38` | Snapshot rejected the tracked symlink `docs/authors.md` |
| HTTPX `631ba976` | Baseline failed while loading test configuration |

Three of ten batches reached candidate execution, and all three passed their
selected checks. The other seven comprised three incomplete merge previews,
three baseline startup failures, and one unsupported snapshot. The existing
pytest skip test passed even though the maintainer's two new regression
tests exposed a `NameError` in the earlier source-file replay. This is a
concrete example of an existing check missing the behavior under study.
With only four passing test invocations across three candidates, these
results cannot estimate sensitivity to regressions or support a safety claim.

Run with Python 3.12, Git, full clones, and the pinned dependencies from the
targeted replay above. Add these packages for the initial cohort run:

```text
python -m pip install platformdirs==4.5.0 certifi==2025.10.5 hstspreload==2025.1.1 chardet==3.0.4 h11==0.9.0 h2==3.2.0 hpack==3.0.0 hyperframe==5.2.0 idna==2.10 rfc3986==1.5.0 sniffio==1.3.1 urllib3==1.26.20
python -B gate_cohort.py ../rewind-sources
```

The recorded environment used Python 3.12.14 and Git 2.51.1. A follow-up
reran the same frozen cases after adding `py==1.11.0`, `tomli==2.2.1`,
`trustme==1.2.1`, `cryptography==45.0.7`, `cffi==2.0.0`,
`pycparser==2.23`, and `uvicorn==0.30.6`. The category counts stayed
the same. The old pytest baseline then stopped on an AST deprecation
warning, and HTTPX progressed to a missing Trio dependency. Both runs retain
these as baseline failures. Each report includes the selected tests, batch
counts, and available test output.

### Labeled comparison of smoke and targeted checks

This controlled benchmark asks whether the gate can detect a known broken
rewind when the test command checks the affected behavior. It uses eight
synthetic cases arranged in four pairs. In each pair, the same agent edit is
reversed. The later configuration, source edit, or dependent file determines
whether the result still satisfies the declared contract.

| Contract | Broken rewind | Valid control |
| --- | --- | --- |
| Worker limits | Minimum exceeds the restored maximum | Minimum equals the restored maximum |
| Retry timing | Restored retry delay exceeds the new deadline | Restored retry delay remains within the deadline |
| Callable dependency | Restored function references a removed import | Import remains available |
| Consumer compatibility | Later consumer requires a field the rewind removes | Later consumer supplies a fallback for that field |

Each fixture declares its label before generating the candidate. All eight
candidates changed the target and merged without textual conflicts. The
smoke suite checks basic loading, import, or a preserved field. The targeted
suite adds one scenario-specific check while keeping the smoke check. Both
suites use the same production gate, which first runs the command on a
copy of the current files and then on a separate copy with the candidate.

| Suite | Broken candidates flagged | Valid candidates flagged | Baseline failures |
| --- | ---: | ---: | ---: |
| Smoke | 0/4 | 0/4 | 0/8 |
| Smoke plus targeted check | 4/4 | 0/4 | 0/8 |

The checks were written with knowledge of the seeded failures. The comparison
shows that the gate executes and reports these checks as intended. It does
not measure how reliably a developer or automated system could select a
useful check for an unfamiliar rewind. The valid labels apply only to the
specified fixture contracts. The eight cases share designs within pairs
and should not be treated as independent evidence of field performance.
The historical cohort remains a separate evaluation of full-batch coverage.

Run with Python and Git, using only the standard library and local files:

```text
python -B gate_benchmark.py
```

The JSON report includes the eight labels, the generated candidate text,
baseline and candidate exit codes, and output for each suite.

### One-check selection from the rewind diff

We reused the eight synthetic cases as development data. Each method could
run one check from the same three-entry pool: the smoke check, the existing
contract check from the previous experiment, and a generic working-directory
check. The fixed-order baseline always takes the first entry, the smoke check.
The two selectors count distinct identifier-shaped tokens shared between the
check body and the proposed diff. They use either changed lines alone or the
same lines with one adjacent line of context on each side. Ties use pool
order. The selectors receive the current and proposed file text and the check
bodies. They do not receive the fixture label, expected output, or results.
The selector sees only the changed file, so it does not inspect the separate
consumer module. The selected check runs through the production test gate.

| One-check method | Broken candidates flagged | Valid candidates flagged |
| --- | ---: | ---: |
| Fixed smoke-first order | 0/4 | 0/4 |
| Changed-line token overlap | 2/4 | 0/4 |
| Token overlap with one line of context | 3/4 | 0/4 |

All selected checks passed on their baselines. Changed lines contained the
configuration keys, so both overlap methods chose the two configuration
checks. One line of context added the enclosing function name and let the
selector pick the check that exposed the missing import. Both methods missed
the consumer failure. The smoke check shared the retained field name with the
diff, while the contract test called an indirect consumer and did not name
the removed field.

This is a development-set comparison. The pool was curated around the known
fixture contracts and the fixed order deliberately represents a smoke-first
workflow. The results do not estimate how either selector would perform on a
real test suite or on new cases. A follow-up should freeze the selector,
evaluate held-out changes, and compare against additional equal-budget
baselines before making claims about test selection quality.

```text
python -B gate_benchmark.py --select
```

The JSON includes each selected check, overlap terms, baseline and candidate
results, and labels for scoring.
