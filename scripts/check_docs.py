"""Validate Markdown links and code syntax; render local HTML for inspection."""

import html
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]


def main():
    markdown = MarkdownIt("commonmark").enable("table")
    sources = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for source in sources:
        contents = source.read_text()
        assert contents.endswith("\n"), f"Missing final newline: {source}"
        for number, line in enumerate(contents.splitlines(), 1):
            assert line.rstrip() == line, f"Trailing whitespace: {source}:{number}"
        fence = None
        for line in contents.splitlines():
            match = re.match(r"^(`{3,}|~{3,})", line)
            if match:
                marker = match.group(1)
                if fence is None:
                    fence = marker
                elif marker[0] == fence[0] and len(marker) >= len(fence):
                    fence = None
        assert fence is None, f"Unclosed code fence: {source}"
        tokens = markdown.parse(contents)
        for token in tokens:
            if token.type == "fence" and token.info == "python":
                compile(token.content, str(source), "exec")
            for child in token.children or ():
                if child.type != "link_open":
                    continue
                destination = urlsplit(child.attrGet("href"))
                if not destination.scheme and destination.path:
                    target = source.parent / unquote(destination.path)
                    assert target.exists(), f"Broken link in {source}: {target}"
        rendered = markdown.render(contents)
        assert "<h1>" in rendered
        target = ROOT / "build/docs" / source.relative_to(ROOT).with_suffix(".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        page = (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            f"<title>{html.escape(source.stem)}</title>"
            "<style>body{max-width:880px;margin:48px auto;padding:0 24px;line-height:1.75;"
            "font-family:system-ui,sans-serif;color:#1d2834}pre{padding:18px;background:#f2f5f8;"
            "overflow:auto;line-height:1.5}code{font-size:0.9em}table{border-collapse:collapse}"
            "td,th{padding:8px 14px;border:1px solid #ccd4df}a{color:#176ac7}</style>"
            f"<body>{rendered}</body></html>"
        )
        target.write_text(page)
    # The README's complete Python example is an executable part of the public API.
    readme = markdown.parse((ROOT / "README.md").read_text())
    for token in readme:
        if token.type == "fence" and token.info == "python":
            exec(compile(token.content, "README.md", "exec"), {"__name__": "__readme__"})
    print(f"Checked and rendered {len(sources)} Markdown files; README example passed")
    print(ROOT / "build/docs/README.html")


if __name__ == "__main__":
    main()
