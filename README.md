# MySQL Skill

[中文](README.md) | [English](README.en.md)

通过本地别名查询 MySQL，适用于 **Codex、Claude Code 和 DeepSeek Harness（dsh）**。
连接地址、账号和密码保存在本机明文配置中，由 Python CLI 内部读取；AI 使用别名，无需读取真实配置。

## 功能

- 查询数据：单条只读 `SELECT` 和 `UNION`，MySQL 8.0+ 可使用 CTE。
- 查看结构：列出表、查看指定表的字段。
- 别名发现与本地诊断：不输出连接详情，不建立诊断连接。
- 统一 JSON 输出、凭据脱敏、查询超时、行数和输出大小限制。
- 支持 Windows、macOS 和 Linux，要求 Python 3.10+、MySQL 5.5+，建议 MySQL 8.0+。

当前版本不支持写操作、迁移、存储过程和 MariaDB。

### MySQL 版本兼容

支持 `5.5.20-log`、`5.6.16-log`、`5.7.20` 等版本字符串，`-log` 后缀不影响识别。

| MySQL 版本 | 事务模式 | 查询超时 |
| --- | --- | --- |
| 5.5.x、5.6.0–5.6.4 | 普通事务，依靠专用账号的 SELECT 权限限制写入 | 客户端读取超时 |
| 5.6.5–5.7.7 | 只读事务 | 客户端读取超时 |
| 5.7.8+ | 只读事务 | 服务端 SELECT 超时与客户端读取超时 |

所有版本均应使用专用只读账号。旧版本的客户端超时不会取消服务端查询。
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

让 AI 使用该虚拟环境的 Python 执行 CLI。若工具尚未发现技能，重新加载技能或启动新会话。

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

密码允许本地明文保存。使用只有 `SELECT` 权限的专用账号，并将配置文件访问权限限制为本机用户。不要把真实配置提交到 Git、发送到对话，或让 AI 打开文件。

可通过 `MYSQL_SKILL_CONFIG` 或全局参数 `--config "<PATH>"` 指定配置路径；`--config` 必须放在子命令之前。AI 通过 `config list` 获取别名。

直连网络数据库时配置可验证的 TLS：在连接项中添加 `"tls": {"ca": "/local/path/ca.pem"}`；双向 TLS 可额外添加配对的 `cert` 和 `key` 路径。未配置 `tls` 时不主动启用 TLS。需要 SSH 隧道时，先由 SSH skill 建立本地隧道，再使用本机预先配置的 MySQL 别名。

技能约束正常调用流程不读取凭据，不提供操作系统级文件隔离。脚本会在输出中替换连接地址、用户名和密码的原文匹配，包括查询结果中的匹配值；业务数据本身仍需按授权范围查询。

## 使用方法

直接向 AI 描述目标，例如：

> 使用 MySQL 的 business 别名，查看有哪些订单表。
>
> 查询 business 库最近 10 笔失败订单，只返回订单号、状态和创建时间。

命令行示例，`<PYTHON>` 替换为虚拟环境 Python 路径：

```text
<PYTHON> "scripts/mysql_skill.py" config list
<PYTHON> "scripts/mysql_skill.py" schema --alias business
<PYTHON> "scripts/mysql_skill.py" schema --alias business --table orders
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql "SELECT id, status FROM orders ORDER BY id DESC LIMIT 10"
<PYTHON> "scripts/mysql_skill.py" query --alias business --sql-file "query.sql" --limit 100 --timeout 15
```

默认返回 100 行，最多 1,000 行；`--timeout` 默认为 15 秒，最多 60 秒。MySQL 5.7.8+ 将其用于服务端 SELECT 超时；所有版本的客户端读取超时为该值加 5 秒，属于单次读取等待限制，并非整体执行期限。CLI 同时将 SQL 的顶层 `LIMIT` 收紧到返回上限加 1，保留更小的原有上限和偏移。扫描、排序和聚合仍可能处理更多行。

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

## 开源协议

采用 [MIT License](LICENSE)。

## 工具文档

- [Codex Skills](https://developers.openai.com/codex/skills/)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [DeepSeek Harness Skill Filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)
