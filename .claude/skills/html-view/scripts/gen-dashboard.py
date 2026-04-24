#!/usr/bin/env python3
"""Generate dashboard HTML listing all claude-view files."""
import os
import re
import glob
from datetime import datetime

VIEWS_DIR = os.path.expanduser(
    os.environ.get(
        "HTML_VIEWS_DIR",
        os.path.join(os.environ.get("OBSIDIAN_VAULT", "~/Documents/MyBrain"), "Views"),
    )
)


def get_title(filepath):
    """Extract <title> from HTML file."""
    try:
        with open(filepath, "r") as f:
            content = f.read(3000)
        m = re.search(r"<title>(.*?)</title>", content)
        return m.group(1) if m else os.path.basename(filepath)
    except Exception:
        return os.path.basename(filepath)


def generate():
    os.makedirs(VIEWS_DIR, exist_ok=True)

    # Collect all HTML files except dashboard itself
    files = sorted(glob.glob(f"{VIEWS_DIR}/*.html"), key=os.path.getmtime, reverse=True)
    files = [f for f in files if not os.path.basename(f).startswith("dashboard")]

    cards = ""
    for f in files:
        title = get_title(f)
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        size = os.path.getsize(f)
        fname = os.path.basename(f)
        cards += f"""
        <a href="{fname}" class="view-card">
          <div class="view-title">{title}</div>
          <div class="view-meta">{mtime.strftime('%Y-%m-%d %H:%M')} &middot; {size // 1024}KB</div>
        </a>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Views Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #fafafa;
    color: #1a1a1a;
    line-height: 1.6;
    padding: 2rem;
    max-width: 1000px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.75rem;
    font-weight: 600;
    margin-bottom: 0.25rem;
    color: #111;
  }}
  .subtitle {{
    color: #888;
    font-size: 0.85rem;
    margin-bottom: 2rem;
  }}
  .views-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 0.75rem;
  }}
  .view-card {{
    display: block;
    background: #fff;
    border: 1px solid #e8e8e8;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    text-decoration: none;
    color: inherit;
    transition: all 0.15s;
  }}
  .view-card:hover {{
    border-color: #bbb;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    transform: translateY(-1px);
  }}
  .view-title {{
    font-weight: 600;
    font-size: 0.95rem;
    margin-bottom: 0.25rem;
    color: #111;
  }}
  .view-meta {{
    font-size: 0.8rem;
    color: #999;
  }}
  .empty {{
    text-align: center;
    color: #999;
    padding: 4rem;
    font-size: 0.95rem;
  }}
</style>
</head>
<body>
  <h1>Claude Views</h1>
  <div class="subtitle">{len(files)} view{"s" if len(files) != 1 else ""} &middot; Updated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

  <div class="views-grid">
    {cards if cards else '<div class="empty">No views yet. Use html-view skill to generate one.</div>'}
  </div>
</body>
</html>"""

    out_path = os.path.join(VIEWS_DIR, "dashboard.html")
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Dashboard: {out_path} ({len(files)} views)")
    return out_path


if __name__ == "__main__":
    generate()
