---
name: pg-explorer
description: 只读 PostgreSQL 探查技能。探索 schema、表结构、索引、约束，执行只读查询及 EXPLAIN 分析。
---

# pg-explorer — 只读 PostgreSQL 探查

## 触发条件

用户提到以下任一场景时使用本技能：
- 查看数据库有哪些表、表结构
- 分析索引、约束、表大小
- 执行只读 SQL 查询
- EXPLAIN 分析查询性能

## 前置条件：连接管理

### 首次使用

1. 执行 `python3 scripts/pg-query.py conn list` 检查是否已有连接
2. 若无连接，向用户索要 PostgreSQL 连接 URL（格式：`postgresql://user:pass@host:port/dbname`）
3. **根据用户描述的用途拟定连接名**（如 `production`、`staging`、`analytics`），**向用户确认名称**
4. 用户确认后保存：`python3 scripts/pg-query.py conn add <名称> "<URL>"`

连接信息保存在项目根目录 `.agent-postgres-db-url.json`，密码在文件中以明文存储，权限设为 600。

### 后续使用

- 列出：`python3 scripts/pg-query.py conn list`
- 移除：`python3 scripts/pg-query.py conn remove <名称>`

无默认连接，每次查询须显式指定连接名。

## 命令速查

| 命令 | 用途 | 行数限制 |
|------|------|---------|
| `overview <连接名> --format <json\|markdown>` | 所有表：表名 + 注释 + 列数 + 大小 + 估算行数 | 无 |
| `table <连接名> <表名> --format <json\|markdown>` | 单表：列(含注释) + 索引 + 约束 | 无 |
| `indexes <连接名> --format <json\|markdown>` | 全局索引分布 | 无 |
| `query <连接名> -q "<SQL>" --format <json\|markdown>` | 执行只读查询 | 默认 5，上限 20 |
| `query <连接名> --explain -q "<SQL>" --format <json\|markdown>` | EXPLAIN ANALYZE | 无 |

## `--format` 必填

agent 根据使用场景自行选择：
- **json** — 需要解析数据做后续分析时（推荐，agent 直接读取 `columns`/`rows`）
- **markdown** — 直接给用户看的场景

agent 读取 JSON 后，可用 markdown 表格向用户呈现。

## 安全约束（脚本内部保障，agent 无需额外操作）

- **只读事务** — 脚本连接时自动设为 READ ONLY，数据库级别阻止写操作
- **关键词检测** — 脚本检测 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE 等关键词并拒绝
- **行数限制** — `query` 命令默认 5 行，上限 20 行；schema 探查命令不限制
- **语句超时** — 30 秒
- **密码保护** — 配置文件权限 600

## 环境依赖

`psycopg2-binary`。首次使用时如提示缺失，让用户执行：

```
pip install psycopg2-binary
```
