"""Build a single-page HTML viewer for the workshop notebook series.

Run from the repo root (or via scripts/generate_workshop_series.py, which
calls build() automatically after regenerating the notebooks):

    python3 scripts/build_workshop_website.py

Writes:
    docs/workshop/site/index.html   one page, all notebooks, tab-switchable
    docs/workshop/site/images/      copy of docs/workshop/images/

The notebooks are embedded verbatim as JSON inside the HTML.  Markdown and
code cells are rendered client-side with marked.js, highlight.js, and
MathJax loaded from a CDN, so an internet connection is required when
viewing.  Image references (``images/...``) resolve against the copied
images folder, keeping the HTML itself small.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "workshop"
SITE_DIR = OUT_DIR / "site"

TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
KICKER_RE = re.compile(r"^Notebook\s+(\d+)\s+—\s+(.*)$")


def _source(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def load_notebooks(out_dir: Path) -> list[dict]:
    """Parse each .ipynb into {file, number, title, subtitle, cells}."""
    books = []
    for path in sorted(out_dir.glob("*.ipynb")):
        nb = json.loads(path.read_text(encoding="utf-8"))
        cells = [
            {"type": c["cell_type"], "source": _source(c)}
            for c in nb.get("cells", [])
        ]
        first = next((c["source"] for c in cells if c["type"] == "markdown"), "")
        m = TITLE_RE.search(first)
        title = m.group(1).strip() if m else path.stem
        kicker = KICKER_RE.match(title)
        number = int(kicker.group(1)) if kicker else None
        subtitle = kicker.group(2) if kicker else title
        books.append(
            {
                "file": path.name,
                "number": number,
                "title": title,
                "subtitle": subtitle,
                "cells": cells,
            }
        )
    books.sort(key=lambda b: (b["number"] is None, b["number"], b["file"]))
    return books


def build(out_dir: Path = OUT_DIR, site_dir: Path = SITE_DIR) -> Path:
    books = load_notebooks(out_dir)
    if not books:
        raise SystemExit(f"no notebooks found in {out_dir}")

    data = json.dumps(books, ensure_ascii=False).replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__DATA__", data)

    site_dir.mkdir(parents=True, exist_ok=True)
    images_src = out_dir / "images"
    if images_src.is_dir():
        shutil.copytree(images_src, site_dir / "images", dirs_exist_ok=True)
    index = site_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    print(f"wrote {index} ({len(books)} notebooks)")
    return index


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tidal-OSS Workshop</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Roboto+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11/styles/github.min.css">
<script src="https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script>
window.MathJax = {
  tex: { inlineMath: [["$", "$"]], displayMath: [["$$", "$$"]] },
  options: { skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"] }
};
</script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
<style>
  :root {
    --md-primary: #1976d2; --md-primary-dark: #1565c0;
    --md-on-primary: #ffffff;
    --md-surface: #ffffff; --md-surface-container-low: #f8fafd;
    --md-surface-container: #f0f4f9;
    --md-on-surface: #1b1c1e; --md-on-surface-variant: #5f6368;
    --md-outline: #c4c7c5; --md-outline-variant: #e0e3e7;
    --md-active-container: #e8f0fe; --md-on-active: #1967d2;
    --e1: 0 1px 2px rgba(0,0,0,.10), 0 1px 3px 1px rgba(0,0,0,.06);
    --e2: 0 1px 2px rgba(0,0,0,.10), 0 2px 6px 2px rgba(0,0,0,.08);
    --sidebar-w: 272px;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0; background: var(--md-surface); color: var(--md-on-surface);
    font: 16px/1.65 Roboto, -apple-system, BlinkMacSystemFont, "Segoe UI",
      Helvetica, Arial, sans-serif;
    display: flex; min-height: 100vh; align-items: stretch;
  }
  ::selection { background: #c9ddf8; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb { background: var(--md-outline); border-radius: 8px;
    border: 2px solid var(--md-surface); }
  aside.sidebar {
    flex: 0 0 var(--sidebar-w); background: var(--md-surface); color: var(--md-on-surface);
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
    display: flex; flex-direction: column;
    border-right: 1px solid var(--md-outline-variant);
  }
  aside.sidebar .brand {
    padding: 20px 20px 16px; font-size: 18px; font-weight: 500;
    letter-spacing: .15px; color: var(--md-on-surface);
  }
  aside.sidebar .brand small {
    display: block; font-size: 12px; font-weight: 400; letter-spacing: .4px;
    color: var(--md-on-surface-variant); margin-top: 2px;
  }
  nav.tabs { flex: 1; padding: 4px 12px 12px; }
  nav.tabs button {
    display: flex; align-items: center; width: 100%; text-align: left;
    background: none; border: none; border-radius: 999px;
    color: var(--md-on-surface-variant);
    padding: 10px 16px; margin: 2px 0; font: inherit; font-size: 13.5px;
    font-weight: 500; letter-spacing: .2px; line-height: 1.35; cursor: pointer;
    transition: background-color .15s ease, color .15s ease;
  }
  nav.tabs button:hover { background: var(--md-surface-container); color: var(--md-on-surface); }
  nav.tabs button.active {
    background: var(--md-active-container); color: var(--md-on-active); font-weight: 700;
  }
  nav.tabs button .num {
    flex: 0 0 22px; font-family: "Roboto Mono", monospace; font-size: 12px;
    color: inherit; opacity: .85;
  }
  aside.sidebar .foot {
    padding: 12px 24px; font-size: 12px; letter-spacing: .3px;
    color: var(--md-on-surface-variant);
    border-top: 1px solid var(--md-outline-variant);
  }
  .col { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  header {
    position: sticky; top: 0; z-index: 10; background: var(--md-surface);
    box-shadow: var(--e1);
  }
  .bar {
    max-width: 980px; margin: 0 auto; padding: 14px 24px;
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  }
  .bar h1 { font-size: 18px; margin: 0; font-weight: 500; letter-spacing: .2px; }
  .bar .sub {
    font-size: 12px; color: var(--md-on-active); background: var(--md-active-container);
    padding: 3px 10px; border-radius: 999px; font-weight: 500; letter-spacing: .3px;
  }
  main { width: 100%; max-width: 980px; margin: 0 auto; padding: 32px 24px 40px; }
  .cell-markdown { margin: 0 0 8px; }
  .cell-markdown h1 { font-weight: 400; font-size: 32px; letter-spacing: 0; margin: .4em 0 .4em; }
  .cell-markdown h2 { font-weight: 500; font-size: 24px; margin-top: 1.6em; }
  .cell-markdown h3 { font-weight: 500; font-size: 20px; }
  .cell-markdown a { color: var(--md-primary); text-decoration: none; }
  .cell-markdown a:hover { text-decoration: underline; }
  .cell-markdown img { max-width: 100%; height: auto; display: block; margin: 16px 0;
    border: 1px solid var(--md-outline-variant); border-radius: 12px; box-shadow: var(--e1); }
  .cell-markdown table { border-collapse: separate; border-spacing: 0; display: block;
    overflow-x: auto; box-shadow: var(--e1); border-radius: 12px; margin: 16px 0; }
  .cell-markdown th, .cell-markdown td {
    border-bottom: 1px solid var(--md-outline-variant); padding: 10px 16px; text-align: left;
  }
  .cell-markdown tr:last-child td { border-bottom: none; }
  .cell-markdown th { background: var(--md-surface-container); font-weight: 500; }
  .cell-markdown blockquote {
    margin: 16px 0; padding: 8px 20px; border-left: 4px solid var(--md-primary);
    background: var(--md-surface-container-low); border-radius: 0 12px 12px 0;
    color: var(--md-on-surface-variant);
  }
  .cell-markdown code:not(pre code) {
    font-family: "Roboto Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: var(--md-surface-container); padding: .15em .4em; border-radius: 6px;
    font-size: 85%; color: #37474f;
  }
  .cell-code {
    display: flex; margin: 12px 0 20px; border: 1px solid var(--md-outline-variant);
    border-radius: 12px; background: var(--md-surface-container-low);
    box-shadow: var(--e1); overflow: hidden;
  }
  .cell-code .prompt {
    flex: 0 0 64px; color: var(--md-primary);
    font: 500 12px/1.6 "Roboto Mono", ui-monospace, SFMono-Regular, Menlo, Consolas,
      monospace; text-align: right; padding: 10px 10px 10px 0;
    user-select: none; background: var(--md-surface-container);
  }
  .cell-code pre {
    flex: 1; margin: 0; padding: 10px 14px; overflow-x: auto; background: transparent;
  }
  .cell-code pre code {
    font: 400 13px/1.6 "Roboto Mono", ui-monospace, SFMono-Regular, Menlo,
      Consolas, monospace; background: transparent;
  }
  footer.pager {
    width: 100%; max-width: 980px; margin: 0 auto; padding: 0 24px 64px;
    display: flex; justify-content: space-between; gap: 12px; align-items: center;
  }
  footer.pager button {
    background: var(--md-primary); color: var(--md-on-primary); border: none;
    border-radius: 999px; padding: 10px 24px; font: inherit; font-size: 14px;
    font-weight: 500; letter-spacing: .3px; cursor: pointer; box-shadow: var(--e2);
    transition: background-color .15s ease, box-shadow .15s ease;
  }
  footer.pager button:hover:not(:disabled) { background: var(--md-primary-dark); }
  footer.pager button:disabled {
    background: rgba(0,0,0,.12); color: rgba(0,0,0,.38); box-shadow: none;
    cursor: default;
  }
  .hint { font-size: 12px; letter-spacing: .4px; color: var(--md-on-surface-variant); }
  @media (max-width: 760px) {
    body { flex-direction: column; }
    aside.sidebar { position: static; height: auto; width: 100%; flex: none;
      border-right: none; border-bottom: 1px solid var(--md-outline-variant); }
    aside.sidebar .brand { padding-bottom: 8px; }
    aside.sidebar .foot { display: none; }
    nav.tabs { display: flex; padding: 4px 12px 12px; }
    nav.tabs button { width: auto; white-space: nowrap; }
  }
</style>
</head>
<body>
<aside class="sidebar">
  <div class="brand">Tidal-OSS Workshop<small>Documentation series</small></div>
  <nav class="tabs" id="tabs" aria-label="Notebooks"></nav>
  <div class="foot">&larr; / &rarr; keys switch notebooks</div>
</aside>
<div class="col">
<header>
  <div class="bar">
    <h1 id="book-title"></h1>
    <span class="sub" id="book-sub"></span>
  </div>
</header>
<main id="content"></main>
<footer class="pager">
  <button id="prev">&larr; &nbsp;Prev</button>
  <span class="hint" id="pager-pos"></span>
  <button id="next">Next&nbsp; &rarr;</button>
</footer>
</div>

<script type="application/json" id="notebooks">__DATA__</script>
<script>
const BOOKS = JSON.parse(document.getElementById("notebooks").textContent);
let current = 0;

function maskMath(src) {
  const stash = [];
  const keep = (s) => { stash.push(s); return "\u0000" + (stash.length - 1) + "\u0000"; };
  src = src.replace(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g, keep);
  src = src.replace(/(`[^`\n]*`)/g, keep);
  src = src.replace(/\$\$[\s\S]*?\$\$/g, keep);
  src = src.replace(/\$[^$\n]*?\$/g, keep);
  return [src, stash];
}

function renderMarkdown(src) {
  const [masked, stash] = maskMath(src);
  let html = marked.parse(masked);
  html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[+i]);
  return html;
}

function render() {
  const book = BOOKS[current];
  document.getElementById("book-title").textContent = book.title;
  document.getElementById("book-sub").textContent = book.file;
  document.getElementById("pager-pos").textContent =
    (current + 1) + " / " + BOOKS.length;
  document.title = book.title + " · Tidal-OSS Workshop";
  const content = document.getElementById("content");
  let codeNo = 0;
  content.innerHTML = book.cells.map((cell) => {
    if (cell.type === "code") {
      codeNo += 1;
      const esc = cell.source
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return '<div class="cell-code"><div class="prompt">In&nbsp;['
        + codeNo + "]:</div><pre><code class=\"language-python\">"
        + esc + "</code></pre></div>";
    }
    return '<div class="cell cell-markdown">' + renderMarkdown(cell.source) + "</div>";
  }).join("");
  content.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));
  rewriteLinks(content);
  if (window.MathJax && MathJax.typesetPromise) {
    MathJax.typesetClear([content]);
    MathJax.typesetPromise([content]);
  }
  updateTabs();
  updatePager();
  location.hash = "n=" + current;
  window.scrollTo(0, 0);
}

function rewriteLinks(root) {
  root.querySelectorAll("a[href]").forEach((a) => {
    const href = a.getAttribute("href");
    const m = href.match(/(\d\.[a-z-]+\.ipynb)/);
    if (m) {
      const idx = BOOKS.findIndex((b) => b.file === m[1]);
      if (idx >= 0) {
        a.addEventListener("click", (e) => { e.preventDefault(); go(idx); });
        a.style.cursor = "pointer";
        return;
      }
    }
    if (href.endsWith("README.md")) { a.addEventListener("click", (e) => e.preventDefault()); return; }
    if (!/^https?:/.test(href) && !href.startsWith("#")) {
      a.addEventListener("click", (e) => e.preventDefault());
    }
  });
}

function go(i) {
  if (i < 0 || i >= BOOKS.length || i === current) return;
  current = i;
  render();
}

function updateTabs() {
  document.querySelectorAll("#tabs button").forEach((b, i) => {
    b.classList.toggle("active", i === current);
    if (i === current) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
}

function updatePager() {
  document.getElementById("prev").disabled = current === 0;
  document.getElementById("next").disabled = current === BOOKS.length - 1;
}

(function initTabs() {
  const bar = document.getElementById("tabs");
  BOOKS.forEach((b, i) => {
    const btn = document.createElement("button");
    const label = (b.number !== null ? b.subtitle : b.title);
    const short = label.length > 52 ? label.slice(0, 51) + "\u2026" : label;
    if (b.number !== null) {
      const num = document.createElement("span");
      num.className = "num";
      num.textContent = String(b.number).padStart(2, "0");
      btn.appendChild(num);
    }
    btn.appendChild(document.createTextNode(short));
    btn.title = b.file;
    btn.addEventListener("click", () => go(i));
    bar.appendChild(btn);
  });
})();

document.getElementById("prev").addEventListener("click", () => go(current - 1));
document.getElementById("next").addEventListener("click", () => go(current + 1));
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.key === "ArrowLeft") go(current - 1);
  if (e.key === "ArrowRight") go(current + 1);
});

(function start() {
  const m = location.hash.match(/n=(\d+)/);
  if (m && +m[1] < BOOKS.length) current = +m[1];
  render();
})();
</script>
</body>
</html>
"""


def main() -> None:
    build()


if __name__ == "__main__":
    main()
