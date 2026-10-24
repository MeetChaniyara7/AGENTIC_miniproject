"""Static safety check for LLM-written SQL, using sqlglot (SQLite dialect).

validate_sql(sql) -> (ok, cleaned_sql, error, requires_approval)

Layers of defence (the executor adds a read-only connection and a timeout):
  1. exactly one statement, and it must be a SELECT (or UNION/INTERSECT/EXCEPT of SELECTs)
  2. no comments (a classic way to hide a second statement)
  3. tables must be on the allow-list in config.py; no schema-qualified names, no table-valued functions
  4. LIMIT is always present and never above SQL_ROW_LIMIT
  5. sensitive columns outside an aggregate set requires_approval

Error strings are written for an LLM to read and repair the query from.
"""
from __future__ import annotations

import difflib
from typing import NamedTuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from config import ALLOWED_TABLES, SENSITIVE_COLUMNS, SQL_ROW_LIMIT

MAX_SQL_CHARS = 4000

# Node types that can never appear in a read-only query. getattr() because not every
# sqlglot version defines every class (e.g. Detach).
_FORBIDDEN = tuple(
    getattr(exp, name) for name in
    ("Insert", "Update", "Delete", "Drop", "Create", "Alter", "Command", "Pragma",
     "Attach", "Detach", "Merge", "Set", "Transaction", "Commit", "Rollback")
    if hasattr(exp, name)
)
# SQLite functions that load code or allocate huge blobs.
_FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer",
                        "zeroblob", "randomblob"}


class ValidationResult(NamedTuple):
    ok: bool
    cleaned_sql: str          # "" when not ok
    error: str | None         # None when ok
    requires_approval: bool


def _reject(error: str) -> ValidationResult:
    return ValidationResult(False, "", error, False)


def _real_tables(root: exp.Expression) -> tuple[set[str], list[str], str | None]:
    """Return (tables used, unknown tables, structural error) ignoring CTE names."""
    cte_names = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    used, unknown = set(), []
    for tbl in root.find_all(exp.Table):
        if not isinstance(tbl.this, exp.Identifier):
            return used, unknown, ("Table-valued functions (e.g. pragma_table_info, json_each) are not allowed. "
                                   "Select only from the real tables.")
        if tbl.args.get("db") or tbl.args.get("catalog"):
            return used, unknown, (f"Schema-qualified table '{tbl.sql(dialect='sqlite')}' is not allowed. "
                                   f"Use the bare table name, e.g. '{tbl.name}'.")
        name = tbl.name.lower()
        if name in cte_names:
            continue
        used.add(name)
        if name not in ALLOWED_TABLES:
            unknown.append(tbl.name)
    return used, unknown, None


def _unknown_table_error(unknown: list[str]) -> str:
    parts = []
    for name in unknown:
        close = difflib.get_close_matches(name.lower(), sorted(ALLOWED_TABLES), n=1)
        parts.append(f"'{name}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
    return (f"Unknown table(s): {', '.join(parts)}. "
            f"Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}.")


def _sensitive_hits(root: exp.Expression, tables: set[str]) -> list[str]:
    """Sensitive columns used outside an aggregate (COUNT(DISTINCT customer_unique_id) is fine)."""
    sensitive_here = {c for t in tables for c in SENSITIVE_COLUMNS.get(t, ())}
    hits = []
    for col in root.find_all(exp.Column):
        if col.name.lower() in sensitive_here and not col.find_ancestor(exp.AggFunc):
            hits.append(col.name.lower())
    for star in root.find_all(exp.Star):
        if star.find_ancestor(exp.AggFunc):
            continue
        # A star only exposes the tables its own SELECT reads directly. `SELECT * FROM some_cte`
        # exposes whatever the CTE selected, which is checked where the CTE is defined.
        owner = star.find_ancestor(exp.Select)
        direct = [t for t in owner.find_all(exp.Table) if t.find_ancestor(exp.Select) is owner]
        if isinstance(star.parent, exp.Column) and star.parent.table:   # `o.*` exposes only the table aliased o
            alias = star.parent.table.lower()
            direct = [t for t in direct if t.alias_or_name.lower() == alias]
        for table in direct:
            hits.extend(SENSITIVE_COLUMNS.get(table.name.lower(), ()))
    return sorted(set(hits))


def _apply_limit(root: exp.Expression) -> str | None:
    """Ensure an outer LIMIT <= SQL_ROW_LIMIT. Returns an error string or None."""
    limit = root.args.get("limit")
    if limit is None:
        root.set("limit", exp.Limit(expression=exp.Literal.number(SQL_ROW_LIMIT)))
        return None
    value = limit.expression
    # LIMIT -1 means "no limit" in SQLite, so only plain non-negative integers are accepted.
    if not (isinstance(value, exp.Literal) and not value.is_string and value.name.isdigit()):
        return ("LIMIT must be a non-negative integer literal such as LIMIT 50 "
                "(note: LIMIT -1 means unlimited in SQLite and is not allowed).")
    if int(value.name) > SQL_ROW_LIMIT:
        root.set("limit", exp.Limit(expression=exp.Literal.number(SQL_ROW_LIMIT)))
    return None


def validate_sql(sql: str) -> ValidationResult:
    if not isinstance(sql, str) or not sql.strip():
        return _reject("Empty query. Provide one SELECT statement.")
    if len(sql) > MAX_SQL_CHARS:
        return _reject(f"Query is too long ({len(sql)} characters, max {MAX_SQL_CHARS}). Simplify it.")

    try:
        if any(tok.comments for tok in sqlglot.tokenize(sql, read="sqlite")):
            return _reject("SQL comments (-- or /* */) are not allowed. Remove them and resend the query.")
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except (ParseError, TokenError) as e:
        # sqlglot's own wording can mention internal classes, so add a plain-language hint.
        return _reject(f"SQL syntax error (SQLite dialect): {str(e).splitlines()[0]} "
                       "Check keyword spelling, balanced parentheses and commas, and that the query "
                       "starts with SELECT or WITH.")

    if not statements:
        return _reject("Empty query. Provide one SELECT statement.")
    if len(statements) > 1:
        return _reject(f"Multiple statements found ({len(statements)}). Send exactly one SELECT statement "
                       "and remove everything after the first semicolon.")

    root = statements[0]
    if not isinstance(root, (exp.Select, exp.SetOperation)):
        return _reject(f"Only SELECT queries are allowed, but this is a {root.key.upper()} statement. "
                       "Rewrite it as a read-only SELECT.")
    bad = next((n for n in root.walk() if isinstance(n, _FORBIDDEN)), None)
    if bad is not None:
        return _reject(f"{bad.key.upper()} is not allowed inside a query. Use only SELECT.")
    for node in root.find_all(exp.Anonymous):
        if node.name.lower() in _FORBIDDEN_FUNCTIONS:
            return _reject(f"Function {node.name}() is not allowed.")

    tables, unknown, structural_error = _real_tables(root)
    if structural_error:
        return _reject(structural_error)
    if unknown:
        return _reject(_unknown_table_error(unknown))
    if not tables:
        return _reject("The query reads no table. Query one of: " + ", ".join(sorted(ALLOWED_TABLES)) + ".")

    limit_error = _apply_limit(root)
    if limit_error:
        return _reject(limit_error)

    return ValidationResult(True, root.sql(dialect="sqlite"), None, bool(_sensitive_hits(root, tables)))


def find_sensitive(sql: str) -> list[str]:
    """Names of sensitive columns a query touches (for showing a reason in the approval prompt)."""
    res = validate_sql(sql)
    if not res.ok:
        return []
    root = sqlglot.parse_one(res.cleaned_sql, read="sqlite")
    return _sensitive_hits(root, _real_tables(root)[0])
