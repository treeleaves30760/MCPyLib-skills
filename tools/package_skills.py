#!/usr/bin/env python3
"""Build one zip per skill for uploading to claude.ai (Customize > Skills).

Each zip holds the skill folder at its root (mcpylib/SKILL.md, mcpylib/scripts/...),
which is the layout claude.ai expects. Bytecode and caches are left out.

Usage:  python tools/package_skills.py [--out dist] [SKILL ...]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def build(skill_dir: Path, out_dir: Path) -> Path:
    target = out_dir / f"{skill_dir.name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(skill_dir.rglob("*")):
            rel = path.relative_to(skill_dir)
            if path.is_dir() or SKIP_PARTS & set(rel.parts) or path.suffix in SKIP_SUFFIXES:
                continue
            zf.write(path, (Path(skill_dir.name) / rel).as_posix())
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="Zip each skill for claude.ai uploads.")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default: dist/)")
    ap.add_argument("skills", nargs="*", help="skill names (default: all)")
    args = ap.parse_args()
    available = {p.name: p for p in sorted((ROOT / "skills").iterdir()) if (p / "SKILL.md").exists()}
    names = args.skills or list(available)
    unknown = [n for n in names if n not in available]
    if unknown:
        print(f"Unknown skill(s): {', '.join(unknown)}; available: {', '.join(available)}")
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = build(available[name], out_dir)
        with zipfile.ZipFile(target) as zf:
            count = len(zf.namelist())
        print(f"{target} ({count} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
