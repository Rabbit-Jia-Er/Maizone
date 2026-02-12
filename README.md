# Maizone（麦麦空间） 插件

> [!IMPORTANT]
>
> 为了您的安全，请设置Token。操作方法：在设置http服务器时面板最下方的Token栏中填入密码，在生成的config.toml文件中填写该密码

*制作者水平有限，任何漏洞、疑问或建议欢迎提出issue或联系qq：1523640161*

## 概述

Maizone（麦麦空间）插件v2.5.0，让你的麦麦发说说，读QQ空间，点赞评论，写日记！

效果展示：

<img src="images/done_show.png" style="zoom:50%;" />

## 功能

- **发说说**: 命令 `/mz send` 或自然语言触发（"发条说说"），支持指定主题、自定义内容
- **说说配图**: 可从已注册表情包中选择，或用AI生成配图，或随机混合
- **读说说**：当用户要求麦麦读说说、qq空间，并指定目标的qq昵称时，麦麦会获取该目标账号最近的动态并点赞评论
- **日记功能**: 从聊天记录生成日记，支持多种风格，可自动发布到QQ空间
- **权限管理**: 白名单/黑名单模式，分别控制发说说和读说说的权限
- **自动刷空间**: 后台定时浏览好友说说，自动点赞、评论，自动回复自己说说下的评论
- **定时发送**: 后台按时间表自动发说说，支持随机/固定主题

## 命令一览

所有命令统一使用 `/mz` 前缀：

| 命令 | 说明 | 权限 |
|------|------|------|
| `/mz help` | 查看帮助 | 所有人 |
| `/mz send` | 发一条随机主题的说说 | send权限 |
| `/mz send <主题>` | 发一条指定主题的说说 | send权限 |
| `/mz send custom` | 发送自定义私聊内容的说说 | send权限 |
| `/mz diary generate` | 生成今天的日记 | send权限 |
| `/mz diary generate <日期>` | 生成指定日期的日记 | send权限 |
| `/mz diary list` | 查看日记列表和统计 | send权限 |
| `/mz diary view` | 查看今天的日记 | 所有人 |
| `/mz diary view <日期>` | 查看指定日期的日记 | 所有人 |
| `/mz diary view <日期> <编号>` | 查看指定编号的日记 | 所有人 |

日期格式支持：`YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY.MM.DD`、`今天`、`昨天`、`前天`

## 使用方法

### 安装插件

1. 下载或克隆本仓库（麦麦旧版本可在release中下载适配旧版的插件）

   ```bash
   git clone https://github.com/internetsb/Maizone.git
   ```
   
2. 将 `Maizone\`文件夹放入 `MaiBot\plugins`文件夹下（路径中不要含有标点符号，中文字符）

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
     #pip安装，在MaiBot文件夹下
     .\venv\Scripts\activate
     cd .\plugins\Maizone\
     pip install -i https://mirrors.aliyun.com/pypi/simple -r .\requirements.txt --upgrade
     ```
   
     启动一次麦麦自动生成 `config.toml`配置文件，成功生成配置文件即说明读取插件成功（未生成配置文件请检查启动麦麦时的加载插件日志）

### 设置Napcat http服务器端口以获取cookie

![](images/done_napcat1.png)

![](images/done_napcat2.png)

启用后在 `config.toml` 中填写在napcat中设置的host（默认127.0.0.1）和端口号（默认9999）用于获取cookie

插件支持4种cookie获取方式，按 `cookie_methods` 配置的顺序依次尝试：

| 方式 | 说明 |
|------|------|
| `napcat` | 通过Napcat HTTP接口获取（推荐） |
| `clientkey` | 通过本机QQ客户端获取（需QQ在同一机器上） |
| `qrcode` | 扫描插件目录下的二维码登录（有效期约一天） |
| `local` | 读取已保存的cookie文件（[如何获取QQ空间cookie？](https://www.xjr7670.com/articles/how-to-get-qzone-cookie.html)） |

> [!IMPORTANT]
>
> **Docker部署使用方法**
>
> 将Napcat设置的HTTP Server的Host栏改为0.0.0.0，插件的config.toml中的http_host栏改为"napcat"（注意引号）。经测试可正常使用
>
> **NapCat设置**
>
> ![](images/done_docker_napcat.png)
>
> **插件config设置**
>
> ![](images/done_docker_config.png)
>
> **正常监听后的日志显示**
>
> ![](images/done_docker_log.png)

### 修改配置文件

请检查：

1. `MaiBot/config/bot_config.toml` 中 `qq_account` 是否为bot的QQ号

请设置：

2. 是否启用插件及各种功能
3. 是否启用说说配图和AI生成配图（及相应的模型配置）
4. 权限名单及类型

更多配置请看 `config.toml` 中的注释

### 配置说明

`config.toml` 分为以下几个配置区：

| 区段 | 说明 |
|------|------|
| `[plugin]` | 基础配置：Napcat连接地址、端口、Token、cookie获取方式 |
| `[send]` | 发说说配置：权限、图片、prompt。`/mz send`、发说说Action、定时发送共用此配置。权限同时控制 `/mz diary generate/list` |
| `[read]` | 读说说配置：权限、prompt。读说说Action使用。自动刷空间评论他人说说时也使用此处prompt |
| `[monitor]` | 自动刷空间：定时浏览好友说说并评论点赞，自动回复评论 |
| `[schedule]` | 定时发送：按时间表自动发说说，使用 `[send]` 的prompt和图片配置 |
| `[models]` | 模型配置：文本模型、图片prompt模板、调试选项 |
| `[diary]` | 日记功能：手动或定时生成日记，权限复用 `[send]` 的permission |
| `[diary.model]` | 日记模型：可使用自定义模型或MaiBot默认replyer模型 |

### （可选）AI生图

本插件通过麦麦绘卷（Mai's Art Journal）插件生成图片。配置步骤：

1. 确保已安装麦麦绘卷插件并在其配置中设置好图片生成模型
2. 在 Maizone 的 `config.toml` 中将 `[send]` 区段的 `enable_image` 设为 `true`
3. 将 `pic_plugin_model` 填写为麦麦绘卷配置中的模型key（例如其配置中有 `[models.kolors]`，则填 `kolors`）
4. `image_mode` 可选 `only_ai`（仅AI生成）、`only_emoji`（仅表情包）、`random`（随机混合）

### （可选）自定义内容

主题为 `custom` 时将发送与 `custom_qqaccount` 私聊的最新一条内容（过滤 `/` 开头的命令），根据 `custom_only_mai` 配置选择麦麦或私聊对象的发言。

- 命令：`/mz send custom`
- 定时发送：在 `[schedule]` 中设置 `random_topic = false`，`fixed_topics` 中包含 `"custom"`

使用示例：

- **麦麦做梦**：
  1. 配置麦麦做梦：发送至私聊，勾选存储到上下文
  2. 设置Maizone定时发送：选用固定主题 `custom`，配置 `custom_qqaccount` 为相同私聊
- **日记发布到空间**：
  1. 使用 `/mz diary generate` 生成日记（会自动发布到QQ空间）
  2. 或在 `[diary]` 中设置 `enabled = true` 开启自动日记

### 快速开始

**配置权限**：在 `config.toml` 中的 `[send]` 和 `[read]` 区段分别设置 `permission`（QQ号列表）和 `permission_type`（whitelist/blacklist）

**发说说**：发送命令 `/mz send` 或自然语言 "发条说说吧"/"发一条xxx的说说"，等待几秒后麦麦将发送一条说说至QQ空间

**读说说**：对麦麦说 "读一下我的QQ空间"/"评价一下@xxx的空间"，麦麦将对其近几条说说进行点赞评论

**生成日记**：发送命令 `/mz diary generate`，麦麦会根据当天聊天记录生成日记并发布到QQ空间

**自动看说说**：在 `config.toml` 中设置 `[monitor]` 的 `enable_auto_monitor = true`，麦麦会自动阅读新说说并点赞、评论

**定时发说说**：在 `config.toml` 中设置 `[schedule]` 的 `enable_schedule = true`，麦麦会定时发送说说

### （可选）日记功能

日记功能会从聊天记录中提取当天的对话内容，通过LLM生成日记。

**手动生成**：`/mz diary generate` 或 `/mz diary generate 2025-01-01`

**自动生成**：在 `[diary]` 中设置 `enabled = true` 和 `schedule_time`（默认23:30）

**日记风格**：
- `diary` — 日记体，传统日记格式
- `qqzone` — 说说体，适合发到QQ空间
- `custom` — 自定义prompt模板

**消息过滤**：通过 `filter_mode` 和 `target_chats` 控制从哪些群聊/私聊中收集消息

**自定义模型**：在 `[diary.model]` 中设置 `use_custom_model = true` 并配置API地址、密钥、模型名称

## 常见问题

- **Q：所有功能都失败报错**

  **A：请检查是否生成cookie，cookie名称与内容中的qq号是否正确，`MaiBot/config/bot_config.toml` 中 `qq_account` 是否填写正确**
  
- **Q：No module named 'bs4'**

  **A：安装依赖失败，请根据使用说明，确保在MaiBot运行的环境下，按照安装麦麦时的方法，选择恰当的方式安装依赖**
  
- **Q：No module named 'plugins.Maizone-2'**/**'No module named 'plugins.internetsb'**

  **A：'.'导致被错误地识别为了包，请重命名文件夹为Maizone，不要含有标点符号及中文字符**
  
- **Q：提示词为空，无法正常回复/回复“你好，我能为你做什么？”...**

  **A：版本更新导致的配置不兼容，请删除 `config.toml` 重新生成**
  
- **Q：我发了一条说说，但bot没有回复**

  **A：bot无法阅读相册上传、小程序分享、过早的说说，且某些说说（比如新加的好友）需要多次才能读到，具体读取情况以日志为准**
  
- **Q：listen EACCES: permission denied 127.0.0.1:9999**

  **A：可能为端口9999被占用，可选择更换为其它端口，并修改相应配置**
  
- **Q：如何更改使用的模型配置**

  **A：请查看 `MaiBot/config/model_config.toml`，默认使用replyer**

  ```
  [model_task_config.replyer] # 首要回复模型，还用于表达器和表达方式学习
  model_list = ["xxxxxx"]
  temperature = xxx
  max_tokens = xxx
  ```

  **可更换为配置的utils、utils_small、tool_use等模型，模型列表配置参看MaiBot文档**
  
- **Q：`/send_feed` 命令不存在了？**

  **A：v2.5.0 起所有命令统一为 `/mz` 前缀，原 `/send_feed` 改为 `/mz send`，原 `/diary` 改为 `/mz diary`**

- **其余问题请联系作者修复或解决（部分好友请求可能被过滤导致回复不及时，请见谅）**

## 已知问题

- 可能出现对同一条说说重复评论，或对同一条评论重复回复的问题，欢迎提供出现问题时的日志
- 当前解析说说附带的视频时仅解析了视频封面
- 当前对评论进行回复时仅使用了评论+@的方式而非通常的子评论

## 鸣谢

[MaiBot](https://github.com/MaiM-with-u/MaiBot)

部分代码来自仓库：[qzone-toolkit](https://github.com/gfhdhytghd/qzone-toolkit)

感谢[xc94188](https://github.com/xc94188)、[myxxr](https://github.com/myxxr)、[UnCLAS-Prommer](https://github.com/UnCLAS-Prommer)、[XXXxx7258](https://github.com/XXXxx7258)、[heitiehu-beep](https://github.com/heitiehu-beep)提供的功能改进

魔改版麦麦，集成了魔改版插件[MoFox_Bot](https://github.com/MoFox-Studio/MoFox_Bot)
