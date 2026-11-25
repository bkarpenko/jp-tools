"""Build disclosure-limited method references from the pinned commit; no network."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

BASE = "1ad3d417ee3e3d0f7f2ee3769d0c258ae13488a7"
ROOT = Path(__file__).resolve().parents[5]
DEST = Path(__file__).resolve().parent
TERMS = [
    "\u683c\u597d", "\u6070\u597d", "\u8cac\u4efb", "\u8d23\u4efb",
    "\u4e0a\u9054", "\u4e0a\u8fbe", "\u304b\u3063\u3053\u3046",
    "\u304b\u3063\u2010\u3053\u3046", "\u30ab\u30c3\u30b3\u30a6",
    "\u305b\u304d\u306b\u3093", "\u305b\u304d\u2010\u306b\u3093", "\u30bb\u30ad\u30cb\u30f3",
    "\u3058\u3087\u3046\u305f\u3064", "\u3058\u3087\u3046\u2010\u305f\u3064", "\u30b8\u30e7\u30a6\u30bf\u30c4",
    "kakkou", "kakko", "qiahao", "sekinin", "zeren", "joutatsu", "jotatsu", "j\u014dtatsu", "shangda",
]
SOURCES = {
    "tools/jukugo/PIPELINE.md": "PIPELINE.md",
    "tools/jukugo/references/web-sources.md": "web-sources.md",
    "tools/jukugo/references/SCHEMA.md": "SCHEMA.md",
    "tools/jukugo/references/russian.md": "russian.md",
    "CLAUDE.md": "CLAUDE.md",
    "tools/jukugo/README.md": "jukugo-README.md",
}

def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)

def unsafe(value: str) -> bool:
    decoded = unquote(unquote(value)).casefold()
    return any(term.casefold() in decoded for term in TERMS)

def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def main() -> None:
    (DEST / "neutral").mkdir(exist_ok=True)
    entries = []
    for source, output in SOURCES.items():
        raw = git("show", f"{BASE}:{source}")
        content = raw.decode("utf-8-sig")
        sections = re.split(r"(?m)(?=^#{1,6}\s)", content)
        kept = []
        removed = []
        for index, section in enumerate(sections):
            if unsafe(section):
                removed.append(index)
                kept.append(
                    "\n> [Раздел с конкретным случаем исключён для независимого испытания. "
                    "Экспериментальный порядок работы задан в protocol.md и access.md.]\n\n"
                )
            else:
                kept.append(section)
        result = (
            "<!-- Derived reference; not the accepted method source. "
            f"Base: {BASE}. Original: {source}. "
            "Concrete-case sections are withheld; do not reconstruct them. -->\n\n"
            + "".join(kept)
        ).encode("utf-8")
        if unsafe(result.decode("utf-8")):
            raise RuntimeError(f"Disclosure check failed: {output}")
        path = DEST / "neutral" / output
        path.write_bytes(result)
        entries.append({
            "source_path": source,
            "base_commit": BASE,
            "git_blob": git("rev-parse", f"{BASE}:{source}").decode().strip(),
            "source_sha256": sha256(raw),
            "derived_path": f"neutral/{output}",
            "derived_sha256": sha256(result),
            "withheld_section_indices": removed,
        })
    main_files = [
        "handoff.md", "protocol.md", "protocol-v2-coverage.md",
        "protocol-v3-entry-search.md", "access.md", "state.md",
        "start-here.md", "make_neutral.py", "../../../references/ja-on-morphemes.md",
        "../../../references/express-method.md",
    ]
    manifest = {
        "base_commit": BASE,
        "pipeline_blob": "fa0f35da06a7cc27441d496fe2496217630dbeda",
        "purpose": "Independent prospective trial; no case results or expected classifications included.",
        "sanitization": "Withhold entire Markdown heading sections containing a target token or encoded equivalent; no previous analyses read.",
        "limitations": "Derived references are intentionally incomplete. protocol.md/access.md supply the prospective route. Not a formally blinded model study.",
        "references": entries,
        "handoff_sha256": {name: sha256((DEST / name).read_bytes()) for name in main_files},
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"references": len(entries), "withheld_sections": sum(len(e["withheld_section_indices"]) for e in entries), "target_token_check": "passed"}))

if __name__ == "__main__":
    main()
