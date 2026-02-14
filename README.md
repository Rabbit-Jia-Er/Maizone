# Maizone（麦麦空间）

MaiBot 的 QQ 空间插件。让你的麦麦发说说、刷空间、自动评论点赞、回复评论、写日记！

## 功能

**发说说** — `/zn <主题>` 或自然语言触发，根据人格和历史说说生成内容，可选 AI 配图

**读说说** — 自然语言触发（"读一下我的QQ空间"），获取好友说说并点赞评论

**自动刷空间** — Routine 模式驱动，自动评论、点赞、回复评论：
- 评论未读的好友说说
- 按概率点赞
- 回复自己说说下的新评论（`enable_auto_reply`）
- 回复他人空间中对 bot 评论的回复（非静默时段自动生效）

**日记** — 从聊天记录生成日记，手动 `/zn gen` 或定时自动生成

**Routine** — 依赖 autonomous_planning 插件，LLM 决策是否发说说/刷空间

## 使用方法

### 安装插件

1. 使用命令行工具或是 git base 进入你的麦麦目录

   ```shell
   cd MaiBot/plugins
   ```

2. 克隆本仓库

   ```shell
   git clone https://github.com/Rabbit-Jia-Er/Maizone.git
   ```

3. 根据部署方式安装相应依赖，示例：

   - 一键包安装：在`![[点我启动!!!`后出现的菜单中选择交互式安装pip模块，按模块名安装bs4和json5

   - docker部署安装：宿主机内

     ```bash
     docker exec -it maim-bot-core uv pip install bs4 json5 --system
     ```

     您可能需要修改docker-compose.yaml以持久化python包

   - uv安装：在plugins\Maizone文件夹下

     ```bash
     uv pip install -r .\requirements.txt -i https://mirrors.aliyun.com/pypi/simple --upgrade
     ```

   - pip安装：在MaiBot文件夹下

     ```bash
     .\venv\Scripts\activate
     cd .\plugins\Maizone\
     pip install -i https://mirrors.aliyun.com/pypi/simple -r .\requirements.txt --upgrade
     ```

     启动 MaiBot，插件目录下自动生成 `config.toml`，按注释填写配置后重启即可（未生成配置文件请检查启动麦麦时的加载插件日志）

## 命令一览

所有命令统一使用 `/zn` 前缀：

| 命令 | 说明 | 权限 |
|------|------|------|
| `/zn help` | 查看帮助 | 所有人 |
| `/zn <主题>` | 发一条指定主题的说说 | send权限 |
| `/zn custom` | 发送自定义私聊内容的说说 | send权限 |
| `/zn gen` | 生成今天的日记 | send权限 |
| `/zn gen <日期>` | 生成指定日期的日记 | send权限 |
| `/zn ls` | 查看日记列表和统计 | send权限 |
| `/zn v` | 查看今天的日记 | 所有人 |
| `/zn v <日期>` | 查看指定日期的日记 | 所有人 |
| `/zn v <日期> <编号>` | 查看指定编号的日记 | 所有人 |

日期格式支持：`YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY.MM.DD`、`今天`、`昨天`、`前天`

## 配置

### `[plugin]`

| 项 | 默认值 | 说明 |
|----|--------|------|
| `enable` | `true` | 启用插件 |
| `http_host` | `"127.0.0.1"` | Napcat 地址 |
| `http_port` | `"9999"` | Napcat 端口 |
| `napcat_token` | `""` | Napcat Token |
| `cookie_methods` | `["napcat", "clientkey", "qrcode", "local"]` | Cookie 获取方式，按顺序尝试 |
> 为了您的安全，请设置Token。操作方法：在设置http服务器时面板最下方的Token栏中填入密码，在生成的config.toml文件中填写该密码

| 方式 | 说明 |
|------|------|
| `napcat` | 通过Napcat HTTP接口获取（推荐） |
| `clientkey` | 通过本机QQ客户端获取（需QQ在同一机器上） |
| `qrcode` | 扫描插件目录下的二维码登录（有效期约一天） |
| `local` | 读取已保存的cookie文件（[如何获取QQ空间cookie？](https://www.xjr7670.com/articles/how-to-get-qzone-cookie.html)） |

### `[send]`

`/zn`、Action、Routine 共用。权限同时控制日记命令。

| 项 | 默认值 | 说明 |
|----|--------|------|
| `permission` | `["114514"]` | 权限 QQ 号 |
| `permission_type` | `"whitelist"` | `whitelist` / `blacklist` |
| `enable_image` | `false` | 启用配图 |
| `image_mode` | `"random"` | `only_ai` / `only_emoji` / `random` |
| `ai_probability` | `0.5` | AI 配图概率 |
| `image_number` | `1` | 图片数量 1-4 |
| `history_number` | `5` | 参考历史说说数量 |
| `prompt` | *见配置文件* | 提示词。占位符：`{current_time}` `{bot_personality}` `{topic}` `{bot_expression}` `{current_activity}` |
| `custom_qqaccount` | `""` | custom 模式私聊 QQ |
| `custom_only_mai` | `true` | custom 模式用 bot 发言 |
| `pic_plugin_model` | `""` | 麦麦绘卷模型 key |

### `[read]`

Action 和刷空间评论共用。

| 项 | 默认值 | 说明 |
|----|--------|------|
| `permission` | `["114514"]` | 权限 QQ 号 |
| `permission_type` | `"blacklist"` | `whitelist` / `blacklist` |
| `read_number` | `5` | 读取说说数量 |
| `like_possibility` | `1.0` | 点赞概率 |
| `comment_possibility` | `1.0` | 评论概率 |
| `prompt` | *见配置文件* | 评论提示词。占位符：`{current_time}` `{bot_personality}` `{target_name}` `{created_time}` `{content}` `{impression}` `{bot_expression}` |
| `rt_prompt` | *见配置文件* | 转发说说评论提示词。额外：`{rt_con}` |

### `[monitor]`

| 项 | 默认值 | 说明 |
|----|--------|------|
| `read_list` | `[]` | 自动阅读名单 |
| `read_list_type` | `"blacklist"` | `whitelist` / `blacklist` |
| `enable_auto_reply` | `false` | 回复自己说说下的评论 |
| `self_readnum` | `5` | 检查自己最新说说数量 |
| `silent_hours` | `"22:00-07:00"` | 静默时段 |
| `like_during_silent` | `false` | 静默期允许点赞 |
| `comment_during_silent` | `false` | 静默期允许评论 |
| `like_possibility` | `1.0` | 点赞概率 |
| `comment_possibility` | `1.0` | 评论概率 |
| `processed_comments_cache_size` | `100` | 已处理评论缓存上限 |
| `processed_feeds_cache_size` | `100` | 已处理说说缓存上限 |
| `reply_prompt` | *见配置文件* | 回复评论提示词。占位符：`{current_time}` `{bot_personality}` `{nickname}` `{created_time}` `{content}` `{comment_content}` `{impression}` `{bot_expression}` |
| `reply_to_reply_prompt` | *见配置文件* | 回复他人空间中对 bot 评论的回复。占位符：`{current_time}` `{bot_personality}` `{nickname}` `{created_time}` `{content}` `{bot_comment}` `{reply_content}` `{impression}` `{bot_expression}` |

### `[routine]`

依赖 autonomous_planning 插件。

| 项 | 默认值 | 说明 |
|----|--------|------|
| `check_interval_minutes` | `20` | 检查间隔（分钟） |
| `post_cooldown_minutes` | `120` | 发说说冷却（分钟） |
| `browse_cooldown_minutes` | `40` | 刷空间冷却（分钟） |

### `[models]`

| 项 | 默认值 | 说明 |
|----|--------|------|
| `text_model` | `"replyer"` | 文本模型 |
| `image_prompt` | *见配置文件* | 图片提示词备选 |
| `clear_image` | `true` | 上传后清理图片 |
| `show_prompt` | `false` | 日志显示 prompt |

### `[diary]`

权限复用 `[send]`。

| 项 | 默认值 | 说明 |
|----|--------|------|
| `enabled` | `false` | 启用自动日记 |
| `schedule_time` | `"23:30"` | 自动生成时间 |
| `style` | `"diary"` | `diary` / `qqzone` / `custom` |
| `min_message_count` | `3` | 最少消息数 |
| `min_word_count` | `250` | 最少字数 |
| `max_word_count` | `350` | 最多字数 |
| `filter_mode` | `"all"` | `all` / `whitelist` / `blacklist` |
| `target_chats` | `""` | 每行一个 `group:群号` 或 `private:QQ号` |
| `custom_prompt` | `""` | 自定义模板 |

### `[diary.model]`

| 项 | 默认值 | 说明 |
|----|--------|------|
| `use_custom_model` | `false` | 使用自定义模型 |
| `api_url` | `"https://api.siliconflow.cn/v1"` | API 地址 |
| `api_key` | `""` | API 密钥 |
| `model_name` | `"Pro/deepseek-ai/DeepSeek-V3"` | 模型名称 |
| `temperature` | `0.7` | 温度 |
| `api_timeout` | `300` | 超时（秒） |


## 贡献和反馈

- **制作者水平有限，任何漏洞、疑问或建议,欢迎提交 Issue 和 Pull Request！**
- **或联系QQ：1523640161,3082618311**
- **其余问题请联系作者修复或解决（部分好友请求可能被过滤导致回复不及时，请见谅）**

---

## 鸣谢

[MaiBot](https://github.com/MaiM-with-u/MaiBot)

部分代码来自仓库：[qzone-toolkit](https://github.com/gfhdhytghd/qzone-toolkit)

感谢[xc94188](https://github.com/xc94188)、[myxxr](https://github.com/myxxr)、[UnCLAS-Prommer](https://github.com/UnCLAS-Prommer)、[XXXxx7258](https://github.com/XXXxx7258)、[heitiehu-beep](https://github.com/heitiehu-beep)提供的功能改进

魔改版麦麦，集成了魔改版插件[MoFox_Bot](https://github.com/MoFox-Studio/MoFox_Bot)
