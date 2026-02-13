"""
日记工具集

包含日记功能的通用工具类和函数：
- DiaryConstants: 常量定义
- format_date_str: 日期格式化
- get_bot_personality: 获取Bot人设
"""

from typing import Any, Dict

from src.plugin_system.apis import config_api, get_logger

logger = get_logger("Maizone.diary.utils")


class DiaryConstants:
    """日记插件常量定义"""
    MIN_MESSAGE_COUNT = 3
    TOKEN_LIMIT_50K = 50000
    TOKEN_LIMIT_126K = 126000
    MAX_DIARY_LENGTH = 8000
    DEFAULT_QZONE_WORD_COUNT = 300


async def get_bot_personality() -> Dict[str, str]:
    """获取bot人设信息"""
    personality = config_api.get_global_config("personality.personality", "是一个机器人助手")
    reply_style = config_api.get_global_config("personality.reply_style", "")
    nickname = config_api.get_global_config("bot.nickname", "")
    alias_names = config_api.get_global_config("bot.alias_names", [])

    return {
        "core": personality,
        "style": reply_style,
        "nickname": nickname,
        "alias_names": alias_names
    }


def format_date_str(date_input: Any) -> str:
    """统一的日期格式化函数，确保YYYY-MM-DD格式"""
    import datetime
    import re

    if isinstance(date_input, datetime.datetime):
        return date_input.strftime("%Y-%m-%d")
    elif isinstance(date_input, str):
        try:
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
                try:
                    date_obj = datetime.datetime.strptime(date_input, fmt)
                    return date_obj.strftime("%Y-%m-%d")
                except ValueError:
                    continue

            if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_input):
                return date_input

        except Exception as e:
            logger.debug(f"日期格式化失败: {e}")

    error_msg = f"无法识别的日期格式: {date_input}。支持: YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD"
    logger.debug(error_msg)
    raise ValueError(error_msg)
