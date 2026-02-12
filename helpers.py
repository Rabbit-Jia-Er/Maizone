"""Maizone 共享工具函数

提取 commands / actions / scheduled_tasks 中的重复模式：
- check_permission: 白名单/黑名单权限检查
- get_napcat_config_and_renew: 读取 Napcat 配置并刷新 Cookie
- build_diary_config: 构建 DiaryService 所需的配置字典
"""

from typing import Callable, List, Tuple

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
) -> Tuple[str, str, str]:
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
