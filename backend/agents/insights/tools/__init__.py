"""Tool surface for the AI Insights agent.

Each tool lives in its own submodule (``query_database``, ``build_chart``,
``persist_insight``, …). Import the function from its submodule:

    from agents.insights.tools.persist_insight import persist_insight

The submodule names are deliberately NOT re-exported as function aliases
at the package level — that pattern would shadow the submodules in
``agents.insights.tools.X``, breaking ``mock.patch`` and any code that
needs the module object (e.g. to patch its dependencies).
"""

from .sql_gate import SqlGateError, ValidatedSQL, validate_sql  # noqa: F401
from .registry import TOOL_DEFS, dispatch  # noqa: F401
