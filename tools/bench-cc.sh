#!/bin/bash
# Benchmark: Full CC vs Stripped CC latency
# Run OUTSIDE of Claude Code session!
unset CLAUDECODE

PROMPT="ответь одним словом: да"
RUNS=3

bench() {
    local label="$1"; shift
    local total=0
    local tokens=""

    echo "=== $label ==="
    for i in $(seq 1 $RUNS); do
        START=$(python3 -c "import time; print(time.time())")
        RESULT=$(claude -p --no-session-persistence --max-turns 1 --output-format json "$@" "$PROMPT" 2>/dev/null)
        END=$(python3 -c "import time; print(time.time())")
        DUR=$(python3 -c "print(f'{$END - $START:.2f}')")
        total=$(python3 -c "print($total + $END - $START)")

        if [ $i -eq 1 ]; then
            tokens=$(echo "$RESULT" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    u=d.get('usage',{})
    print(f'in={u.get(\"input_tokens\",\"?\")}, out={u.get(\"output_tokens\",\"?\")}')
except: print('?')
" 2>/dev/null)
        fi
        echo "  Run $i: ${DUR}s"
    done
    AVG=$(python3 -c "print(f'{$total / $RUNS:.2f}')")
    echo "  Avg: ${AVG}s | Tokens: $tokens"
    echo ""
}

echo "Claude Code Latency Benchmark"
echo "Prompt: \"$PROMPT\""
echo "Runs per test: $RUNS"
echo "================================"
echo ""

# Test 1: Full CC default (opus)
bench "1. Full CC (opus, all tools, full system prompt)"

# Test 2: Stripped (opus)
bench "2. Stripped (opus, no tools, minimal prompt)" \
    --system-prompt "Отвечай одним словом" --tools ""

# Test 3: Full CC (sonnet)
bench "3. Full CC (sonnet)" --model sonnet

# Test 4: Stripped (sonnet)
bench "4. Stripped (sonnet, no tools, minimal prompt)" \
    --system-prompt "Отвечай одним словом" --tools "" --model sonnet

# Test 5: Stripped (haiku)
bench "5. Stripped (haiku, no tools, minimal prompt)" \
    --system-prompt "Отвечай одним словом" --tools "" --model haiku

# Test 6: Stripped + disable skills
bench "6. Ultra-stripped (sonnet, no tools, no skills, minimal prompt)" \
    --system-prompt "Отвечай одним словом" --tools "" --disable-slash-commands --model sonnet

echo "================================"
echo "Done! Compare Avg times and token counts."
echo "Lower input tokens = less system prompt overhead."
