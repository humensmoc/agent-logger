# Agent Logger

给 Codex、Claude Code 或 Cursor 项目添加逐回合 AI 对话日志。日志按本机日期保存在你指定的目录中；用户消息默认逐字记录，AI 回复以简短摘要记录。Skill 只在 Agent 会话中执行，不是后台录屏或定时任务。

> 日志可能包含你输入的代码、链接、个人信息和凭据。首次启用时先选择日志目录、要排除的记录字段，以及哪些项目配置只留在本地。建议把日志目录放在公开仓库之外。

## 发链接给 Agent 安装

把本仓库的链接和下面这段话一起发给目标项目中的 Agent。安装过程应先问清楚选择，再写入本机和项目文件。

```text
请阅读这个仓库的 README.md 和 skills/agent-logger/SKILL.md，
在当前 Git 项目启用对话日志：<在这里粘贴仓库链接>。123

动手前请依次问我：
1. 这台设备的日志根目录绝对路径是什么？目录不存在时是否要创建？
2. 默认记录用户原文、图片说明、回复摘要、设备、项目、来源路径、时区、
   文件改动、所用 Skill、AI 名称和模型；我想排除哪些字段？
3. 如果日志目录在当前 Git 仓库里，要不要在本地忽略它？
4. Skill 本体、AGENTS.override.md、CLAUDE.local.md 和 Cursor 规则
   要留在本地，还是允许提交给协作者？解释两种选择的影响。

得到回答后再执行 configure 和 install，并运行 resolve 验证。
请不要修改现有日志、已跟踪文件或仓库历史。
```

仅发送链接无法让一个尚未读取仓库内容的 Agent 自动配置本机路径。上述提示词明确了它需要先做的事，也适用于换新设备：当前 Skill 的 `routes.json` 没有新设备的路径时会重新询问日志目录。

## 手动安装

需要 Python 3 和 Git。先下载本仓库，再在目标项目中运行本仓库内的脚本；以下路径均为示例，请替换成自己的绝对路径。

Windows PowerShell：

```powershell
git clone <仓库链接> C:\Tools\agent-logger
python C:\Tools\agent-logger\skills\agent-logger\scripts\logger_setup.py configure --path C:\Private\conversation-logs --create --exclude-fields ""
python C:\Tools\agent-logger\skills\agent-logger\scripts\logger_setup.py install --repo C:\Projects\example --visibility local --log-visibility local
python C:\Projects\example\.agents\skills\agent-logger\scripts\logger_setup.py resolve
```

macOS：

```sh
git clone <仓库链接> ~/Tools/agent-logger
python3 ~/Tools/agent-logger/skills/agent-logger/scripts/logger_setup.py configure --path ~/Documents/conversation-logs --create --exclude-fields ""
python3 ~/Tools/agent-logger/skills/agent-logger/scripts/logger_setup.py install --repo ~/Projects/example --visibility local --log-visibility local
python3 ~/Projects/example/.agents/skills/agent-logger/scripts/logger_setup.py resolve
```

`--create` 仅在你决定创建这个目录时使用；目录已存在可去掉。`--exclude-fields ""` 表示记录全部默认字段。例如不记录设备名和模型：`--exclude-fields device,model`。省略这个参数会保留当前 Skill 的 `routes.json` 中该设备此前的字段选择。

`install` 明确指定 `--repo`，避免误把发布仓库当作目标项目。默认示例中的两个 `local` 是**示例选择**，实际使用前请决定：

| 选项 | `local` | `shared` |
|---|---|---|
| `--visibility` | 把 Skill、`AGENTS.override.md`、`CLAUDE.local.md`、Cursor 规则写入目标仓库的 `.git/info/exclude`，只在本机启用 | 不为这些规则添加忽略项，允许你主动提交给团队 |
| `--log-visibility` | 日志目录位于目标仓库内时，在本地忽略该目录 | 不添加日志目录忽略项；日志在仓库内可能被提交 |

`.git/info/exclude` 只影响这个 Git 克隆中的**未跟踪**文件。已经提交过的文件、公开仓库历史及其他人的克隆不会因此隐藏。若日志目录在仓库外，`--log-visibility` 不需要添加路径。安装前脚本会拒绝将已跟踪文件误报为已被本地忽略。

## 默认记录内容与字段选择

每条记录都有日期、时间和当日递增回合号。其余内容默认记录，可在 `configure --exclude-fields` 中排除：

| 字段名 | 默认内容 |
|---|---|
| `user` | 用户输入原文，包括粘贴的代码和链接；附件以占位符表示 |
| `image_description` | 可见图片的客观简述 |
| `reply` | AI 实际回复与完成事项摘要 |
| `device` | 设备名 |
| `project` | 项目名 |
| `source` | 项目或工作区绝对路径 |
| `timezone` | 时区 |
| `files` | 本轮文件改动 |
| `skills` | 实际使用的 Skill |
| `ai` | Agent 产品名称 |
| `model` | 可验证的当前会话模型 ID |

日志格式示例使用虚构数据：

```markdown
# 2026-01-02 每日记录

### 回合 1 | 09:30 | laptop | example
- **来源**：`/home/example/project` | 时区=Asia/Shanghai
- **用户**：
  > 请帮我检查 README
- **回复**：检查了 README 并指出安装步骤中缺少目录配置。
- **Skill**：agent-logger
- **环境**：AI=Codex | 模型=未知模型
---
```

## 脚本与项目文件

`logger_setup.py` 有四个命令：`configure` 把当前设备的日志目录和排除字段写入 Skill 旁的 `routes.json`；`resolve` 验证该路径可写；`install` 在目标 Git 仓库复制 Skill、本机路由并写入项目规则；可选的 `register` 把 Skill 和本机路由复制到当前用户的 Codex、Claude Code 和 Cursor Skill 目录，便于在其他项目中再次安装。`register` 本身不会让所有项目自动写日志。

安装时使用 `AGENTS.override.md` 让 Codex 每轮读取 Skill，`CLAUDE.local.md` 让 Claude Code 每轮读取 Skill，`.cursor/rules/agent-logger.mdc` 用于 Cursor。使用本地模式的原因是：个人日志习惯与目录通常不应自动施加给协作者；如果团队希望统一启用，可以选择共享并审阅后提交这些文件。[Codex Skill 位置说明](https://learn.chatgpt.com/docs/build-skills)、[Claude Code 项目记忆说明](https://code.claude.com/docs/en/memory)。

换设备时，当前 Skill 副本的 `routes.json` 若没有该设备的路径，先询问用户使用哪个日志根目录，再运行 `configure --path <绝对路径>`。旧日志不会自动迁移。多设备写同一个云同步目录可能发生冲突，本机锁不保证跨设备串行。

`routes.json` 是唯一配置来源，按设备名保存路径和排除字段，格式见 `skills/agent-logger/routes.example.json`。真实路由不随发布仓库提交；`install` 和 `register` 会为各自的 Skill 副本写入当前设备路由，已有的目标路由保留。安装到仓库时，真实路由始终加入该仓库的本地 Git exclude。

## 故障排查与更新

- `resolve` 提示当前设备没有路径：询问用户要使用的绝对路径，再运行 `configure --path <绝对路径>`。
- 目录不存在或不可写：确认路径、权限；只有你要创建新目录时才加 `--create`。
- 旧版 Skill 与发布包不同：先查看差异，确认后在 `install` 增加 `--update`。
- Git 已跟踪日志或本地规则：先检查 Git 索引和公开历史；添加 ignore 无法撤回已发布内容。

本发布包仅包含对话记录 Skill 和安装脚本，不包含真实对话日志、个人设备路由或 Git 日结脚本。许可证应在公开发布前由维护者明确选定并添加 `LICENSE` 文件。
