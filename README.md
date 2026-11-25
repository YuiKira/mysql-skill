# MySQL Skill

[中文](README.md) | [English](README.en.md)

**让 AI 执行 MySQL 增删改查，无需把数据库账号密码交给 AI。**

连接信息只需在本机配置一次，由本地 CLI 读取并建立连接，返回结果时对当前连接的地址、账号和密码进行脱敏。
AI 通过别名执行查询和数据修改，无需打开凭据文件或在对话中接收账密。适用于 **Codex、Claude Code 和 DeepSeek Harness（dsh）**。

## 功能

- 查询数据：单条只读 `SELECT` 和 `UNION`，MySQL 8.0+ 可使用 CTE。
- 增删改：`INSERT`、`UPDATE`、`DELETE`，支持批量插入、`INSERT SELECT`、`INSERT IGNORE` 和重复键更新。
- 写入成功自动提交，返回影响行数和自增 ID；失败尝试回滚，不自动重试。
- 查看结构：列出表、查看指定表的字段。
- 常用只读 SQL：`SHOW`、`DESCRIBE`、系统变量读取，以及常用查询函数。
- 执行计划：`EXPLAIN SELECT`，支持传统格式和 JSON 格式，不支持 `EXPLAIN ANALYZE`。
- 别名发现与本地诊断：不输出连接详情，不建立诊断连接。
- SSH 跳板访问：通过服务器别名查询，自动建立并清理本地隧道。
- 统一 JSON 输出、凭据脱敏、查询超时、行数和输出大小限制。
- 支持 Windows、macOS 和 Linux，要求 Python 3.10+、MySQL 5.5+，建议 MySQL 8.0+。

当前版本不支持 DDL、迁移、存储过程和 MariaDB。
建表、删表、授权、SET、CALL、文件读写和多语句同样会拦截。函数仍使用允许列表，
不会将未知存储函数或 UDF 当成安全查询。`SHOW GRANTS`、`SHOW CREATE USER` 不开放。

### MySQL 版本兼容

支持 `5.5.20-log`、`5.6.16-log`、`5.7.20` 等版本字符串，`-log` 后缀不影响识别。

| MySQL 版本 | 读取事务模式 | 查询超时 |
| --- | --- | --- |
| 5.5.x、5.6.0–5.6.4 | 普通事务 | 客户端读取超时 |
| 5.6.5–5.7.7 | 只读事务 | 客户端读取超时 |
| 5.7.8+ | 只读事务 | 服务端 SELECT 超时与客户端读取超时 |

写入在所有支持版本上使用普通事务，超时使用客户端读取限制。账号按实际用途授予权限，
只读账号仍可正常查询。客户端超时不会取消服务端正在执行的操作。
SQL 语法以目标版本为准：CTE、窗口函数需要 MySQL 8.0+，JSON 函数需要 5.7+。

## 安装

使用 [skills CLI](https://github.com/vercel-labs/skills) 安装，需先安装 Node.js：

```sh
npx skills add YuiKira/mysql-skill
```

指定 Codex 和 Claude Code，并安装到个人技能目录：

```sh
npx skills add YuiKira/mysql-skill --skill mysql-skill --agent codex claude-code --global
```

安装后仍需按下文安装 Python 依赖并配置本地连接。DeepSeek Harness 可使用共享目录
`~/.agents/skills/mysql-skill`，或按下面的路径手动安装。

也可以从 [Releases](https://github.com/YuiKira/mysql-skill/releases) 下载 ZIP，
将完整仓库解压或复制到对应工具的技能目录，目录名使用 `mysql-skill`：

| 工具 | 个人技能路径 |
| --- | --- |
| Codex | `~/.agents/skills/mysql-skill` |
| Claude Code | `~/.claude/skills/mysql-skill` |
| DeepSeek Harness | `~/.dsh/skills/mysql-skill` 或 `~/.agents/skills/mysql-skill` |

`~` 表示用户主目录。Codex 与 DeepSeek Harness 可共用 `.agents/skills` 中的一份安装。
DeepSeek Harness 自定义组合需要启用 `@deepseek-ai/dsh-skill`、`@deepseek-ai/dsh-skill-filesystem` 和 `@deepseek-ai/dsh-tool-skill`；路径可由 `DSH_HOME`、`DSH_AGENTS_HOME` 调整。

在技能目录创建虚拟环境并安装依赖：

Windows PowerShell：

```powershell
python -m venv .venv
& ".venv/Scripts/python.exe" -m pip install -r "requirements.txt"
& ".venv/Scripts/python.exe" "scripts/mysql_skill.py" doctor --json
```

macOS / Linux：

```sh
python3 -m venv .venv
".venv/bin/python" -m pip install -r "requirements.txt"
".venv/bin/python" "scripts/mysql_skill.py" doctor --json
```

AI 优先使用技能目录内该虚拟环境的 Python，避免误用缺少依赖的系统 Python。
若工具尚未发现技能，重新加载技能或启动新会话。

## 本地连接配置

手动将 `config/connections.example.json` 复制到 `~/.mysql-skill/connections.json`，然后在本机编辑器中填写真实值。示例值均为虚构值：

```json
{
  "version": 1,
  "connections": {
    "business": {
      "host": "db.example.invalid",
      "port": 3306,
      "user": "example_reader",
      "password": "replace-locally",
      "database": "example_app"
    }
  }
}
```

密码允许本地明文保存。账号按实际用途授予 `SELECT`、`INSERT`、`UPDATE`、`DELETE` 权限，并将配置文件访问权限限制为本机用户。不要把真实配置提交到 Git、发送到对话，或让 AI 打开文件。

已有版本 1 的连接配置直接生效，无需重新添加别名或新增配置字段。升级 skill 不会改变数据库授权；
只有 `SELECT` 权限的账号可以继续查询，执行写入会返回 `access_denied`。

可通过 `MYSQL_SKILL_CONFIG` 或全局参数 `--config "<PATH>"` 指定配置路径；`--config` 必须放在子命令之前。AI 通过 `config list` 获取别名。

直连网络数据库时配置可验证的 TLS：在连接项中添加 `"tls": {"ca": "/local/path/ca.pem"}`；双向 TLS 可额外添加配对的 `cert` 和 `key` 路径。未配置 `tls` 时不主动启用 TLS。

需要通过跳板机访问时，安装 SSH skill v4，在查询命令中添加 `--via <SSH别名>`。
数据库配置保留跳板机可访问的目标地址和端口，无需改成本机地址。
程序内部建立本地隧道、执行查询并清理，不向远程服务器传递数据库账密或 SQL。
隧道保留原数据库主机名用于 TLS 校验。

默认查找同级 `ssh-skill`，然后查找用户 `.agents`、`.codex`、`.claude`、`.dsh`
下的技能目录。自定义安装可设置 `MYSQL_SKILL_SSH_ROOT`；SSH 使用独立 Python 时可设置
`MYSQL_SKILL_SSH_PYTHON`。默认优先使用 SSH skill 自己的 `.venv`，否则使用当前 Python
的基础解释器，SSH 依赖需安装在对应环境中。

技能约束正常调用流程不读取凭据，不提供操作系统级文件隔离。脚本会在输出中替换连接地址、用户名和密码的原文匹配，包括查询结果中的匹配值；业务数据本身仍需按授权范围查询。

## 使用方法

直接向 AI 描述目标，例如：

> 使用 MySQL 的 business 别名，查看有哪些订单表。
>
> 查询 business 库最近 10 笔失败订单，只返回订单号、状态和创建时间。
>
> 通过 jump 服务器查询 business 库的订单表结构。
>
> 将 business 库订单 42 的状态改为 done。

命令行示例，`<PYTHON>` 替换为虚拟环境 Python 路径：

```text
<PYTHON> "scripts/mysql_skill.py" config list
<PYTHON> "scripts/mysql_skill.py" schema --alias business
<PYTHON> "scripts/mysql_skill.py" schema --alias business --table orders
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SELECT id, status FROM orders ORDER BY id DESC LIMIT 10"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql-file "query.sql" --limit 100 --timeout 15
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SHOW TABLES"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "DESCRIBE orders"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SHOW INDEX FROM orders"
<PYTHON> "scripts/mysql_skill.py" explain --alias business --sql "SELECT id FROM orders WHERE id = 42"
<PYTHON> "scripts/mysql_skill.py" explain --alias business --sql-file "query.sql" --format json
<PYTHON> "scripts/mysql_skill.py" query --alias business --via jump --sql "SELECT 1"
<PYTHON> "scripts/mysql_skill.py" schema --alias business --via jump --table orders
<PYTHON> "scripts/mysql_skill.py" explain --alias business --via jump --sql "SELECT id FROM orders WHERE id = 42"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "INSERT INTO orders (id, status) VALUES (42, 'new')"
<PYTHON> "scripts/mysql_skill.py" query --alias business --via jump --sql "UPDATE orders SET status = 'done' WHERE id = 42"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "DELETE FROM orders WHERE id = 42"
```

每次 `query` 只执行一条语句。增删改返回 `affected_rows`、`last_insert_id`（没有时为 null）、
`committed` 和 `execution`。成功提交后 `committed=true`；影响行数沿用 MySQL 语义，
更新为相同值可能返回 0，重复键更新可能返回 2。`--limit` 只限制 SELECT 返回行数，
不会限制写入行数或改写 `INSERT SELECT`。需要限制修改范围时，在 SQL 中明确 WHERE 或 LIMIT。

写入失败会尝试回滚；回滚能力取决于表引擎，InnoDB 支持事务，非事务表无法依靠回滚撤销。
若返回 `write_outcome_unknown`，先核对实际数据，再决定后续操作，不自动重放写入。

`--via` 适用于 `query`、`schema` 和 `explain`，每次调用独立建立并清理隧道，
不修改原连接配置。SSH 原始输出由程序内部接收；隧道进程参数包含目标地址，
不包含数据库账号密码。清理未确认时，`meta.warnings` 返回需要处理的隧道 ID，
查询结果或原错误仍会保留。SSH 操作单独设有 45 秒超时，超时后先检查隧道状态，
不自动重试或改用远程 SQL。

也可以用 `query --sql "EXPLAIN SELECT ..."`。传统执行计划兼容 MySQL 5.5+，
JSON 格式需要 MySQL 5.6.5+。执行计划保留原 SQL 的 LIMIT；`--limit` 只限制返回的
计划行数。SHOW/DESCRIBE 不追加 SQL LIMIT，返回结果仍受行数和输出大小限制。
JSON 计划作为文本单元格返回，可能被截断，请检查 `cells_truncated`。
每次调用使用独立连接，SHOW WARNINGS/ERRORS 无法查看上次调用的诊断信息。

默认返回 100 行，最多 1,000 行；`--timeout` 默认为 15 秒，最多 60 秒。MySQL 5.7.8+ 将其用于服务端 SELECT 超时，写入不使用该服务端超时；所有版本的客户端读取超时为该值加 5 秒，属于单次读取等待限制，并非整体执行期限。CLI 将读取 SELECT 的顶层 `LIMIT` 收紧到返回上限加 1，保留更小的原有上限和偏移。扫描、排序和聚合仍可能处理更多行。

查询结果的 `execution` 字段返回规范化版本号、是否启用只读事务、超时模式及该模式的超时秒数，不返回原始服务端版本字符串。

输出上限为 256 KiB，单元格文本上限为 4,096 个字符，二进制内容仅返回大小标记。结果中的 `truncated` 和 `cells_truncated` 表示截断。所有操作（除 `--help`）输出单个 JSON；失败退出码为 1，不包含原始驱动异常，也不会自动重试。

完整参数和错误码见 [命令参考](references/commands.md)。

## 测试

使用安装了依赖的 Python：

```text
<PYTHON> -m unittest discover -s tests -v
```

默认测试使用虚构配置和模拟连接；集成测试默认跳过。只有设置
`MYSQL_SKILL_TEST_PORT` 后才会连接本机隔离测试实例；可选
`MYSQL_SKILL_TEST_PASSWORD` 指定该测试实例的 root 密码。不要指向业务实例。
GitHub Actions 配置了独立的 MySQL 5.5、5.6、5.7 和 8.0 服务用于集成测试。
增删改测试在隔离实例内创建临时 InnoDB 表和只读账号，验证提交、失败回滚和权限限制后清理。

## 开源协议

采用 [MIT License](LICENSE)。

## 工具文档

- [Codex Skills](https://developers.openai.com/codex/skills/)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [DeepSeek Harness Skill Filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)
