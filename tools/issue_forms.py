"""Hold the issue forms to what GitHub accepts.

A malformed form is not rejected on push. GitHub falls back to a blank
issue, so the first anyone knows is a report carrying none of the
fields it was supposed to ask for.

Checks this repository by default, and any sibling given as an
argument, so one run covers every implementation on a machine that has
them checked out:

    python tools/issue_forms.py            # this repository
    python tools/issue_forms.py ../assert-go ../assert-python
"""

import pathlib
import re
import sys

import yaml

TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}
ID = re.compile(r"^[a-z0-9_-]+$")

problems: list[str] = []


def at(where: str, what: str) -> None:
    """Record one problem, and where it is."""
    problems.append(f"{where}: {what}")


ROOT = pathlib.Path(__file__).resolve().parent.parent

for repo in sys.argv[1:] or [str(ROOT)]:
    root = pathlib.Path(repo) / ".github" / "ISSUE_TEMPLATE"
    forms = sorted(p for p in root.glob("*.yml") if p.name != "config.yml")
    if not forms:
        at(repo, "has no issue forms")
        continue

    names = {p.name for p in forms}
    for path in forms:
        where = f"{repo}/{path.name}"
        form = yaml.safe_load(path.read_text())

        for key in ("name", "description", "body"):
            if not form.get(key):
                at(where, f"states no {key}")

        seen: set[str] = set()
        for index, item in enumerate(form.get("body", [])):
            kind = item.get("type")
            if kind not in TYPES:
                at(where, f"body[{index}] has type {kind!r}")
                continue

            ident = item.get("id")
            if kind != "markdown":
                if not ident:
                    at(where, f"body[{index}] ({kind}) has no id")
                elif not ID.match(ident):
                    at(where, f"id {ident!r} is not lowercase and hyphenated")
                elif ident in seen:
                    at(where, f"id {ident!r} is used twice")
                seen.add(str(ident))

            attributes = item.get("attributes", {})
            if kind == "markdown" and not attributes.get("value"):
                at(where, f"body[{index}] is markdown with no value")
            if kind != "markdown" and not attributes.get("label"):
                at(where, f"body[{index}] ({kind}) has no label")
            if kind == "dropdown" and not attributes.get("options"):
                at(where, f"body[{index}] is a dropdown with no options")
            if kind == "checkboxes":
                for option in attributes.get("options", []):
                    if not option.get("label"):
                        at(where, f"body[{index}] has a checkbox with no label")

    config = root / "config.yml"
    if not config.exists():
        at(repo, "has no ISSUE_TEMPLATE/config.yml")
        continue

    settings = yaml.safe_load(config.read_text())
    for link in settings.get("contact_links", []):
        for key in ("name", "url", "about"):
            if not link.get(key):
                at(f"{repo}/config.yml", f"a contact link states no {key}")

        url = str(link.get("url", ""))
        template = re.search(r"[?&]template=([\w.-]+)", url)
        # A link into this repository's own forms has to name one
        # that exists. A link elsewhere is checked by that repo.
        own = pathlib.Path(repo).name
        if template and f"/{own}/" in url and template.group(1) not in names:
            at(f"{repo}/config.yml", f"links to {template.group(1)}, which is absent")

for problem in problems:
    print(problem, file=sys.stderr)
print(f"\n{len(problems)} problem(s)" if problems else "issue forms: all valid")
sys.exit(1 if problems else 0)
