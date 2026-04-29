# 🦋 蝴蝶效应 — 飞书群聊互动叙事游戏

![蝴蝶效应](assets/game-logo.png)

在飞书群聊里，多个成员共同 @机器人 推进一个 AI 生成的故事。每一次决策都会改变剧情走向——就像蝴蝶效应。

- **剧情生成**：DeepSeek LLM（JSON 结构化输出，含场景、叙述、氛围、选项）
- **概念图**：火山方舟 Ark 文生图（OpenAI 兼容接口）
- **存档导出**：自动创建飞书云文档（带标题），同时保存本地 Markdown 快照
- **多人协作**：同一群聊共享一局状态，任意成员均可参与推进

---

## 目录

- [快速开始](#快速开始)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
- [运行](#运行)
- [游戏指令](#游戏指令)
- [配置文件详解](#配置文件详解)
- [项目结构](#项目结构)
- [数据存储](#数据存储)
- [故障排查](#故障排查)

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 复制环境变量模板并填入 Key
cp .env.example .env   # 编辑 .env 填入 DEEPSEEK_API_KEY 等

# 3. 启动引擎
python scripts/game-engine.py

# 4. 在飞书群里发送
# @机器人 帮助
# @机器人 开始游戏 一群宇航员被困在火星基地
```

---

## 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.10+ |
| lark-cli | 已安装并完成 `lark-cli auth login` + 机器人权限配置 |
| 飞书应用 | 已开通 `im:message.receive_v1` 事件、发消息权限、创建云文档权限 |
| DeepSeek API | 必须，用于剧情生成 |
| 火山方舟 API | 可选，用于概念图生成；无 Key 时游戏正常运行，仅跳过配图 |

### 飞书 lark-cli Skill 依赖

引擎通过 `lark-cli` 子进程调用以下内置 Skill，无需单独安装，但需确认 lark-cli 已正确配置：

| Skill | 用途 |
|---|---|
| `lark-shared` | 应用鉴权、身份切换（`lark-cli config init` / `auth login`） |
| `lark-event` | WebSocket 事件订阅，接收群聊消息（`event +subscribe`） |
| `lark-im` | 向群聊发送文本 / 图片回复（`im +messages-send`） |
| `lark-doc` | 创建飞书云文档，用于故事 / 梗概导出（`docs +create`） |

> 如遇权限报错，优先检查飞书应用是否开通对应 scope（`im:message`、`docs:doc`）。

---

## 安装

```bash
git clone <repo-url>
cd butterfly-effect
pip install -r requirements.txt
```

**lark-cli 配置**（如未完成）：

```bash
lark-cli config init     # 填入 App ID / App Secret
lark-cli auth login      # 授权机器人身份
```

---

## 配置

### 1. 环境变量 `.env`

在项目根目录创建 `.env` 文件（**不要提交到 Git**）：

```dotenv
# 必填：剧情生成
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 可选：覆盖默认 LLM 端点与模型
LLM_API_URL=https://api.deepseek.com/v1/chat/completions
LLM_MODEL=deepseek-chat

# 可选：概念图生成（火山方舟 Ark）
ARK_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
ARK_MODEL=doubao-seedream-4-0-250828

# 可选：机器人自身的 open_id，用于过滤机器人自回声
FEISHU_BOT_OPEN_ID=ou_xxxxxxxxxxxxxxxx
```

### 2. 游戏参数 `config.yaml`

```yaml
game:
  inactivity_timeout: 600       # 无操作多少秒后自动暂停（默认 10 分钟）
  image_gen_interval: 3         # 每 N 次玩家决策生成一张概念图
  max_story_nodes: 50           # 达到后自动触发结束

llm:
  temperature: 0.85
  max_tokens: 2048

safety:
  max_decisions_per_minute: 10  # 每群每分钟最多处理多少次 LLM 请求

# 预设开局（群内用 preset:键名 或 #键名 引用）
presets:
  mars:
    title: "火星72小时"
    opening: "我们是一队被困火星的宇航员，补给与氧气只剩约72小时，必须做出抉择。"
  demo:
    title: "赛博霓都"
    opening: "你是底层义体技师，今夜接到一单无法拒绝的生意，委托人身份不明。"
```

---

## 运行

### 普通模式

```bash
python scripts/game-engine.py
```

### 调试模式（推荐排查问题时使用）

```bash
python scripts/game-engine.py --debug
```

调试模式会打印每条收到的事件 JSON、路由决策、发出的回复内容及返回码，便于确认消息格式和指令识别是否正常。

### 注意事项

- 引擎需要**常驻运行**（使用 tmux / screen / 系统服务托管）
- 停止引擎请用 **`Ctrl+C`**，不要用 `Stop-Process -Force` 等强杀方式
  - 强杀会使 `lark-cli` 子进程成为孤儿，继续占用飞书的 WebSocket 连接
  - 如已出现孤儿进程：`Stop-Process -Name lark-cli -Force`（Windows）
- 同一飞书应用只允许**一条**事件订阅连接，启动前确认没有旧引擎在跑

---

## 游戏指令

所有指令建议**单独一行**发送，前面加 `@机器人`（群聊必须）。

| 指令 | 说明 |
|---|---|
| `@机器人 帮助` | 显示完整指令列表 |
| `@机器人 开始游戏 [开头]` | 开始新游戏，可附带故事开场描述 |
| `@机器人 开始游戏 preset:mars` | 加载预设开局（键名见 `config.yaml` → `presets`） |
| `@机器人 开始游戏 #demo` | 同上，`#键名` 简写 |
| `@机器人 新游戏 [开头]` | 同「开始游戏」 |
| `@机器人 [任意描述]` | 推进剧情，输入玩家动作或决策 |
| `@机器人 游戏状态` | 查看当前进度（幕数、参与者、最近剧情） |
| `@机器人 选项` | 列出 2～4 个行动方向（不推进剧情） |
| `@机器人 回溯` | 撤销上一幕剧情 |
| `@机器人 重新开始` | 清空本局剧情，累计通关数保留 |
| `@机器人 导出故事` | 导出全文飞书文档，**不结束**游戏 |
| `@机器人 导出梗概` | 导出 AI 压缩梗概文档，**不结束**游戏 |
| `@机器人 结束游戏` | 结束本局，通关计数 +1，导出全文文档 |

> **指令容错**：支持前缀「请、帮、麻烦」，句尾「吧、谢谢」及常见标点；各指令词内部允许 IME 插入空格（如「导 出 故 事」）；`@机器人指令`（无空格）也能识别。

---

## 典型演示流程

```
@机器人 帮助
@机器人 开始游戏 preset:mars        ← 载入火星预设
[系统] 我们是一队被困火星的宇航员……（附 2-4 个行动选项）

@机器人 检查氧气读数并联系指挥部    ← 推进剧情
[系统] 你走向控制台…（下一幕剧情 + 选项）

@机器人 导出梗概                    ← 中途导出不结束
[系统] 已导出飞书文档（梗概，游戏未结束）：https://…

@机器人 结束游戏
[系统] 游戏结束，飞书文档：https://… 本地快照：…  累计完成 1 局。
```

---

## 配置文件详解

### `config.yaml` 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `game.inactivity_timeout` | 600 | 超时自动暂停（秒） |
| `game.image_gen_interval` | 3 | 每 N 次玩家决策尝试生图 |
| `game.max_story_nodes` | 50 | 最大节点数，超限自动结束 |
| `game.context_window_nodes` | 5 | 传给 LLM 的最近节点数 |
| `llm.temperature` | 0.85 | 剧情生成温度 |
| `llm.max_tokens` | 2048 | 每次剧情最大 token |
| `safety.max_decisions_per_minute` | 10 | 每群每分钟 LLM 请求上限 |

### 预设开局（`presets`）

```yaml
presets:
  my_story:
    title: "故事标题"         # 飞书文档标题前缀
    opening: "开场描述文字"   # 作为 LLM 的初始 prompt
```

群内使用：`@机器人 开始游戏 preset:my_story` 或 `@机器人 开始游戏 #my_story`

---

## 项目结构

```
butterfly-effect/
├── scripts/
│   ├── game-engine.py        # 核心引擎（事件监听、路由、游戏逻辑）
│   ├── archive_builder.py    # 独立文档导出工具
│   ├── story_generator.py    # 独立剧情生成工具
│   ├── image_generator.py    # 独立图片生成工具
│   └── test_game_engine.py   # 回归测试（指令解析、事件提取等）
├── references/
│   ├── game-rules.md         # 游戏机制说明
│   ├── demo-presets.md       # 演示口令序列
│   ├── api-reference.md      # API 调用参考
│   └── prompt-templates.md   # Prompt 模板说明
├── config.yaml               # 游戏参数与预设配置
├── requirements.txt          # Python 依赖
├── .env                      # 密钥配置（不提交 Git）
├── SKILL.md                  # Skill 详细文档（含架构、边界说明）
└── README.md                 # 本文件
```

---

## 数据存储

| 路径 | 内容 |
|---|---|
| `~/.butterfly-effect/saves/<chat_id>.json` | 每群游戏状态（运行时持久化） |
| `~/.butterfly-effect/finished-runs/*.md` | 每局结束 / 导出的 Markdown 快照 |
| `.butterfly-effect/export-temp/` | 创建飞书文档时的临时 Markdown 文件（24h 后自动清理） |
| `.butterfly-effect/image-cache/` | 发图前下载的临时图片文件（24h 后自动清理） |

---

## 故障排查

### 启动报「another event +subscribe instance is already running」

有孤儿 `lark-cli` 进程占用连接：

```powershell
# Windows
Stop-Process -Name lark-cli -Force

# macOS / Linux
pkill -f "lark-cli event"
```

等 2-3 秒后重新运行引擎。

### 机器人没有任何响应

1. 确认引擎终端显示 `Connected. Waiting for events...`
2. 用 `--debug` 模式启动，查看是否有 `[DEBUG] event keys=...` 出现
3. 检查飞书应用是否开通了 `im.message.receive_v1` 事件订阅
4. 确认机器人已被添加到群聊

### 飞书只收到部分内容 / 指令没反应

可能是旧版引擎在运行。重启引擎确认代码是最新版本。

### 飞书文档标题显示「Untitled」

引擎使用 `docs +create --title … --markdown @file`（v1 API）创建文档，已明确传入标题。若仍显示 Untitled，请检查 lark-cli 版本（`lark-cli --version`）并确保使用引擎内置导出函数。

### 无法生成概念图

- 检查 `.env` 中 `ARK_API_KEY` 是否填写
- 发送 `@机器人 游戏状态` 查看本局跳过配图次数
- Ark 免费额度耗尽时游戏仍正常运行，仅不出图

### 运行回归测试

```bash
python scripts/test_game_engine.py
# 输出 "ok" 表示全部通过
```

---

## 安全说明

- `.env` 文件已在 `.gitignore` 中排除，**请勿将 API Key 提交到代码仓库**
- 引擎仅处理当前消息用于路由与 LLM，不批量同步历史聊天记录
- 本地存档仅含游戏相关字段（决策、剧情节点），不含完整聊天记录
