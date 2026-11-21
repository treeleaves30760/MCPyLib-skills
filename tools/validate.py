#!/usr/bin/env python3
"""Validate the MCPyLib skills repository.

Checks
  1. skills/<dir>/SKILL.md frontmatter follows the Agent Skills spec
     (agentskills.io/specification) plus the stricter rules of claude.ai
     uploads: only portable keys, name rules, description length, no XML tags.
  2. SKILL.md stays under 500 lines; relative links and `scripts/...`,
     `references/...` paths mentioned in skill Markdown exist.
  3. Every .py file under skills/ and tools/ compiles (py_compile).
  4. Every ```python block in the Markdown parses, and every mc.<method>(...)
     call (in .py files and Markdown) names a real MCPyLib method and binds to
     its signature. Needs the mcpylib package: pip install mcpylib
  5. skills/mcpylib/references/api.md lists every public MCPyLib method once,
     with the exact signature.
  6. .claude-plugin/marketplace.json and plugin.json have the required fields
     and consistent names.
  7. Each skill ships LICENSE.txt identical to the root LICENSE.

Usage:  python tools/validate.py [--skip-api]
Exit status: 0 when everything passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import py_compile
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

# Keys accepted by every surface (claude.ai and the Skills API reject others).
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED_WORDS = ("anthropic", "claude")
MAX_SKILL_LINES = 500
MAX_SKILL_CHARS = 20000  # about 5,000 tokens, the recommended body budget
API_RECEIVERS = {"mc"}  # mc.method(...) and anything.mc.method(...)
SIG_LINE_RE = re.compile(r"^`(mc\.(\w+)\(.*\)(?: -> .+)?)`\s*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
PATH_RE = re.compile(r"`((?:scripts|references|assets)/[\w./-]+)`")
FENCE_RE = re.compile(r"^```([\w+-]*)[^\n]*\n(.*?)^```\s*$", re.S | re.M)
MC_CALL_TEXT_RE = re.compile(r"\bmc\.([A-Za-z_]\w*)\(")

MARKETPLACE_TOP = {"$schema", "name", "owner", "plugins", "description", "version",
                   "metadata", "forceRemoveDeletedPlugins",
                   "allowCrossMarketplaceDependenciesOn", "renames"}
PLUGIN_ENTRY = {"name", "source", "description", "version", "author", "homepage",
                "repository", "license", "keywords", "category", "tags", "strict",
                "displayName", "metadata", "defaultEnabled", "dependencies"}
PLUGIN_JSON = {"$schema", "name", "displayName", "version", "description", "author",
               "homepage", "repository", "license", "keywords", "metadata"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# ---------------------------------------------------------------- frontmatter

def split_frontmatter(text: str) -> tuple[str, str] | None:
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None


def check_frontmatter(skill_dir: Path, rep: Report) -> None:
    import yaml  # PyYAML

    md = skill_dir / "SKILL.md"
    where = rel(md)
    text = md.read_text(encoding="utf-8")
    parts = split_frontmatter(text)
    if parts is None:
        rep.error(where, "must start with '---' YAML frontmatter closed by '---'")
        return
    raw, body = parts
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        rep.error(where, f"frontmatter is not valid YAML: {exc}")
        return
    if not isinstance(meta, dict):
        rep.error(where, "frontmatter must be a YAML mapping")
        return

    extra = set(meta) - ALLOWED_KEYS
    if extra:
        rep.error(where, f"non-portable frontmatter keys {sorted(extra)}; "
                         f"allowed: {sorted(ALLOWED_KEYS)}")

    name = meta.get("name")
    if not isinstance(name, str) or not name:
        rep.error(where, "'name' is required and must be a string")
    else:
        if len(name) > 64:
            rep.error(where, f"name is {len(name)} chars (max 64)")
        if not NAME_RE.match(name):
            rep.error(where, "name may only use a-z, 0-9 and single hyphens, "
                             "not starting or ending with a hyphen")
        if name != skill_dir.name:
            rep.error(where, f"name '{name}' must match the directory '{skill_dir.name}'")
        for word in RESERVED_WORDS:
            if word in name:
                rep.error(where, f"name must not contain the reserved word '{word}'")

    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        rep.error(where, "'description' is required and must be a non-empty string")
    else:
        if len(desc) > 1024:
            rep.error(where, f"description is {len(desc)} chars (max 1024)")
        if "<" in desc or ">" in desc:
            rep.error(where, "description must not contain XML tags or angle brackets")
        if "use when" not in desc.lower():
            rep.error(where, "description should say when to use the skill ('Use when ...')")
        # Repo convention: one plain line, so naive frontmatter parsers agree with YAML.
        line = next((l for l in raw.split("\n") if l.startswith("description:")), "")
        value = line[len("description:"):].strip()
        if value != desc:
            rep.error(where, "keep description as one plain single-line value "
                             "(no quotes, block scalars or ': ')")

    if "license" in meta and not isinstance(meta["license"], str):
        rep.error(where, "'license' must be a string")
    if "compatibility" in meta:
        comp = meta["compatibility"]
        if not isinstance(comp, str) or not (1 <= len(comp) <= 500):
            rep.error(where, "'compatibility' must be a string of 1-500 characters")
    if "metadata" in meta:
        md_map = meta["metadata"]
        if not isinstance(md_map, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in md_map.items()):
            rep.error(where, "'metadata' must map strings to strings (quote numbers)")
    if "allowed-tools" in meta and not isinstance(meta["allowed-tools"], str):
        rep.error(where, "'allowed-tools' must be a space-separated string")

    n_lines = text.count("\n") + 1
    if n_lines >= MAX_SKILL_LINES:
        rep.error(where, f"{n_lines} lines; keep SKILL.md under {MAX_SKILL_LINES}")
    if len(body) > MAX_SKILL_CHARS:
        rep.warn(where, f"body is {len(body)} chars (~{len(body)//4} tokens); "
                        "consider moving detail to references/")


# ---------------------------------------------------------------- links/paths

def check_links(md: Path, rep: Report, skill_dir: Path | None) -> None:
    text = md.read_text(encoding="utf-8")
    no_code = FENCE_RE.sub("", text)
    for target in LINK_RE.findall(no_code):
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        if path and not (md.parent / path).exists():
            rep.error(rel(md), f"broken relative link '{target}'")
    if skill_dir is not None:
        for path in PATH_RE.findall(no_code):
            if not (skill_dir / path).exists():
                rep.error(rel(md), f"mentions '{path}' but {rel(skill_dir)}/{path} does not exist")


# ---------------------------------------------------------------- python code

def compile_py(path: Path, rep: Report, tmp: Path) -> None:
    try:
        py_compile.compile(str(path), cfile=str(tmp / "check.pyc"), doraise=True)
    except py_compile.PyCompileError as exc:
        rep.error(rel(path), f"py_compile failed: {exc.msg}")


def load_api(rep: Report):
    try:
        from mcpylib import MCPyLib  # noqa: F401
    except ImportError:
        rep.error("api", "cannot import mcpylib; run `pip install mcpylib` (or pass --skip-api)")
        return None
    return {n: inspect.signature(f)
            for n, f in inspect.getmembers(MCPyLib, inspect.isfunction)
            if not n.startswith("_")}


def receiver_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def check_calls(tree: ast.AST, where: str, api: dict, rep: Report, line_offset: int = 0) -> int:
    checked = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if receiver_name(node.func.value) not in API_RECEIVERS:
            continue
        method = node.func.attr
        loc = f"{where}:{node.lineno + line_offset}"
        if method not in api:
            rep.error(loc, f"mc.{method}() is not an MCPyLib method")
            continue
        if any(isinstance(a, ast.Starred) for a in node.args) or any(
                k.arg is None for k in node.keywords):
            continue
        try:
            api[method].bind(None, *([None] * len(node.args)),
                             **{k.arg: None for k in node.keywords})
        except TypeError as exc:
            rep.error(loc, f"mc.{method}{api[method]} -- call does not bind: {exc}")
        checked += 1
    return checked


def python_blocks(text: str):
    for m in FENCE_RE.finditer(text):
        if m.group(1).lower() in ("python", "py", "python3"):
            start_line = text.count("\n", 0, m.start(2))
            yield start_line, m.group(2)


def check_markdown_code(md: Path, api: dict | None, rep: Report) -> int:
    text = md.read_text(encoding="utf-8")
    checked = 0
    for start, code in python_blocks(text):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            rep.error(f"{rel(md)}:{start + (exc.lineno or 0)}", f"python block does not parse: {exc.msg}")
            continue
        if api is not None:
            checked += check_calls(tree, rel(md), api, rep, line_offset=start)
    if api is not None:
        for method in set(MC_CALL_TEXT_RE.findall(text)):
            if method not in api:
                rep.error(rel(md), f"mentions mc.{method}() which is not an MCPyLib method")
    return checked


def format_signature(name: str, sig: inspect.Signature) -> str:
    parts = []
    for p in list(sig.parameters.values())[1:]:
        s = p.name
        if p.default is not inspect.Parameter.empty:
            s += "=" + (json.dumps(p.default) if isinstance(p.default, str) else repr(p.default))
        parts.append(s)
    ret = sig.return_annotation
    if ret is inspect.Signature.empty:
        ret_s = ""
    elif isinstance(ret, type):
        ret_s = ret.__name__
    else:
        ret_s = str(ret).replace("typing.", "")
    return f"mc.{name}({', '.join(parts)})" + (f" -> {ret_s}" if ret_s else "")


def check_api_reference(api: dict, rep: Report) -> None:
    ref = SKILLS / "mcpylib" / "references" / "api.md"
    if not ref.exists():
        rep.error(rel(ref), "missing")
        return
    seen: dict[str, int] = {}
    for i, line in enumerate(ref.read_text(encoding="utf-8").split("\n"), 1):
        m = SIG_LINE_RE.match(line)
        if not m:
            continue
        sig_text, name = m.group(1), m.group(2)
        seen[name] = seen.get(name, 0) + 1
        if name not in api:
            rep.error(f"{rel(ref)}:{i}", f"documents unknown method {name}")
        elif sig_text != format_signature(name, api[name]):
            rep.error(f"{rel(ref)}:{i}", f"signature '{sig_text}' != actual "
                                          f"'{format_signature(name, api[name])}'")
    for name in api:
        if seen.get(name, 0) != 1:
            rep.error(rel(ref), f"method {name} documented {seen.get(name, 0)} times (want 1)")


# ---------------------------------------------------------------- manifests

def check_manifests(rep: Report) -> None:
    mp_path = ROOT / ".claude-plugin" / "marketplace.json"
    where = rel(mp_path)
    try:
        mp = json.loads(mp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        rep.error(where, f"cannot read: {exc}")
        return
    for key in ("name", "owner", "plugins"):
        if key not in mp:
            rep.error(where, f"missing required field '{key}'")
    name = mp.get("name", "")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name) or ".." in name:
        rep.error(where, f"invalid marketplace name '{name}'")
    if not isinstance(mp.get("owner"), dict) or not mp["owner"].get("name"):
        rep.error(where, "owner.name is required")
    if not mp.get("description"):
        rep.warn(where, "no marketplace description")
    for key in set(mp) - MARKETPLACE_TOP:
        rep.warn(where, f"unknown top-level field '{key}'")
    plugins = mp.get("plugins") or []
    if not plugins:
        rep.error(where, "plugins must list at least one plugin")
    for i, entry in enumerate(plugins):
        ew = f"{where} plugins[{i}]"
        for key in set(entry) - PLUGIN_ENTRY:
            rep.warn(ew, f"unknown field '{key}'")
        pname = entry.get("name", "")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", pname):
            rep.error(ew, f"invalid plugin name '{pname}'")
        source = entry.get("source")
        if not isinstance(source, str) or not (source == "." or source.startswith("./")):
            rep.error(ew, "source must be a relative path starting with './'")
            continue
        if ".." in source:
            rep.error(ew, "source must not contain '..'")
            continue
        plugin_root = (ROOT / source).resolve()
        if not plugin_root.is_dir():
            rep.error(ew, f"source '{source}' does not exist")
            continue
        pj_path = plugin_root / ".claude-plugin" / "plugin.json"
        if pj_path.exists():
            pj = json.loads(pj_path.read_text(encoding="utf-8"))
            pw = rel(pj_path)
            if pj.get("name") != pname:
                rep.error(pw, f"name '{pj.get('name')}' must equal the marketplace entry name '{pname}'")
            for key in ("version", "description", "author"):
                if key not in pj:
                    rep.warn(pw, f"missing '{key}'")
            for key in set(pj) - PLUGIN_JSON:
                rep.warn(pw, f"field '{key}' not checked by this validator")
            if "version" in entry and "version" in pj:
                rep.warn(ew, "version set in both entry and plugin.json (plugin.json wins)")
        skills_dir = plugin_root / "skills"
        found = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md"))
        if not found:
            rep.error(ew, "plugin has no skills/<name>/SKILL.md")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skip-api", action="store_true",
                    help="skip checks that need the mcpylib package")
    args = ap.parse_args()
    rep = Report()

    try:
        import yaml  # noqa: F401
    except ImportError:
        print("PyYAML is required: pip install pyyaml")
        return 1

    api = None if args.skip_api else load_api(rep)

    skill_dirs = sorted(p for p in SKILLS.iterdir() if p.is_dir()) if SKILLS.is_dir() else []
    if not skill_dirs:
        rep.error("skills", "no skill directories found")
    root_license = (ROOT / "LICENSE").read_bytes() if (ROOT / "LICENSE").exists() else None

    calls_checked = 0
    for sd in skill_dirs:
        if not (sd / "SKILL.md").exists():
            rep.error(rel(sd), "missing SKILL.md")
            continue
        check_frontmatter(sd, rep)
        lic = sd / "LICENSE.txt"
        if root_license is None or not lic.exists() or lic.read_bytes() != root_license:
            rep.error(rel(sd), "LICENSE.txt missing or different from the root LICENSE")
        for md in sorted(sd.rglob("*.md")):
            check_links(md, rep, sd)
            calls_checked += check_markdown_code(md, api, rep)

    for md in sorted(ROOT.glob("*.md")):
        check_links(md, rep, None)
        calls_checked += check_markdown_code(md, api, rep)

    py_files = sorted(list(SKILLS.rglob("*.py")) + list((ROOT / "tools").rglob("*.py")))
    with tempfile.TemporaryDirectory() as tmp:
        for py in py_files:
            compile_py(py, rep, Path(tmp))
    if api is not None:
        for py in py_files:
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue  # already reported by py_compile
            calls_checked += check_calls(tree, rel(py), api, rep)
        check_api_reference(api, rep)

    check_manifests(rep)

    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors:
        print(f"FAIL  {e}")
    print(f"\nskills: {len(skill_dirs)}  python files compiled: {len(py_files)}  "
          f"mc.* calls checked: {calls_checked}  "
          f"api methods: {len(api) if api else 'skipped'}")
    if rep.errors:
        print(f"Validation FAILED: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
        return 1
    print(f"Validation passed ({len(rep.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
