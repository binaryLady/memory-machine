#!/usr/bin/env python3
"""Render COMMANDS.md as the memory-machine Field Manual page.

The published page is an Artifact, which is a copy of this repository's
documentation rather than a rendering of it — so it drifts unless regenerated.
This script is how it gets regenerated, and why the drift stays bounded.

    python3 scripts/render_manual.py            # writes build/field-manual.html
    python3 scripts/render_manual.py --out FILE

Only the subset of Markdown that COMMANDS.md actually uses is supported:
headings, fenced code, tables, bullets, and inline bold, code and links. It is
deliberately not a general Markdown implementation — a dependency-free script
that handles this one file beats pulling a parser into a Debian package.
"""
from __future__ import annotations

import argparse
import html as H
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Sections are grouped by what the reader is doing, not by their order in the
# file: this is a reference, and numbering would imply a sequence nobody reads
# it in. A section missing from the source is simply left out of the rail.
GROUPS = {
    "Setup": [
        "Getting started", "Media", "A DSI panel", "The heartbeat panel",
        "Multiple screens", "Config",
    ],
    "Running": [
        "Every command at a glance", "Quick tips", "Service control",
        "Status and logs", "Testing without the headphone sensor", "Updating",
        "Development (laptop)",
    ],
    "When something's wrong": ["Troubleshooting"],
}

PREAMBLE = (
    "<p>Everything you need to run, inspect, and change the installation. "
    "Commands run on the Pi unless marked <strong>(laptop)</strong>.</p>"
)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def inline(text: str) -> str:
    """Escape, then re-introduce the inline markup COMMANDS.md uses."""
    text = H.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def render_markdown(source: str) -> tuple[str, list[str]]:
    """Return the article HTML and the list of top-level section titles."""
    lines = source.splitlines()
    out: list[str] = []
    titles: list[str] = []
    para: list[str] = []
    bullets: list[str] = []
    table: list[str] = []

    def flush_para() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def flush_bullets() -> None:
        if bullets:
            items = "".join(f"<li>{inline(b)}</li>" for b in bullets)
            out.append(f"<ul>{items}</ul>")
            bullets.clear()

    def flush_table() -> None:
        if not table:
            return
        header, *rest = table
        body = [r for r in rest if not set(r.replace("|", "").strip()) <= set("- :")]
        def cells(row: str) -> list[str]:
            return [c.strip() for c in row.strip().strip("|").split("|")]
        head = "".join(f"<th>{inline(c)}</th>" for c in cells(header))
        rows = "".join(
            "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>"
            for r in body
        )
        out.append(
            '<div class="scroller"><table><thead><tr>'
            f"{head}</tr></thead><tbody>{rows}</tbody></table></div>"
        )
        table.clear()

    def flush_all() -> None:
        flush_para()
        flush_bullets()
        flush_table()

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            flush_all()
            lang = line[3:].strip()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            body = H.escape("\n".join(code))
            # Only shell blocks get a copy button: the reader is at a terminal,
            # and config snippets are edited rather than pasted.
            css_class = "cmd" if lang == "bash" else "block"
            button = '<button class="copy" type="button">Copy</button>' if lang == "bash" else ""
            out.append(f'<figure class="{css_class}">{button}<pre><code>{body}</code></pre></figure>')
            i += 1
            continue

        if line.startswith("## "):
            flush_all()
            title = re.sub(r"\*\*(.+?)\*\*", r"\1", line[3:].strip())
            titles.append(title)
            out.append(f'<h2 id="{slug(title)}">{H.escape(title)}</h2>')
            i += 1
            continue

        if line.startswith("### "):
            flush_all()
            title = line[4:].strip()
            out.append(f'<h3 id="{slug(title)}">{inline(title)}</h3>')
            i += 1
            continue

        if line.startswith("|"):
            flush_para()
            flush_bullets()
            table.append(line)
            i += 1
            continue

        if line.startswith("- "):
            flush_para()
            flush_table()
            bullets.append(line[2:])
            i += 1
            continue

        if line.strip() == "---" or not line.strip():
            flush_all()
            i += 1
            continue

        if bullets:
            # A wrapped continuation of the bullet above it.
            bullets[-1] += " " + line.strip()
        else:
            flush_table()
            para.append(line.strip())
        i += 1

    flush_all()
    return "\n".join(out), titles


def render_nav(titles: list[str]) -> str:
    groups = []
    for group, section_titles in GROUPS.items():
        links = "".join(
            f'<li><a href="#{slug(t)}">{H.escape(t)}</a></li>'
            for t in section_titles
            if t in titles
        )
        groups.append(f'<div class="navgroup"><h4>{H.escape(group)}</h4><ul>{links}</ul></div>')
    return "\n".join(groups)


def render(source: str) -> str:
    article, titles = render_markdown(source)
    # The standfirst already carries this line; leaving it in duplicates it.
    article = article.replace(PREAMBLE, "", 1)
    return TEMPLATE.replace("@@NAV@@", render_nav(titles)).replace("@@ARTICLE@@", article)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=REPO / "COMMANDS.md")
    parser.add_argument("--out", type=Path, default=REPO / "build" / "field-manual.html")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(args.source.read_text()), encoding="utf-8")
    print(f"Wrote {args.out}")


TEMPLATE = r"""<title>memory-machine Field Manual</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {
  --ground: #EDEFF4;
  --raised: #FFFFFF;
  --sunk: #E3E6EE;
  --ink: #171B24;
  --ink-soft: #4B5364;
  --ink-faint: #79808F;
  --rule: #D3D8E3;
  --accent: #0E8F86;
  --accent-soft: #0E8F8618;
  --warn: #A9701C;
  --shadow: 0 1px 2px #171B2410, 0 8px 24px #171B240A;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #0E1219;
    --raised: #161C26;
    --sunk: #0A0E14;
    --ink: #E6EAF2;
    --ink-soft: #A2AAB9;
    --ink-faint: #6D7686;
    --rule: #262E3B;
    --accent: #3FD6C4;
    --accent-soft: #3FD6C41A;
    --warn: #D9A44E;
    --shadow: 0 1px 2px #00000040, 0 10px 30px #00000030;
  }
}
:root[data-theme="dark"] {
  --ground: #0E1219;
  --raised: #161C26;
  --sunk: #0A0E14;
  --ink: #E6EAF2;
  --ink-soft: #A2AAB9;
  --ink-faint: #6D7686;
  --rule: #262E3B;
  --accent: #3FD6C4;
  --accent-soft: #3FD6C41A;
  --warn: #D9A44E;
  --shadow: 0 1px 2px #00000040, 0 10px 30px #00000030;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  font-size: 16px;
  line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}
.iris {
  height: 3px;
  background: linear-gradient(90deg, #3FD6C4, #4E9BE8 28%, #8B6FE0 52%, #D2739C 74%, #E0A85C);
}
header {
  padding: 3rem 1.5rem 2.25rem;
  border-bottom: 1px solid var(--rule);
  background: var(--raised);
}
.headline {
  max-width: 62rem; margin: 0 auto;
  display: flex; gap: 1rem; align-items: baseline; flex-wrap: wrap;
}
h1 {
  font-family: "Bricolage Grotesque", ui-sans-serif, sans-serif;
  font-weight: 700; font-size: clamp(1.9rem, 4.5vw, 2.9rem);
  letter-spacing: -0.022em; margin: 0; text-wrap: balance;
}
.heart { color: var(--accent); font-size: 1.5rem; line-height: 1; }
@media (prefers-reduced-motion: no-preference) {
  .heart { animation: beat 1s infinite; }
  @keyframes beat { 0%,22% { transform: scale(1.18); } 30%,100% { transform: scale(0.92); } }
}
.standfirst {
  max-width: 62rem; margin: 0.9rem auto 0;
  color: var(--ink-soft); font-size: 1.05rem; max-inline-size: 60ch;
}
.wrap {
  max-width: 62rem; margin: 0 auto; padding: 0 1.5rem 6rem;
  display: grid; grid-template-columns: 14rem minmax(0, 1fr); gap: 3rem; align-items: start;
}
nav { position: sticky; top: 1.5rem; padding-top: 2.5rem; }
.navgroup + .navgroup { margin-top: 1.6rem; }
.navgroup h4 {
  margin: 0 0 0.5rem; font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-faint);
}
nav ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.15rem; }
nav a {
  display: block; padding: 0.2rem 0; color: var(--ink-soft);
  text-decoration: none; font-size: 0.9rem;
}
nav a:hover, nav a:focus-visible { color: var(--accent); }
main { padding-top: 2.5rem; min-width: 0; }
h2 {
  font-family: "Bricolage Grotesque", ui-sans-serif, sans-serif;
  font-weight: 700; font-size: 1.55rem; letter-spacing: -0.015em;
  margin: 3.5rem 0 1rem; padding-top: 1.5rem; border-top: 1px solid var(--rule);
  text-wrap: balance; scroll-margin-top: 1.5rem;
}
main > h2:first-child { margin-top: 0; border-top: 0; padding-top: 0; }
h3 {
  font-family: "Bricolage Grotesque", ui-sans-serif, sans-serif;
  font-weight: 500; font-size: 1.13rem; margin: 2.25rem 0 0.6rem;
  color: var(--ink); scroll-margin-top: 1.5rem;
}
p { margin: 0 0 1rem; max-inline-size: 68ch; }
ul { margin: 0 0 1rem; padding-left: 1.15rem; max-inline-size: 68ch; }
li { margin-bottom: 0.4rem; }
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
code {
  font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 0.9em;
  background: var(--accent-soft); color: var(--ink);
  padding: 0.1em 0.34em; border-radius: 3px;
}
strong { font-weight: 600; }
figure { margin: 0 0 1.15rem; position: relative; }
figure pre {
  margin: 0; overflow-x: auto; background: var(--sunk);
  border: 1px solid var(--rule); border-left: 2px solid var(--accent);
  padding: 0.85rem 1rem; border-radius: 0 4px 4px 0;
}
.block pre { border-left-color: var(--rule); }
figure code { background: none; padding: 0; font-size: 0.86rem; line-height: 1.55; }
.copy {
  position: absolute; top: 0.45rem; right: 0.5rem; z-index: 1;
  font: 500 0.72rem/1 "IBM Plex Sans", sans-serif; letter-spacing: 0.04em;
  color: var(--ink-faint); background: var(--raised);
  border: 1px solid var(--rule); border-radius: 3px;
  padding: 0.3rem 0.5rem; cursor: pointer; opacity: 0; transition: opacity 0.12s;
}
figure:hover .copy, .copy:focus-visible { opacity: 1; }
.copy:hover { color: var(--accent); border-color: var(--accent); }
.scroller { overflow-x: auto; margin: 0 0 1.35rem; border: 1px solid var(--rule); border-radius: 4px; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 0.6rem 0.85rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
th {
  font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--ink-faint); font-weight: 600; background: var(--sunk); white-space: nowrap;
}
tbody tr:last-child td { border-bottom: 0; }
td code { white-space: nowrap; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 62rem) {
  .wrap { grid-template-columns: 1fr; gap: 1.5rem; }
  nav {
    position: static; padding-top: 1.75rem; border-bottom: 1px solid var(--rule);
    padding-bottom: 1.25rem; display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 1.25rem;
  }
  .navgroup + .navgroup { margin-top: 0; }
  main { padding-top: 0.5rem; }
}
</style>
<div class="iris"></div>
<header>
  <div class="headline">
    <span class="heart" aria-hidden="true">&#9829;</span>
    <h1>memory-machine Field Manual</h1>
  </div>
  <p class="standfirst">Everything needed to run, inspect and change the installation. Commands run on the Pi unless marked <strong>(laptop)</strong>.</p>
</header>
<div class="wrap">
  <nav aria-label="Sections">@@NAV@@</nav>
  <main>@@ARTICLE@@</main>
</div>
<script>
document.querySelectorAll(".copy").forEach(function (button) {
  button.addEventListener("click", function () {
    var text = button.parentElement.querySelector("code").textContent;
    navigator.clipboard.writeText(text).then(function () {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = "Copy"; }, 1400);
    }, function () {
      button.textContent = "Select it";
      setTimeout(function () { button.textContent = "Copy"; }, 1400);
    });
  });
});
</script>
"""


if __name__ == "__main__":
    main()
