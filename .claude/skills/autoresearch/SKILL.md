---
name: autoresearch
description: Autonomous optimization loop for any measurable metric. Inspired by Karpathy
user_invocable: true
---

# autoresearch

Autonomous optimization of any measurable metric. Edit code, measure, keep or discard, repeat. You sleep - it works.

Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). Same core idea, generalized to anything.

## Invocation

```
/autoresearch
```

The skill runs in two modes:

**Interactive setup** (no existing config):
- Ask user what to optimize, collect the 4 required params
- Create `.autoresearch.yaml`, establish baseline, start looping

**Resume** (config exists):
- Read `.autoresearch.yaml` and `results.tsv`
- Continue from where the last session left off

## Setup Phase

Collect exactly 4 things from the user:

### 1. goal
What are we optimizing? Plain text.
```
"Minimize API response time"
"Maximize test coverage"
"Reduce bundle size"
"Lower validation loss"
```

### 2. files
Which files can you modify? Glob pattern or explicit list. Everything else is READ-ONLY.
```
"src/api/**/*.ts"
"train.py"
"src/pipeline.py, src/config.py"
```

### 3. metric_cmd
Shell command that outputs the metric. MUST print a number to stdout (last number in output is used).
```
"npm test -- --coverage 2>&1 | grep 'All files' | awk '{print $10}'"
"python train.py 2>&1 | grep '^val_bpb:' | awk '{print $2}'"
"curl -s localhost:3000/api/bench | jq '.p95_ms'"
"wc -l src/**/*.ts | tail -1 | awk '{print $1}'"
"du -sk dist/ | awk '{print $1}'"
```

### 4. direction
`lower` or `higher`. Lower = minimize (loss, latency, bundle size). Higher = maximize (coverage, throughput, score).

### Optional params

- **verify_cmd** - correctness check that must pass BEFORE measuring metric. Exit code 0 = pass. Default: none.
  ```
  "npm test"
  "python -m pytest tests/ -x -q"
  "make check"
  ```
- **timeout** - max seconds per experiment. Default: 300 (5 min).
- **max_experiments** - stop after N experiments. Default: unlimited.

### Config file

After collecting params, create `.autoresearch.yaml` in the project root:

```yaml
goal: "Minimize API response time p95"
files:
  - "src/api/**/*.ts"
metric_cmd: "npm run bench 2>&1 | grep p95 | awk '{print $2}'"
direction: lower
verify_cmd: "npm test"
timeout: 300
created: "2026-03-15T08:00:00"
tag: "mar15"
```

## Experiment Loop

### Before first experiment

1. **Create branch**: `git checkout -b autoresearch/<tag>` from current HEAD.
2. **Read in-scope files**: Read ALL files matching the `files` pattern. Understand the codebase fully.
3. **Read context**: README, package.json/pyproject.toml, any config files. Understand the project.
4. **Initialize results.tsv** with header row.
5. **Run baseline**: Execute metric_cmd WITHOUT changes. Record as first entry in results.tsv with status `baseline`.
6. **Confirm and go**: Show the user the baseline metric, confirm setup, start looping.

### The loop

```
LOOP:
  1. Review state: current metric, experiment history, what worked/failed
  2. Propose an idea (based on goal + history + code understanding)
  3. Edit the in-scope files
  4. git add <changed files> && git commit -m "autoresearch: <short description>"
  5. Run verify_cmd (if set). If FAIL → revert, log crash, goto 1
  6. Run metric_cmd > .autoresearch_run.log 2>&1. Apply timeout
  7. Extract metric (last number in output)
  8. If metric improved (respecting direction):
       → status=keep, advance branch (keep the commit)
  9. If metric same or worse:
       → status=discard, git reset --hard HEAD~1
  10. If crashed/timeout:
       → status=crash, git reset --hard HEAD~1
       → If trivial fix (typo, import), fix and retry ONCE
  11. Append to results.tsv
  12. Goto 1
```

### results.tsv format

Tab-separated (NOT commas). Untracked by git.

```
experiment	commit	metric	status	description
1	a1b2c3d	0.997900	baseline	initial measurement
2	b2c3d4e	0.993200	keep	increase learning rate to 0.04
3	c3d4e5f	1.005000	discard	switch to GeLU activation
4	d4e5f6g	0.000000	crash	double model width (OOM)
5	e5f6g7h	0.991000	keep	tune weight decay schedule
```

### Decision rules

**Keep** when:
- Metric improved in the right direction
- AND the change is not absurdly complex for a tiny gain

**Discard** when:
- Metric got worse
- Metric stayed the same (no point adding complexity for nothing)
- Improvement is negligible but adds significant complexity

**Simplicity criterion** (from Karpathy):
- All else being equal, simpler is better
- Small improvement + ugly complexity = not worth it
- Removing code + equal or better metric = great outcome (simplification win)
- Near-zero improvement but much simpler code = keep

### Strategy

Think like a researcher, not a monkey pressing buttons:

1. **Start broad**: Big architectural changes first. They have the highest potential impact.
2. **Read the history**: What worked? What didn't? Find patterns. If "increasing X" helped twice, try increasing it more.
3. **Combine near-misses**: If two discarded ideas each almost worked, try combining them.
4. **Try the opposite**: If your intuition says A, also try not-A. You might be wrong.
5. **Read the code deeply**: Often the best improvements come from noticing bugs, oversights, or suboptimal defaults - not from clever new ideas.
6. **Don't repeat yourself**: Never try the exact same thing twice. Check results.tsv.
7. **When stuck**: Re-read all files. Try more radical changes. Look for things that "everyone knows" but nobody tested.

### NEVER STOP

Once the loop begins, do NOT pause to ask the user if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The user may be asleep or away. You are autonomous. The loop runs until:
- You hit max_experiments (if set)
- The user manually interrupts you
- You genuinely cannot think of anything new (this should be rare - think harder)

If you run out of ideas:
- Re-read in-scope files for new angles
- Try combining previous near-misses
- Try more radical changes
- Read project docs/README for hints
- Try simplifying (removing code can improve metrics)

### Crash handling

- Trivial crash (typo, missing import, syntax error): fix and retry once
- Fundamental crash (OOM, design flaw): log as crash, revert, move on
- 3+ consecutive crashes: step back, try a completely different approach
- Never spend more than 2 attempts fixing the same crash

### Progress reporting

Every 10 experiments, output a brief progress summary:

```
--- autoresearch progress (10/∞) ---
baseline: 0.9979
current best: 0.9810 (-1.69%)
experiments: 10 (6 keep, 3 discard, 1 crash)
top improvements:
  #2: increase LR to 0.04 (-0.47%)
  #5: tune weight decay (-0.30%)
  #8: sharpen attention scaling (-0.52%)
---
```

## Examples

### Optimize test coverage
```yaml
goal: "Maximize test coverage to 90%+"
files: ["src/**/*.test.ts"]
metric_cmd: "npm test -- --coverage 2>&1 | grep 'All files' | awk '{print $10}'"
direction: higher
verify_cmd: "npm test"
```

### Reduce Docker image size
```yaml
goal: "Minimize Docker image size"
files: ["Dockerfile", "docker-compose.yml", ".dockerignore"]
metric_cmd: "docker build -t test . 2>&1 && docker image inspect test --format '{{.Size}}' | awk '{print $1/1048576}'"
direction: lower
```

### Optimize Python script performance
```yaml
goal: "Minimize execution time of data pipeline"
files: ["pipeline.py", "utils.py"]
metric_cmd: "python -c 'import time; t=time.time(); exec(open(\"pipeline.py\").read()); print(time.time()-t)'"
direction: lower
verify_cmd: "python -m pytest tests/ -x -q"
```

### Optimize prompt quality
```yaml
goal: "Maximize LLM eval score on test cases"
files: ["prompts/*.md", "agent.py"]
metric_cmd: "python run_eval.py 2>&1 | grep 'avg_score' | awk '{print $2}'"
direction: higher
```

### Reduce API latency
```yaml
goal: "Minimize p95 API response time"
files: ["src/api/**/*.ts"]
metric_cmd: "npm run bench 2>&1 | grep 'p95' | awk '{print $2}'"
direction: lower
verify_cmd: "npm test"
```

## Key differences from Karpathy's original

| Aspect | Karpathy | This skill |
|--------|----------|------------|
| Scope | ML training (train.py) | Anything measurable |
| Metric | val_bpb only | Any shell command output |
| Files | Single file | Any glob pattern |
| Direction | Always lower | lower or higher |
| Platform | NVIDIA GPU required | Any environment |
| Verify | Implicit (crash = fail) | Explicit verify_cmd |
| Config | Hardcoded in program.md | .autoresearch.yaml |

## Design philosophy

This is Karpathy's core insight: **you don't program the code, you program the research org.** The `.autoresearch.yaml` + this skill = your autonomous researcher. The researcher edits code, you edit the researcher.

The beauty is in the constraints:
- **Fixed evaluation** = fair comparison across experiments
- **Git-based state** = perfect undo, full history, resumable
- **One metric** = no ambiguity about what "better" means
- **Simplicity criterion** = prevents complexity creep

*"Any metric you care about that is reasonably efficient to evaluate can be autoresearched by an agent swarm."* - @karpathy
