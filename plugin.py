import sys, os
import asyncio
from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo
from src.plugin_system.base.config_types import ConfigField

from .actions import SendFeedAction, ReadFeedAction
from .commands import MaizoneCommand
from .scheduled_tasks import FeedMonitor, ScheduleSender


@register_plugin
class MaizonePlugin(BasePlugin):
    """Maizone插件 - 让麦麦发QQ空间"""
    plugin_name = "MaizonePlugin"
    plugin_description = "让麦麦实现QQ空间点赞、评论、发说说，统一命令 /mz"
    plugin_author = "internetsb"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies = []
    python_dependencies = ['httpx', 'Pillow', 'bs4', 'json5', 'openai']

    config_section_descriptions = {
        "plugin": "插件基础配置（Napcat连接与Cookie获取方式）",
        "send": "发送说说配置（/mz send、发说说Action、定时发送共用，权限同时控制 /mz diary generate/list）",
        "read": "阅读说说配置（读说说Action，关键词触发：聊天中提到'说说''空间''动态'时触发）",
        "monitor": "自动刷空间配置（后台定时浏览好友说说并评论点赞，评论他人说说时使用read的prompt）",
        "schedule": "定时发送说说配置（后台按时间表自动发说说，说说生成使用send的prompt和图片配置）",
        "models": "模型配置（文本生成模型、图片提示词、调试选项）",
        "diary": "日记功能配置（/mz diary 命令手动操作或定时自动生成，权限复用send的permission）",
    }

    config_schema = {
        "plugin": {
            "enable": ConfigField(type=bool, default=True, description="是否启用插件"),
            "http_host": ConfigField(type=str, default='127.0.0.1', description="Napcat http服务器地址"),
            "http_port": ConfigField(type=str, default='9999', description="Napcat http服务器端口号"),
            "napcat_token": ConfigField(type=str, default="", description="Napcat服务认证Token（如果Napcat设置了Token则需要填写）"),
            "cookie_methods": ConfigField(type=list, default=['napcat', 'clientkey', 'qrcode', 'local'],
                                          description="获取Cookie的方法，按顺序尝试，可选: napcat, clientkey, qrcode, local"),
        },
        "send": {
            "permission": ConfigField(type=list, default=['114514', '1919810', '1523640161'],
                                      description="权限QQ号列表（同时控制 /mz send、/mz diary generate/list 和发说说Action的权限）"),
            "permission_type": ConfigField(type=str, default='whitelist',
                                           description="权限模式: whitelist(仅列表中的QQ号有权限) / blacklist(仅列表中的QQ号无权限)"),
            "enable_image": ConfigField(type=bool, default=False,
                                        description="是否启用带图片的说说（需要配置 pic_plugin_model 或表情包插件）"),
            "image_mode": ConfigField(type=str, default='random',
                                      description="图片使用方式: only_ai(仅AI生成) / only_emoji(仅表情包) / random(随机混合)"),
            "ai_probability": ConfigField(type=float, default=0.5, description="random模式下使用AI图片的概率（0-1）"),
            "image_number": ConfigField(type=int, default=1,
                                        description="使用的图片或表情包数量（1-4，仅部分模型支持多图，如Kolors）"),
            "history_number": ConfigField(type=int, default=5,
                                          description="生成说说时参考的历史说说数量（越多越能避免重复内容，但增加token消耗）"),
            "prompt": ConfigField(type=str,
                                  default="你是'{bot_personality}'，现在是'{current_time}'你想写一条主题是'{topic}'的说说发表在qq空间上，"
                                          "{bot_expression}，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，可以适当使用颜文字，只输出一条说说正文的内容，不要输出多余内容"
                                          "(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )",
                                  description="生成说说的提示词，可用占位符: {current_time}(当前时间), {bot_personality}(人格), {topic}(说说主题), {bot_expression}(表达方式)"),
            "custom_qqaccount": ConfigField(type=str, default="",
                                            description="custom模式（/mz send custom）：使用与该QQ账号的最新私聊内容作为说说内容（会屏蔽'/'开头的命令）"),
            "custom_only_mai": ConfigField(type=bool, default=True,
                                           description="custom模式下使用谁说的内容（true: bot的发言, false: 私聊对象的发言）"),
            "pic_plugin_model": ConfigField(type=str, default="",
                                            description="使用麦麦绘卷生图时的模型名称（对应麦麦绘卷配置中的模型key，留空则不生成AI图片）"),
        },
        "read": {
            "permission": ConfigField(type=list, default=['114514', '1919810'],
                                      description="权限QQ号列表（控制读说说Action的权限）"),
            "permission_type": ConfigField(type=str, default='blacklist',
                                           description="权限模式: whitelist(仅列表中有权限) / blacklist(仅列表中无权限)"),
            "read_number": ConfigField(type=int, default=5, description="一次读取最新的几条说说"),
            "like_possibility": ConfigField(type=float, default=1.0, description="读说说后点赞的概率（0-1）"),
            "comment_possibility": ConfigField(type=float, default=1.0, description="读说说后评论的概率（0-1）"),
            "prompt": ConfigField(type=str,
                                  default="你是'{bot_personality}'，你正在浏览你好友'{target_name}'的QQ空间，你看到了你的好友'{target_name}'"
                                          "在qq空间上在'{created_time}'发了一条内容是'{content}'的说说，你想要发表你的一条评论，现在是'{current_time}'"
                                          "你对'{target_name}'的印象是'{impression}'，若与你的印象点相关，可以适当评论相关内容，无关则忽略此印象，"
                                          "{bot_expression}，回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，不要输出多余内容"
                                          "(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容",
                                  description="对普通说说进行评论的提示词，可用占位符: {current_time}, {bot_personality}, {target_name}(说说主人名称), "
                                              "{created_time}(发布时间), {content}(说说内容), {impression}(印象点), {bot_expression}"),
            "rt_prompt": ConfigField(type=str,
                                     default="你是'{bot_personality}'，你正在浏览你好友'{target_name}'的QQ空间，你看到了你的好友'{target_name}'"
                                             "在qq空间上在'{created_time}'转发了一条内容为'{rt_con}'的说说，你的好友的评论为'{content}'，你对'{"
                                             "target_name}'的印象是'{impression}'，若与你的印象点相关，可以适当评论相关内容，无关则忽略此印象，"
                                             "现在是'{current_time}'，你想要发表你的一条评论，{bot_expression}，"
                                             "回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，"
                                             "不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容",
                                     description="对转发说说进行评论的提示词，额外占位符: {rt_con}(转发说说内容)，其余同上"),
        },
        "monitor": {
            "enable_auto_monitor": ConfigField(type=bool, default=False,
                                               description="是否启用自动刷空间"),
            "read_list": ConfigField(type=list, default=[],
                                     description="自动阅读名单（QQ号列表，配合 read_list_type 使用）"),
            "read_list_type": ConfigField(type=str, default="blacklist",
                                          description="名单类型: whitelist(仅读列表中的) / blacklist(不读列表中的)"),
            "enable_auto_reply": ConfigField(type=bool, default=False,
                                             description="是否启用自动回复自己说说下的评论（需要 enable_auto_monitor = true）"),
            "self_readnum": ConfigField(type=int, default=5,
                                        description="需要检查评论的自己最新说说数量"),
            "interval_minutes": ConfigField(type=int, default=15, description="刷空间间隔（分钟）"),
            "silent_hours": ConfigField(type=str, default="22:00-07:00",
                                        description="不刷空间的时间段（24小时制，格式 \"HH:MM-HH:MM\"，多段用逗号分隔）"),
            "like_during_silent": ConfigField(type=bool, default=False,
                                              description="静默时间段内是否仍然点赞"),
            "comment_during_silent": ConfigField(type=bool, default=False,
                                                 description="静默时间段内是否仍然评论"),
            "like_possibility": ConfigField(type=float, default=1.0,
                                            description="自动刷空间时点赞的概率（0-1）"),
            "comment_possibility": ConfigField(type=float, default=1.0,
                                               description="自动刷空间时评论的概率（0-1）"),
            "processed_comments_cache_size": ConfigField(type=int, default=100,
                                                        description="已处理评论缓存上限（防止内存无限增长，超出后丢弃最早的记录）"),
            "processed_feeds_cache_size": ConfigField(type=int, default=100,
                                                      description="已处理说说缓存上限（防止内存无限增长，超出后丢弃最早的记录）"),
            "reply_prompt": ConfigField(type=str,
                                        default="你是'{bot_personality}'，你的好友'{nickname}'在'{created_time}'评论了你QQ空间上的一条内容为"
                                                "'{content}'的说说，你的好友对该说说的评论为:'{comment_content}'，"
                                                "现在是'{current_time}'，你想要对此评论进行回复，你对该好友的印象是:"
                                                "'{impression}'，若与你的印象点相关，可以适当回复相关内容，无关则忽略此印象，"
                                                "{bot_expression}，回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，"
                                                "不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容",
                                        description="自动回复评论的提示词，可用占位符: {current_time}, {bot_personality}, {nickname}(评论者昵称), "
                                                    "{created_time}(评论时间), {content}(说说内容), {comment_content}(评论内容), {impression}(印象点), {bot_expression}"),
        },
        "schedule": {
            "enable_schedule": ConfigField(type=bool, default=False, description="是否启用定时发送说说"),
            "probability": ConfigField(type=float, default=1.0,
                                       description="每天发送说说的概率（0-1，每天0点决定当天是否发送）"),
            "schedule_times": ConfigField(type=list, default=["08:00", "20:00"],
                                          description="定时发送时间列表（HH:MM格式）"),
            "fluctuation_minutes": ConfigField(type=int, default=0,
                                               description="发送时间上下浮动范围（分钟），0表示不浮动（每天随机生成偏移）"),
            "random_topic": ConfigField(type=bool, default=True,
                                        description="是否使用随机主题（true则LLM自由发挥，false则从 fixed_topics 中随机选择）"),
            "fixed_topics": ConfigField(type=list,
                                        default=["今日穿搭", "日常碎片PLOG", "生活仪式感", "治愈系天空", "理想的家",
                                                 "周末去哪儿", "慢生活", "今天吃什么呢", "懒人食谱", "居家咖啡馆",
                                                 "探店美食", "说走就走的旅行", "小众旅行地", "治愈系风景", "一起去露营",
                                                 "逛公园", "博物馆奇遇", "穿搭灵感", "复古穿搭", "今日妆容", "护肤日常",
                                                 "小众品牌", "我家宠物好可爱", "阳台花园", "运动打卡", "瑜伽日常",
                                                 "轻食记", "看书打卡", "我的观影报告", "咖啡店日记", "手帐分享",
                                                 "画画日常", "手工DIY", "沙雕日常", "沉浸式体验", "开箱视频",
                                                 "提升幸福感的小物", "圣诞氛围感", "冬日限定快乐", "灵感碎片",
                                                 "艺术启蒙", "色彩美学", "每日一诗", "哲学小谈", "存在主义咖啡馆",
                                                 "艺术史趣闻", "审美积累", "现代主义漫步", "东方美学"],
                                        description="固定主题列表（random_topic 为 false 时生效，其中 'custom' 表示使用私聊最新内容）"),
        },
        "models": {
            "text_model": ConfigField(type=str, default="replyer",
                                      description="生成文本的模型（从MaiBot的model_config读取），默认 replyer 即可"),
            "image_prompt": ConfigField(type=str,
                                        default="请根据以下QQ空间说说内容配图，并构建生成配图的风格和prompt。说说主人信息：'{personality}'。说说内容:'{"
                                                "message}'。请注意：仅回复用于生成图片的prompt，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )",
                                        description="图片生成提示词（当麦麦绘卷的PromptOptimizer不可用时作为备选），"
                                                    "可用占位符: {personality}(说说主人信息), {message}(说说内容), {current_time}(当前时间)"),
            "clear_image": ConfigField(type=bool, default=True, description="是否在上传后清理生成的图片文件"),
            "show_prompt": ConfigField(type=bool, default=False, description="是否在日志中显示生成的prompt内容（调试用）"),
        },
        "diary": {
            "enabled": ConfigField(type=bool, default=False,
                                   description="是否启用日记功能（启用后定时任务会在指定时间自动生成日记）"),
            "schedule_time": ConfigField(type=str, default="23:30",
                                         description="每日自动生成日记的时间（HH:MM格式）"),
            "style": ConfigField(type=str, default="diary",
                                 description="日记风格: diary(日记体) / qqzone(说说体) / custom(自定义prompt)"),
            "min_message_count": ConfigField(type=int, default=3,
                                             description="生成日记所需的最少消息数量（不够则跳过）"),
            "min_word_count": ConfigField(type=int, default=250,
                                          description="日记最少字数"),
            "max_word_count": ConfigField(type=int, default=350,
                                          description="日记最多字数"),
            "filter_mode": ConfigField(type=str, default="all",
                                       description="消息过滤模式: all(所有群聊) / whitelist(仅target_chats中的) / blacklist(排除target_chats中的)"),
            "target_chats": ConfigField(type=str, default="",
                                        description="目标聊天列表，每行一个，格式: group:群号 或 private:QQ号"),
            "custom_prompt": ConfigField(type=str, default="",
                                         description="自定义日记prompt模板（style 为 custom 时生效），可用占位符: {date}, {timeline}, {date_with_weather}, "
                                                     "{target_length}, {personality_desc}, {style}, {name}"),
        },
        "diary.model": {
            "use_custom_model": ConfigField(type=bool, default=False,
                                            description="是否使用自定义模型（否则使用MaiBot默认replyer模型）"),
            "api_url": ConfigField(type=str, default="https://api.siliconflow.cn/v1",
                                   description="自定义模型API地址"),
            "api_key": ConfigField(type=str, default="",
                                   description="自定义模型API密钥"),
            "model_name": ConfigField(type=str, default="Pro/deepseek-ai/DeepSeek-V3",
                                      description="自定义模型名称"),
            "temperature": ConfigField(type=float, default=0.7,
                                       description="生成温度（0-2）"),
            "api_timeout": ConfigField(type=int, default=300,
                                       description="API请求超时时间（秒）"),
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor = None
        self.scheduler = None

        if self.get_config("plugin.enable", True):
            self.enable_plugin = True

            if self.get_config("monitor.enable_auto_monitor", False):
                self.monitor = FeedMonitor(self)
                asyncio.create_task(self._start_monitor_after_delay())

            if self.get_config("schedule.enable_schedule", False) or self.get_config("diary.enabled", False):
                self.scheduler = ScheduleSender(self)
                asyncio.create_task(self._start_scheduler_after_delay())
        else:
            self.enable_plugin = False

    async def _start_monitor_after_delay(self):
        """延迟启动监控任务"""
        await asyncio.sleep(10)
        if self.monitor:
            await self.monitor.start()

    async def _start_scheduler_after_delay(self):
        """延迟启动日程任务"""
        await asyncio.sleep(10)
        if self.scheduler:
            await self.scheduler.start()

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (MaizoneCommand.get_command_info(), MaizoneCommand),
            (SendFeedAction.get_action_info(), SendFeedAction),
            (ReadFeedAction.get_action_info(), ReadFeedAction),
        ]

