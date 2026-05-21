#!/usr/bin/env python3
"""pg-explorer — 只读 PostgreSQL 探查引擎。一个脚本，SQL 全部内联。"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse

# ── 常量 ──────────────────────────────────────────────────────────
CONFIG_FILE = ".agent-postgres-db-url.json"
QUERY_DEFAULT_LIMIT = 5
QUERY_MAX_LIMIT = 20
QUERY_TIMEOUT_MS = 30000

# ── 内嵌 SQL ──────────────────────────────────────────────────────

SQL_OVERVIEW = """
SELECT
  t.table_name,
  pg_catalog.obj_description(pc.oid, 'pg_class') AS comment,
  (SELECT count(*) FROM information_schema.columns c
   WHERE c.table_schema = t.table_schema AND c.table_name = t.table_name) AS column_count,
  pg_size_pretty(pg_total_relation_size(format('%I.%I', t.table_schema, t.table_name))) AS total_size,
  pc.reltuples::bigint AS estimated_rows
FROM information_schema.tables t
JOIN pg_catalog.pg_class pc
  ON pc.relname = t.table_name
 AND pc.relnamespace = (SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = t.table_schema)
WHERE t.table_type = 'BASE TABLE'
  AND t.table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(format('%I.%I', t.table_schema, t.table_name)) DESC
"""

SQL_TABLE_COLUMNS = """
SELECT
  a.attnum AS ordinal,
  a.attname AS column_name,
  pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
  CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS nullable,
  pg_get_expr(d.adbin, d.adrelid) AS default_value,
  pg_catalog.col_description(a.attrelid, a.attnum) AS comment
FROM pg_catalog.pg_attribute a
LEFT JOIN pg_catalog.pg_attrdef d ON a.attrelid = d.adrelid AND a.attnum = d.adnum
WHERE a.attrelid = %s::regclass
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

SQL_TABLE_INDEXES = """
SELECT
  i.relname AS index_name,
  am.amname AS index_method,
  ix.indisunique AS is_unique,
  pg_get_indexdef(ix.indexrelid) AS definition,
  pg_size_pretty(pg_relation_size(i.oid)) AS index_size
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_am am ON am.oid = i.relam
WHERE t.oid = %s::regclass
ORDER BY ix.indisprimary DESC, i.relname
"""

SQL_TABLE_CONSTRAINTS = """
SELECT
  tc.constraint_name,
  tc.constraint_type,
  array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS columns,
  ccu.table_name AS foreign_table,
  array_agg(ccu.column_name ORDER BY kcu.ordinal_position) AS foreign_columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
 AND tc.table_name = kcu.table_name
LEFT JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.table_schema = ccu.table_schema
WHERE tc.table_schema = %s AND tc.table_name = %s
GROUP BY tc.constraint_name, tc.constraint_type, ccu.table_name
ORDER BY tc.constraint_type, tc.constraint_name
"""

SQL_TABLE_COMMENT = """
SELECT pg_catalog.obj_description(c.oid, 'pg_class')
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname = %s AND n.nspname NOT IN ('pg_catalog', 'information_schema')
LIMIT 1
"""

SQL_INDEXES_GLOBAL = """
SELECT
  n.nspname AS schema_name,
  t.relname AS table_name,
  i.relname AS index_name,
  am.amname AS index_method,
  ix.indisunique AS is_unique,
  pg_get_indexdef(i.oid) AS definition,
  pg_size_pretty(pg_relation_size(i.oid)) AS index_size
FROM pg_index ix
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_am am ON am.oid = i.relam
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY n.nspname, t.relname, ix.indisprimary DESC, i.relname
"""

# ── 工具函数 ──────────────────────────────────────────────────────

def _find_config():
    cwd = os.getcwd()
    while True:
        p = os.path.join(cwd, CONFIG_FILE)
        if os.path.exists(p):
            return p
        parent = os.path.dirname(cwd)
        if parent == cwd:
            return os.path.join(os.getcwd(), CONFIG_FILE)
        cwd = parent


def _load_config():
    path = _find_config()
    if not os.path.exists(path):
        return None, path
    with open(path) as f:
        return json.load(f), path


def _save_config(cfg, path):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _parse_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"不支持的 scheme: {u.scheme}")
    return {
        "user": u.username or "postgres",
        "password": u.password or "",
        "host": u.hostname or "localhost",
        "port": u.port or 5432,
        "database": u.path.lstrip("/") or "postgres",
        "params": dict(urllib.parse.parse_qsl(u.query)) if u.query else {},
    }


def _clean_sql(sql):
    sql = sql.replace("\r\n", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", sql).strip()


def _check_read_only(sql):
    allowed = ("SELECT", "EXPLAIN", "WITH", "SHOW", "SET", "BEGIN", "COMMIT", "ROLLBACK")
    upper = sql.strip().upper()
    if not any(upper.startswith(p) for p in allowed):
        return False, f"只允许只读操作，'{upper.split()[0]}' 疑似写操作"
    danger = re.findall(
        r"\b(INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|DROP\s+(TABLE|INDEX|VIEW|SCHEMA|DATABASE)|"
        r"ALTER\s+(TABLE|INDEX|VIEW|SCHEMA)|TRUNCATE|CREATE\s+(TABLE|INDEX|VIEW|SCHEMA)|"
        r"GRANT|REVOKE|VACUUM|ANALYZE|REINDEX|CLUSTER)\b",
        upper,
    )
    if danger:
        return False, f"疑似的写操作关键词: {danger[0][0].strip()}"
    return True, ""


def _connect(conn_info, timeout_ms):
    import psycopg2
    dsn = (
        f"host={conn_info['host']} port={conn_info['port']} "
        f"dbname={conn_info['database']} "
        f"user={conn_info['user']} password={conn_info['password']} "
        f"connect_timeout={max(timeout_ms // 1000, 5)}"
    )
    sm = conn_info.get("params", {}).get("sslmode")
    if sm and sm != "prefer":
        dsn += f" sslmode={sm}"
    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True)
    return conn


def _row_to_list(row):
    result = []
    for v in row:
        if v is None:
            result.append(None)
        elif isinstance(v, (str, int, float, bool)):
            result.append(v)
        elif isinstance(v, bytes):
            result.append(f"<bytes {len(v)}>")
        elif hasattr(v, "isoformat"):
            result.append(v.isoformat())
        else:
            result.append(str(v))
    return result


def _fetch(cur, sql, params=None, limit=None):
    """在已创建的 cursor 上执行查询，返回 {columns, rows}。"""
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    columns = [d.name for d in cur.description] if cur.description else []
    if limit and limit > 0:
        raw = cur.fetchmany(limit)
        truncated = cur.fetchone() is not None
        rows = [_row_to_list(r) for r in raw]
    else:
        raw = cur.fetchall()
        rows = [_row_to_list(r) for r in raw]
        truncated = False
    return {"columns": columns, "rows": rows, "count": len(rows), "truncated": truncated}


def _run_one(conn_info, sql, params=None, limit=None, timeout_ms=QUERY_TIMEOUT_MS, explain=False):
    """单次查询：连接 → 执行 → 关闭连接 → 返回结果。"""
    conn = _connect(conn_info, timeout_ms)
    start = time.time()
    try:
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout TO {timeout_ms}")
        if explain:
            sql = f"EXPLAIN (ANALYZE, COSTS, VERBOSE, BUFFERS, FORMAT JSON) {sql}"
            limit = None
        result = _fetch(cur, sql, params, limit)
        result["elapsed_ms"] = round((time.time() - start) * 1000, 1)
        result["success"] = True
        result["explain"] = explain
        return result
    except Exception as e:
        return {
            "success": False, "error": str(e),
            "elapsed_ms": round((time.time() - start) * 1000, 1),
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _run_multi(conn_info, queries, timeout_ms=QUERY_TIMEOUT_MS):
    """单连接多次查询，每个 query 是 (sql, params, limit)。返回结果列表。"""
    conn = _connect(conn_info, timeout_ms)
    start = time.time()
    results = []
    try:
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout TO {timeout_ms}")
        for sql, params, limit in queries:
            r = _fetch(cur, sql, params, limit)
            r["elapsed_ms"] = round((time.time() - start) * 1000, 1)
            r["success"] = True
            results.append(r)
        return results
    except Exception as e:
        return [{
            "success": False, "error": str(e),
            "elapsed_ms": round((time.time() - start) * 1000, 1),
        }]
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Markdown 格式化 ───────────────────────────────────────────────

def _md_table(columns, rows):
    if not columns:
        return "(无数据)"
    widths = [len(c) for c in columns]
    for row in rows:
        for i, cell in enumerate(row):
            w = len(str(cell)) if cell is not None else 4
            if i < len(widths):
                widths[i] = max(widths[i], w)
    header = "| " + " | ".join(c.ljust(w) for c, w in zip(columns, widths)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    body = "\n".join(
        "| " + " | ".join(
            (str(v) if v is not None else "NULL").ljust(widths[min(i, len(widths) - 1)])
            for i, v in enumerate(row)
        ) + " |"
        for row in rows
    )
    return f"{header}\n{sep}\n{body}"


def _fmt_overview_md(result):
    rows = result["rows"]
    lines = ["# 数据库概览\n"]
    lines.append(f"共 {len(rows)} 张表")
    if rows:
        lines.append("")
        lines.append(_md_table(
            ["表名", "注释", "列数", "大小", "估算行数"],
            [r for r in rows],
        ))
    return "\n".join(lines)


def _fmt_table_md(cols, idxs, csts, table_name, table_comment):
    lines = [f"# 表: {table_name}\n"]
    if table_comment:
        lines.append(f"表注释: {table_comment}")
    lines.append("")

    if cols["rows"]:
        lines.append(f"## 列 ({cols['count']})\n")
        lines.append(_md_table(cols["columns"], cols["rows"]))
        lines.append("")

    if idxs["rows"]:
        lines.append(f"## 索引 ({idxs['count']})\n")
        lines.append(_md_table(idxs["columns"], idxs["rows"]))
        lines.append("")

    if csts["rows"]:
        lines.append(f"## 约束 ({csts['count']})\n")
        lines.append(_md_table(csts["columns"], csts["rows"]))

    return "\n".join(lines)


def _fmt_indexes_md(result):
    lines = [f"# 全局索引 ({result['count']} 个)\n"]
    if result["rows"]:
        lines.append(_md_table(result["columns"], result["rows"]))
    else:
        lines.append("(无用户索引)")
    return "\n".join(lines)


def _fmt_query_md(result):
    lines = []
    if result.get("explain"):
        lines.append("# EXPLAIN ANALYZE\n")
        lines.append("```json")
        for r in result["rows"]:
            lines.append(str(r[0]))
        lines.append("```")
    else:
        lines.append("# 查询结果\n")
        if result["rows"]:
            lines.append(_md_table(result["columns"], result["rows"]))
            lines.append("")
            if result.get("truncated"):
                lines.append(f"> 返回 {result['count']} 行，已截断")
            else:
                lines.append(f"> 共 {result['count']} 行")
        else:
            lines.append("(无结果)")
    lines.append(f"\n> 耗时 {result['elapsed_ms']}ms")
    return "\n".join(lines)


def _output_json(result):
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def _output_md(result, fmt_func):
    if not result.get("success"):
        print(f"## 错误\n\n{result.get('error', '未知错误')}")
    else:
        print(fmt_func(result))


# ── 故障处理 ──────────────────────────────────────────────────────

def _fail(msg):
    print(json.dumps({"success": False, "error": msg}))
    sys.exit(1)


def _require_driver():
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        _fail("psycopg2-binary 未安装。请执行: pip install psycopg2-binary")


def _get_conn(config, name):
    if not config or "connections" not in config or name not in config["connections"]:
        available = list(config["connections"].keys()) if config and "connections" in config else []
        msg = f"未找到连接 '{name}'"
        if available:
            msg += f"，可用: {', '.join(available)}"
        _fail(msg)
    return config["connections"][name]


# ── 子命令：conn ──────────────────────────────────────────────────

def cmd_conn_list():
    cfg, _ = _load_config()
    if not cfg or "connections" not in cfg:
        print(json.dumps({"success": True, "connections": []}))
        return
    result = []
    for name, info in cfg["connections"].items():
        safe = re.sub(r":([^@]+)@", ":****@", info["url"])
        result.append({"name": name, "url": safe, "description": info.get("description", "")})
    print(json.dumps({"success": True, "connections": result}, indent=2, ensure_ascii=False))


def cmd_conn_add(name, url):
    cfg, path = _load_config()
    if not cfg:
        cfg = {"connections": {}}
    parsed = _parse_url(url)
    cfg["connections"][name] = {
        "url": url,
        "description": f"{parsed['database']} @ {parsed['host']}:{parsed['port']}",
    }
    _save_config(cfg, path)
    print(json.dumps({"success": True, "action": "add", "name": name, "path": path},
                     indent=2, ensure_ascii=False))


def cmd_conn_remove(name):
    cfg, path = _load_config()
    if not cfg or "connections" not in cfg or name not in cfg["connections"]:
        _fail(f"连接 '{name}' 不存在")
    del cfg["connections"][name]
    _save_config(cfg, path)
    print(json.dumps({"success": True, "action": "remove", "name": name}))


# ── 子命令：overview ──────────────────────────────────────────────

def cmd_overview(conn_name, fmt):
    cfg, _ = _load_config()
    cinfo = _parse_url(_get_conn(cfg, conn_name)["url"])
    result = _run_one(cinfo, SQL_OVERVIEW)
    result["connection"] = conn_name
    if fmt == "json":
        _output_json(result)
    else:
        _output_md(result, _fmt_overview_md)


# ── 子命令：table ─────────────────────────────────────────────────

def cmd_table(conn_name, table_name, fmt):
    cfg, _ = _load_config()
    cinfo = _parse_url(_get_conn(cfg, conn_name)["url"])

    # 先查询表所属 schema
    schema_result = _run_one(cinfo,
        "SELECT n.nspname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relname = %s AND n.nspname NOT IN ('pg_catalog', 'information_schema')",
        params=(table_name,))
    if not schema_result.get("success") or not schema_result["rows"]:
        _fail(f"未找到表 '{table_name}'")
    schema_name = schema_result["rows"][0][0]

    full_name = f"{schema_name}.{table_name}"

    results = _run_multi(cinfo, [
        (SQL_TABLE_COLUMNS, (full_name,), None),
        (SQL_TABLE_INDEXES, (full_name,), None),
        (SQL_TABLE_CONSTRAINTS, (schema_name, table_name), None),
        (SQL_TABLE_COMMENT, (table_name,), 1),
    ])

    if not results[0].get("success"):
        _fail(f"查询失败: {results[0].get('error')}")

    cols, idxs, csts, cmt = results
    comment = cmt["rows"][0][0] if cmt["rows"] else ""

    if fmt == "json":
        _output_json({
            "success": True, "connection": conn_name, "table": f"{schema_name}.{table_name}",
            "schema": schema_name,
            "comment": comment,
            "columns": {"columns": cols["columns"], "rows": cols["rows"]},
            "indexes": {"columns": idxs["columns"], "rows": idxs["rows"]},
            "constraints": {"columns": csts["columns"], "rows": csts["rows"]},
        })
    else:
        print(_fmt_table_md(cols, idxs, csts, f"{schema_name}.{table_name}", comment))


# ── 子命令：indexes ───────────────────────────────────────────────

def cmd_indexes(conn_name, fmt):
    cfg, _ = _load_config()
    cinfo = _parse_url(_get_conn(cfg, conn_name)["url"])
    result = _run_one(cinfo, SQL_INDEXES_GLOBAL)
    result["connection"] = conn_name
    if fmt == "json":
        _output_json(result)
    else:
        _output_md(result, _fmt_indexes_md)


# ── 子命令：query ─────────────────────────────────────────────────

def cmd_query(conn_name, sql, limit, timeout_ms, explain, fmt):
    sql = _clean_sql(sql)
    ok, err = _check_read_only(sql)
    if not ok:
        _fail(err)
    limit = min(limit, QUERY_MAX_LIMIT)
    if limit <= 0:
        limit = QUERY_DEFAULT_LIMIT

    cfg, _ = _load_config()
    cinfo = _parse_url(_get_conn(cfg, conn_name)["url"])
    result = _run_one(cinfo, sql, limit=limit, timeout_ms=timeout_ms, explain=explain)
    result["connection"] = conn_name
    result["limit"] = limit if not explain else None

    if fmt == "json":
        _output_json(result)
    else:
        _output_md(result, _fmt_query_md)


# ── 入口 ──────────────────────────────────────────────────────────

def main():
    _require_driver()

    parser = argparse.ArgumentParser(description="pg-explorer — 只读 PostgreSQL 探查引擎")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    # conn
    conn_p = sub.add_parser("conn", help="连接管理")
    conn_sub = conn_p.add_subparsers(dest="subcmd")
    conn_sub.required = True
    conn_sub.add_parser("list", help="列出所有连接")
    pa = conn_sub.add_parser("add", help="添加连接"); pa.add_argument("name"); pa.add_argument("url")
    pr = conn_sub.add_parser("remove", help="移除连接"); pr.add_argument("name")

    # overview / indexes
    for cmd_name in ("overview", "indexes"):
        p = sub.add_parser(cmd_name)
        p.add_argument("connection")
        p.add_argument("--format", required=True, choices=["json", "markdown"])

    # table
    tp = sub.add_parser("table")
    tp.add_argument("connection")
    tp.add_argument("name", help="表名")
    tp.add_argument("--format", required=True, choices=["json", "markdown"])

    # query
    qp = sub.add_parser("query")
    qp.add_argument("connection")
    qp.add_argument("-q", "--sql", required=True)
    qp.add_argument("--limit", type=int, default=QUERY_DEFAULT_LIMIT)
    qp.add_argument("--timeout", type=int, default=QUERY_TIMEOUT_MS)
    qp.add_argument("--explain", action="store_true")
    qp.add_argument("--format", required=True, choices=["json", "markdown"])

    args = parser.parse_args()

    if args.command == "conn":
        if args.subcmd == "list":
            cmd_conn_list()
        elif args.subcmd == "add":
            cmd_conn_add(args.name, args.url)
        elif args.subcmd == "remove":
            cmd_conn_remove(args.name)
    elif args.command == "overview":
        cmd_overview(args.connection, args.format)
    elif args.command == "table":
        cmd_table(args.connection, args.name, args.format)
    elif args.command == "indexes":
        cmd_indexes(args.connection, args.format)
    elif args.command == "query":
        cmd_query(args.connection, args.sql, args.limit, args.timeout, args.explain, args.format)


if __name__ == "__main__":
    main()
