"""
图片消息处理模块

提供图片消息的识别、描述获取和发送者信息提取功能。
与文本消息处理逻辑集成，支持统一时间线的生成。
"""

import datetime
import re
from dataclasses import dataclass
from typing import Any, Optional

from src.plugin_system.apis import (
    message_api,
    get_logger
)

logger = get_logger("Maizone.diary.image_processor")


@dataclass
class ImageData:
    """图片数据结构"""
    image_id: str
    sender_nickname: str
    description: str
    timestamp: datetime.datetime


class ImageProcessor:
    """图片消息处理器"""

    def __init__(self):
        pass

    def _is_image_message(self, msg: Any) -> bool:
        """检测消息是否为图片消息"""
        try:
            if hasattr(msg, 'is_picid') and msg.is_picid:
                return True

            plain_text = getattr(msg, 'processed_plain_text', None) or ""
            if re.search(r'\[picid:[a-f0-9\-]+\]', plain_text):
                return True

            image_markers = ['[图片', '[image']
            for marker in image_markers:
                if marker in plain_text.lower():
                    return True

            return False

        except Exception as e:
            logger.debug(f"图片消息检测失败: {e}")
            return False

    def _get_image_description(self, msg: Any) -> str:
        """获取图片描述信息"""
        try:
            plain_text = getattr(msg, 'processed_plain_text', None) or ""
            picid_match = re.search(r'\[picid:([a-f0-9\-]+)\]', plain_text)
            if picid_match:
                real_image_id = picid_match.group(1)
                description = message_api.translate_pid_to_description(real_image_id)
                if description and description.strip() and description.strip() != "[图片]":
                    return description.strip()

            if hasattr(msg, 'message_id') and msg.message_id:
                message_id = str(msg.message_id)
                description = message_api.translate_pid_to_description(message_id)
                if description and description.strip() and description.strip() != "[图片]":
                    return description.strip()

            for possible_field in ['pic_id', 'image_id', 'file_id']:
                if hasattr(msg, possible_field):
                    field_value = getattr(msg, possible_field)
                    if field_value and str(field_value) not in ['True', 'False', '']:
                        description = message_api.translate_pid_to_description(str(field_value))
                        if description and description.strip() and description.strip() != "[图片]":
                            return description.strip()

            sender_nickname = self._get_sender_nickname(msg)
            if sender_nickname and sender_nickname != "未知用户":
                return f"{sender_nickname}分享的图片"
            return "用户分享的图片"

        except Exception as e:
            logger.debug(f"获取图片描述失败: {e}")
            return "用户分享的图片"

    def _get_sender_nickname(self, msg: Any) -> str:
        """获取消息发送者的昵称"""
        try:
            user_info = getattr(msg, 'user_info', None)
            if not user_info:
                return "未知用户"

            if hasattr(user_info, 'user_cardname') and user_info.user_cardname:
                cardname = user_info.user_cardname.strip()
                if cardname:
                    return cardname

            if hasattr(user_info, 'user_nickname') and user_info.user_nickname:
                nickname = user_info.user_nickname.strip()
                if nickname:
                    return nickname

            if hasattr(user_info, 'user_id') and user_info.user_id:
                return str(user_info.user_id)

            return "未知用户"

        except Exception as e:
            logger.debug(f"获取发送者昵称失败: {e}")
            return "未知用户"

    def _generate_image_id(self, msg: Any) -> str:
        """生成图片的唯一标识符"""
        try:
            if hasattr(msg, 'is_picid') and msg.is_picid:
                return str(msg.is_picid)

            plain_text = getattr(msg, 'processed_plain_text', None) or ""
            picid_match = re.search(r'\[picid:([a-f0-9\-]+)\]', plain_text)
            if picid_match:
                return picid_match.group(1)

            if hasattr(msg, 'message_id') and msg.message_id:
                return f"img_{msg.message_id}"

            if hasattr(msg, 'time'):
                return f"img_{int(msg.time)}"

            return f"img_unknown_{id(msg)}"

        except Exception as e:
            logger.debug(f"生成图片ID失败: {e}")
            return f"img_error_{id(msg)}"

    def extract_image_data(self, msg: Any) -> Optional[ImageData]:
        """从消息中提取完整的图片数据"""
        try:
            if not self._is_image_message(msg):
                return None

            return ImageData(
                image_id=self._generate_image_id(msg),
                sender_nickname=self._get_sender_nickname(msg),
                description=self._get_image_description(msg),
                timestamp=datetime.datetime.fromtimestamp(msg.time)
            )

        except Exception as e:
            logger.error(f"提取图片数据失败: {e}")
            return None
