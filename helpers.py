"""Maizone 共享工具函数

提取 commands / actions / scheduled_tasks 中的重复模式：
- check_permission: 白名单/黑名单权限检查
- get_napcat_config_and_renew: 读取 Napcat 配置并刷新 Cookie
- build_diary_config: 构建 DiaryService 所需的配置字典
- build_send_prompt: 构建发说说 prompt
- build_comment_prompt: 构建评论说说 prompt
"""

from typing import Callable

from src.common.logger import get_logger

from .qzone import renew_cookies

logger = get_logger("Maizone.helpers")


def check_permission(
    get_config_fn: Callable,
    qq_account: str,
    section: str,
    log_name: str = "",
) -> bool:
    """统一的白名单/黑名单权限检查

    Args:
        get_config_fn: 配置读取函数，签名 (key, default) -> value
        qq_account: 待检查的 QQ 号
        section: 配置段名（如 "send" 或 "read"）
        log_name: 日志中显示的组件名

    Returns:
        是否有权限
    """
    permission_list = get_config_fn(f"{section}.permission")
    permission_type = get_config_fn(f"{section}.permission_type")
    logger.info(f"[{log_name}]{permission_type}:{str(permission_list)}")
    if permission_type == "whitelist":
        return qq_account in permission_list
    elif permission_type == "blacklist":
        return qq_account not in permission_list
    else:
        logger.error("permission_type错误，可能为拼写错误")
        return False


async def get_napcat_config_and_renew(
    get_config_fn: Callable,
) -> tuple[str, str, str]:
    """读取 Napcat 配置并刷新 Cookie

    Args:
        get_config_fn: 配置读取函数

    Returns:
        (host, port, napcat_token)

    Raises:
        Exception: Cookie 刷新失败时透传异常
    """
    host = get_config_fn("plugin.http_host", "127.0.0.1")
    port = get_config_fn("plugin.http_port", "9999")
    napcat_token = get_config_fn("plugin.napcat_token", "")
    cookie_methods = get_config_fn(
        "plugin.cookie_methods", ["napcat", "clientkey", "qrcode", "local"]
    )
    await renew_cookies(host, port, napcat_token, cookie_methods)
    return host, port, napcat_token


def build_diary_config(get_config_fn: Callable) -> dict:
    """构建 DiaryService 所需的配置字典

    Args:
        get_config_fn: 配置读取函数

    Returns:
        嵌套字典，可直接传给 DiaryService(plugin_config=...)
    """
    return {
        "plugin": {
            "http_host": get_config_fn("plugin.http_host", "127.0.0.1"),
            "http_port": get_config_fn("plugin.http_port", "9999"),
            "napcat_token": get_config_fn("plugin.napcat_token", ""),
            "cookie_methods": get_config_fn(
                "plugin.cookie_methods", ["napcat", "clientkey", "qrcode", "local"]
            ),
        },
        "diary": {
            "style": get_config_fn("diary.style", "diary"),
            "custom_prompt": get_config_fn("diary.custom_prompt", ""),
            "min_word_count": get_config_fn("diary.min_word_count", 250),
            "max_word_count": get_config_fn("diary.max_word_count", 350),
            "model": {
                "use_custom_model": get_config_fn("diary.model.use_custom_model", False),
                "api_url": get_config_fn("diary.model.api_url", ""),
                "api_key": get_config_fn("diary.model.api_key", ""),
                "model_name": get_config_fn("diary.model.model_name", ""),
                "temperature": get_config_fn("diary.model.temperature", 0.7),
                "api_timeout": get_config_fn("diary.model.api_timeout", 300),
            },
        },
    }


async def build_send_prompt(
    get_config_fn: Callable,
    qzone_api,
    topic: str,
    bot_personality: str,
    bot_expression: str,
    history_number: int = 5,
    current_activity: str = "",
) -> str:
    """构建发送说说的 prompt

    Args:
        get_config_fn: 配置读取函数
        qzone_api: QZone API 实例（需要 get_send_history 方法）
        topic: 说说主题
        bot_personality: Bot 人格描述
        bot_expression: Bot 表达方式
        history_number: 参考的历史说说数量
        current_activity: 当前活动描述（routine 模式传入，默认为空）

    Returns:
        完整的 prompt 字符串
    """
    import datetime
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt_pre = get_config_fn(
        "send.prompt",
        "你是'{bot_personality}'，现在是'{current_time}'你想写一条主题是'{topic}'的说说发表在qq空间上，"
        "{bot_expression}，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，可以适当使用颜文字，"
        "只输出一条说说正文的内容，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )"
    )
    data = {
        "current_time": current_time,
        "bot_personality": bot_personality,
        "topic": topic,
        "bot_expression": bot_expression,
        "current_activity": current_activity,
    }
    # 安全格式化：如果 prompt 模板中没有 {current_activity} 占位符也不会报错
    try:
        prompt = prompt_pre.format(**data)
    except KeyError:
        # 兼容：旧模板可能没有 current_activity 占位符
        data.pop("current_activity", None)
        prompt = prompt_pre.format(**data)

    # routine 模式下追加活动上下文
    if current_activity:
        prompt += f"\n你当前正在{current_activity}，说说内容应与当前状态自然相关。"

    prompt += "\n以下是你以前发过的说说，写新说说时注意不要在相隔不长的时间发送相同主题的说说\n"
    prompt += await qzone_api.get_send_history(history_number)
    prompt += "\n不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )"
    return prompt


def build_comment_prompt(
    get_config_fn: Callable,
    target_name: str,
    content: str,
    created_time: str,
    bot_personality: str,
    bot_expression: str,
    impression: str,
    rt_con: str = "",
) -> str:
    """构建评论说说的 prompt

    Args:
        get_config_fn: 配置读取函数
        target_name: 说说主人名称或QQ号
        content: 说说内容
        created_time: 说说发布时间
        bot_personality: Bot 人格描述
        bot_expression: Bot 表达方式
        impression: 对说说主人的印象
        rt_con: 转发说说内容，为空表示原创说说

    Returns:
        完整的 prompt 字符串
    """
    import datetime
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not rt_con:
        prompt_pre = get_config_fn(
            "read.prompt",
            "你是'{bot_personality}'，你正在浏览你好友'{target_name}'的QQ空间，你看到了你的好友'{target_name}'"
            "在qq空间上在'{created_time}'发了一条内容是'{content}'的说说，你想要发表你的一条评论，现在是'{current_time}'"
            "你对'{target_name}'的印象是'{impression}'，若与你的印象点相关，可以适当评论相关内容，无关则忽略此印象，"
            "{bot_expression}，回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，不要输出多余内容"
            "(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容"
        )
        data = {
            "current_time": current_time,
            "created_time": created_time,
            "bot_personality": bot_personality,
            "bot_expression": bot_expression,
            "target_name": target_name,
            "content": content,
            "impression": impression,
        }
    else:
        prompt_pre = get_config_fn(
            "read.rt_prompt",
            "你是'{bot_personality}'，你正在浏览你好友'{target_name}'的QQ空间，你看到了你的好友'{target_name}'"
            "在qq空间上在'{created_time}'转发了一条内容为'{rt_con}'的说说，你的好友的评论为'{content}'，你对'{"
            "target_name}'的印象是'{impression}'，若与你的印象点相关，可以适当评论相关内容，无关则忽略此印象，"
            "现在是'{current_time}'，你想要发表你的一条评论，{bot_expression}，"
            "回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，"
            "不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容"
        )
        data = {
            "current_time": current_time,
            "created_time": created_time,
            "bot_personality": bot_personality,
            "bot_expression": bot_expression,
            "target_name": target_name,
            "content": content,
            "rt_con": rt_con,
            "impression": impression,
        }
    return prompt_pre.format(**data)
