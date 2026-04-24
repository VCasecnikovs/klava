---
name: verify
description: Verify code changes actually work by running the app, tests, or scripts
user_invocable: true
---

# Verify

After code changes, verify they actually work. Not just "looks right" - actually run it.

## When to Use

- User calls `/verify` (optionally with args describing what to verify)
- After implementing a feature, fix, or refactor
- When you want to prove something works before committing

## Args

Optional free-text describing what to verify. Examples:
- `/verify` - auto-detect from recent changes
- `/verify the server starts and /health returns 200`
- `/verify tests pass for the auth module`
- `/verify the script outputs valid JSON`

## Flow

### Step 1: Identify What Changed

Check what was modified to understand what needs verification:

```bash
git diff --stat HEAD  # unstaged changes
git diff --cached --stat  # staged changes
git log --oneline -3  # recent commits if nothing staged
```

If args were provided, use those as the verification target instead of inferring from diff.

### Step 2: Determine Verification Strategy

Based on the changes, pick the right approach:

| What changed | How to verify |
|---|---|
| **CLI app / script** | Run it with expected args, check exit code + output |
| **Web server / API** | Start server in background, curl endpoints, check responses, kill server |
| **Test files** | Run the test suite (pytest, jest, go test, cargo test, etc.) |
| **Library / module** | Run existing tests, or write a quick smoke test inline |
| **Config files** | Validate syntax (yaml lint, json parse, toml check) |
| **Build system** | Run the build, check it succeeds |
| **Frontend** | Build, check for errors. If dev server, start and check it loads |
| **Python** | `python3 -c "import module"` or run the script |
| **Shell script** | `bash -n script.sh` for syntax, then run it |

Detect the project type from files present:
- `package.json` -> Node/npm/yarn
- `Cargo.toml` -> Rust
- `go.mod` -> Go
- `pyproject.toml` / `setup.py` / `requirements.txt` -> Python
- `Makefile` -> make
- `Gemfile` -> Ruby

### Step 3: Run Verification

Execute the verification. Key rules:

- **Set timeouts.** Don't let a server run forever. 30s max for most checks
- **Capture output.** Always capture stdout + stderr for the report
- **Check exit codes.** Non-zero = fail, period
- **For servers:** Start in background, wait 2-3s, hit endpoint, then kill. Clean up after
- **For tests:** Run the specific tests related to changes, not the entire suite (unless it's fast)
- **Don't swallow errors.** If something fails, show the full output

Server verification pattern:
```bash
# Start in background
command &
SERVER_PID=$!
sleep 3

# Verify
curl -sf http://localhost:PORT/endpoint
RESULT=$?

# Cleanup
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null

exit $RESULT
```

### Step 4: Report

Be honest. Two outcomes:

**PASS** - State what was verified and what the output was. Keep it short.
```
Verified: server starts on :8080, GET /health returns {"status":"ok"} (200)
```

**FAIL** - State what failed, show the relevant error output. Don't sugar-coat it.
```
FAILED: pytest returned exit code 1
  FAILED tests/test_auth.py::test_login_expired_token - AssertionError: expected 401, got 500
  1 failed, 23 passed
```

If FAIL: suggest what might be wrong based on the error output.

## Common Pitfalls

- Don't verify by re-reading the code. That's review, not verification. Run it
- Don't skip verification because "it's a small change." Small changes break things
- Don't forget cleanup - background processes, temp files, test databases
- If the project has no test infrastructure and no runnable entry point, say so honestly rather than faking a verification
