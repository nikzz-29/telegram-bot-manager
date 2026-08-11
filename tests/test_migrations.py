"""The migration directory has to stay importable, template included.

Alembic loads every file in `alembic/versions/` before it can resolve a single
revision, so one unparseable file there is not a broken migration — it is a
broken `upgrade head`, and the whole stack with it: the compose `migrate` service
is a gate the other three wait on. The failure surfaces as a container exiting 1
with a traceback fifty frames deep, which is a long way from the syntax error
that caused it.

DECISION: the template is rendered and parsed rather than eyeballed. It produced
an unterminated docstring for the length of a whole stage — nothing catches that
until someone runs `task revision`, and then it breaks a deploy rather than the
person who ran it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from mako.template import Template

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"
VERSIONS_DIR = ALEMBIC_DIR / "versions"
TEMPLATE = ALEMBIC_DIR / "script.py.mako"

# What `alembic revision` passes the template. `upgrades`/`downgrades` are empty
# for the no-diff case, which is both the plainest render and the one the
# template's own `if … else "pass"` branches exist for.
_CONTEXT: dict[str, object] = {
    "message": "add whatever",
    "up_revision": "cbdd2f9e4fd6",
    "down_revision": "0001_initial",
    "branch_labels": None,
    "depends_on": None,
    "create_date": "2026-08-11 12:00:00.000000",
    "imports": "",
    "upgrades": "",
    "downgrades": "",
}


def _render() -> str:
    rendered = Template(filename=str(TEMPLATE)).render(**_CONTEXT)
    assert isinstance(rendered, str)
    return rendered


def test_every_migration_is_parseable_python() -> None:
    """A stray file here stops `alembic upgrade head` from starting at all."""
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_the_revision_template_renders_parseable_python() -> None:
    ast.parse(_render(), filename=str(TEMPLATE))


def test_a_generated_migration_says_what_it_is() -> None:
    """The message and the revision it follows, in the file itself.

    Revision ids are opaque, so a migration whose docstring is just the message —
    or, worse, empty — leaves nothing on the page tying it to its place in the
    chain. Asserted on the parsed docstring rather than the raw text so that a
    template which puts the header outside the docstring still fails.
    """
    docstring = ast.get_docstring(ast.parse(_render()))
    assert docstring is not None
    assert "add whatever" in docstring
    assert "0001_initial" in docstring


def test_a_generated_migration_has_both_directions() -> None:
    """`downgrade` missing is a migration that cannot be rolled back."""
    module = ast.parse(_render())
    functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= functions.keys()
    # `mypy --strict` would reject an unannotated one, and a migration nobody can
    # type-check is a migration nobody reads before applying.
    assert all(node.returns is not None for node in functions.values())
