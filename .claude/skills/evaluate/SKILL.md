---
name: evaluate
description: Review agent execution steps with structured feedback. Use when user says evaluate, review steps, or is not satisfied with the result.
user_invocable: true
---

# Evaluate Skill

Interactive step-by-step review of agent's execution. Creates an HTML page where the user sees what the agent did at each step of the Agent Execution Loop and can write targeted feedback.

## When to Use

- User calls `/evaluate`
- User is not satisfied with a result and wants to give precise feedback
- After a complex task where the user wants to review the execution path

Do NOT use after every task - only when evaluation is needed.

## Flow

1. Reflect on your actions in the current session
2. For each step (MATCH, THINK, ACT, VERIFY, LEARN) write what you did
3. Generate HTML with embedded data
4. Open in browser
5. User writes comments next to each step, clicks "Copy Feedback"
6. User pastes feedback in chat
7. Agent parses feedback per step and applies fixes (update skill, retry, etc.)

## Step 1: Reflect

Analyze the current session and fill in each step honestly:

- **MATCH**: Which skill was chosen? Why? Or why none matched?
- **THINK**: What was the expected result? What verification criteria were defined?
- **ACT**: Which tools were called? In what order? What was parallel vs sequential?
- **VERIFY**: What was checked? Did it pass or fail? Any skill audit issues?
- **LEARN**: Was anything updated? If not, why?

Be specific - include file paths, tool names, actual values. The user needs to see exactly what happened.

## Step 2: Generate HTML

Write a self-contained HTML file to `/tmp/evaluate-{timestamp}.html` with the data embedded inline. Use the template below.

Replace `__TASK_DESCRIPTION__` and each `__STEP_*__` placeholder with actual content from your reflection. Use HTML-safe text (escape `<`, `>`, `&`).

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evaluate - Step Review</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    line-height: 1.6;
    min-height: 100vh;
  }

  .header {
    padding: 1.5rem 2rem;
    border-bottom: 1px solid #2a2a4a;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .header h1 {
    font-size: 1.4rem;
    font-weight: 600;
    color: #fff;
  }

  .header .task-label {
    font-size: 0.85rem;
    color: #888;
    margin-top: 0.25rem;
  }

  .copy-btn {
    background: #6c5ce7;
    color: #fff;
    border: none;
    padding: 0.6rem 1.5rem;
    border-radius: 6px;
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
  }

  .copy-btn:hover { background: #5a4bd1; }
  .copy-btn.copied { background: #27ae60; }

  .container {
    padding: 1.5rem 2rem;
    max-width: 1400px;
    margin: 0 auto;
  }

  .step {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .step-card {
    background: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 1.25rem;
  }

  .step-label {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    margin-bottom: 0.75rem;
  }

  .step-match .step-label  { background: #2d3a8c; color: #8b9cf7; }
  .step-think .step-label  { background: #1a5c3a; color: #6bcf8e; }
  .step-act .step-label    { background: #8c5a2d; color: #f7c98b; }
  .step-verify .step-label { background: #5c1a5c; color: #cf6bcf; }
  .step-learn .step-label  { background: #1a4a5c; color: #6bb8cf; }

  .step-content {
    font-size: 0.9rem;
    color: #c0c0c0;
    white-space: pre-wrap;
  }

  .feedback-card {
    background: #1e1e3a;
    border: 1px solid #3a3a5a;
    border-radius: 8px;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
  }

  .feedback-card label {
    font-size: 0.75rem;
    color: #888;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.5rem;
  }

  .feedback-card textarea {
    flex: 1;
    min-height: 80px;
    background: #12122a;
    border: 1px solid #2a2a4a;
    border-radius: 6px;
    color: #e0e0e0;
    font-family: inherit;
    font-size: 0.9rem;
    padding: 0.75rem;
    resize: vertical;
    line-height: 1.5;
  }

  .feedback-card textarea:focus {
    outline: none;
    border-color: #6c5ce7;
  }

  .feedback-card textarea::placeholder {
    color: #555;
  }

  @media (max-width: 900px) {
    .step { grid-template-columns: 1fr; }
    .container { padding: 1rem; }
  }
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>Evaluate - Step Review</h1>
      <div class="task-label">__TASK_DESCRIPTION__</div>
    </div>
    <button class="copy-btn" onclick="copyFeedback()">Copy Feedback</button>
  </div>

  <div class="container">
    <div class="step step-match">
      <div class="step-card">
        <div class="step-label">1. Match</div>
        <div class="step-content">__STEP_MATCH__</div>
      </div>
      <div class="feedback-card">
        <label>Your feedback on MATCH</label>
        <textarea id="fb-match" placeholder="Was the right skill chosen? Should a different one be used?"></textarea>
      </div>
    </div>

    <div class="step step-think">
      <div class="step-card">
        <div class="step-label">2. Think</div>
        <div class="step-content">__STEP_THINK__</div>
      </div>
      <div class="feedback-card">
        <label>Your feedback on THINK</label>
        <textarea id="fb-think" placeholder="Was the expected result correct? Were verification criteria good?"></textarea>
      </div>
    </div>

    <div class="step step-act">
      <div class="step-card">
        <div class="step-label">3. Act</div>
        <div class="step-content">__STEP_ACT__</div>
      </div>
      <div class="feedback-card">
        <label>Your feedback on ACT</label>
        <textarea id="fb-act" placeholder="Were the right tools used? Correct order? Missing steps?"></textarea>
      </div>
    </div>

    <div class="step step-verify">
      <div class="step-card">
        <div class="step-label">4. Verify</div>
        <div class="step-content">__STEP_VERIFY__</div>
      </div>
      <div class="feedback-card">
        <label>Your feedback on VERIFY</label>
        <textarea id="fb-verify" placeholder="Was verification thorough? Missed checks?"></textarea>
      </div>
    </div>

    <div class="step step-learn">
      <div class="step-card">
        <div class="step-label">5. Learn</div>
        <div class="step-content">__STEP_LEARN__</div>
      </div>
      <div class="feedback-card">
        <label>Your feedback on LEARN</label>
        <textarea id="fb-learn" placeholder="Should something be updated? Skill, CLAUDE.md, memory?"></textarea>
      </div>
    </div>
  </div>

<script>
function copyFeedback() {
  const steps = ['match', 'think', 'act', 'verify', 'learn'];
  const labels = { match: 'MATCH', think: 'THINK', act: 'ACT', verify: 'VERIFY', learn: 'LEARN' };

  let output = '## Evaluation Feedback\n';
  let hasAny = false;

  for (const step of steps) {
    const agentEl = document.querySelector(`.step-${step} .step-content`);
    const fbEl = document.getElementById(`fb-${step}`);
    const feedback = fbEl.value.trim();

    if (feedback) {
      hasAny = true;
      output += `\n### ${labels[step]}\n`;
      output += `**Agent:** ${agentEl.textContent.trim()}\n`;
      output += `**Feedback:** ${feedback}\n`;
    }
  }

  if (!hasAny) {
    output += '\nNo feedback provided - all steps OK.\n';
  }

  navigator.clipboard.writeText(output).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = 'Copy Feedback';
      btn.classList.remove('copied');
    }, 2000);
  });
}
</script>
</body>
</html>
```

## Step 3: Open in Browser

```bash
open /tmp/evaluate-{timestamp}.html
```

Tell the user: "Открыл Evaluate в браузере. Напиши комментарии к шагам которые не понравились, нажми Copy Feedback и вставь сюда."

## Step 4: Parse and Fix Feedback

When the user pastes feedback back (format: `## Evaluation Feedback` with `### STEP_NAME` sections), parse each step:

1. Read each `**Feedback:**` line
2. Determine what needs fixing:
   - MATCH feedback -> update skill frontmatter description or CLAUDE.md skill matching rules
   - THINK feedback -> update skill instructions (expected result, verification criteria)
   - ACT feedback -> update skill steps, tool usage, order of operations
   - VERIFY feedback -> add/update verification checks in skill
   - LEARN feedback -> update skill Known Issues, add prevention rules
3. Apply the fix to the appropriate file
4. Git commit: `evaluate: {skill} - {what changed}`
5. If the task needs re-execution, re-run through the Agent Execution Loop

## Known Issues

- Browser clipboard API requires HTTPS or localhost - if clipboard fails, user can manually select all text from the output area
