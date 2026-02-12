"""
消息获取与过滤模块

提供优化的消息获取和智能过滤功能：
- OptimizedMessageFetcher: 智能选择最适合的API获取消息
- SmartFilterSystem: 支持白名单/黑名单/全部消息过滤模式
"""

from typing import Any, List, Tuple

from src.plugin_system.apis import (
    message_api,
    chat_api,
    get_logger
)

logger = get_logger("Maizone.diary.message_fetcher")


class OptimizedMessageFetcher:
    """优化的消息获取器，智能选择最适合的API"""

    def get_messages_by_config(self, configs: List[str], start_time: float, end_time: float) -> List[Any]:
        """根据配置智能选择最适合的API获取消息"""
        all_messages = []
        private_qqs, group_qqs = self._parse_configs(configs)

        if private_qqs:
            private_messages = self._get_private_messages_optimized(private_qqs, start_time, end_time)
            all_messages.extend(private_messages)

        if group_qqs:
            group_messages = self._get_group_messages_optimized(group_qqs, start_time, end_time)
            all_messages.extend(group_messages)

        return sorted(all_messages, key=lambda x: x.time)

    def _get_private_messages_optimized(self, qq_numbers: List[str], start_time: float, end_time: float) -> List[Any]:
        """通过QQ号获取私聊消息（包含Bot回复）"""
        all_private_messages = []

        for user_qq in qq_numbers:
            try:
                private_stream = chat_api.get_stream_by_user_id(user_qq)
                if not private_stream:
                    logger.warning(f"未找到用户{user_qq}的私聊流，跳过")
                    continue

                chat_id = private_stream.stream_id

                messages = message_api.get_messages_by_time_in_chat(
                    chat_id=chat_id,
                    start_time=start_time,
                    end_time=end_time,
                    limit=0,
                    limit_mode="earliest",
                    filter_mai=False,
                    filter_command=False
                )

                all_private_messages.extend(messages)
                logger.info(f"私聊{user_qq} -> {chat_id} 获取到{len(messages)}条消息")

            except Exception as e:
                logger.error(f"获取私聊{user_qq}消息失败: {e}")

        return all_private_messages

    def _get_group_messages_optimized(self, group_qqs: List[str], start_time: float, end_time: float) -> List[Any]:
        """通过群号获取群聊消息"""
        all_group_messages = []

        for group_qq in group_qqs:
            try:
                stream = chat_api.get_stream_by_group_id(group_qq)
                if not stream:
                    logger.warning(f"无法获取群聊{group_qq}的stream信息")
                    continue

                chat_id = stream.stream_id

                messages = message_api.get_messages_by_time_in_chat(
                    chat_id=chat_id,
                    start_time=start_time,
                    end_time=end_time,
                    limit=0,
                    limit_mode="earliest",
                    filter_mai=False,
                    filter_command=False
                )

                all_group_messages.extend(messages)
                logger.debug(f"群聊{group_qq} -> {chat_id} 获取到{len(messages)}条消息")

            except Exception as e:
                logger.error(f"获取群聊{group_qq}消息失败: {e}")
        return all_group_messages

    def _is_private_message(self, msg: Any) -> bool:
        """判断是否为私聊消息"""
        try:
            if hasattr(msg, 'chat_info') and hasattr(msg.chat_info, 'group_id'):
                group_id = msg.chat_info.group_id
                return not group_id or group_id.strip() == ""

            if hasattr(msg, 'group_id'):
                group_id = msg.group_id
                return not group_id or group_id.strip() == ""

            return True

        except Exception as e:
            logger.debug(f"判断私聊消息时出错: {e}")
            return True

    def _parse_configs(self, configs: List[str]) -> Tuple[List[str], List[str]]:
        """解析配置，分离私聊和群聊"""
        private_qqs = []
        group_qqs = []

        for config in configs:
            if config.startswith('private:'):
                private_qqs.append(config[8:])
            elif config.startswith('group:'):
                group_qqs.append(config[6:])
            else:
                group_qqs.append(config)

        return private_qqs, group_qqs


class SmartFilterSystem:
    """智能过滤系统，支持多种过滤模式"""

    def __init__(self):
        self.fetcher = OptimizedMessageFetcher()

    def apply_filter_mode(self, filter_mode: str, configs: List[str], start_time: float, end_time: float) -> List[Any]:
        """应用过滤模式，智能选择最佳策略"""
        if filter_mode == "whitelist":
            if not configs:
                logger.info("白名单为空，返回空消息列表")
                return []
            logger.debug(f"白名单模式，处理{len(configs)}个配置")
            return self.fetcher.get_messages_by_config(configs, start_time, end_time)
        elif filter_mode == "blacklist":
            if not configs:
                logger.debug("黑名单为空，获取所有消息")
                return self._get_all_messages(start_time, end_time)

            logger.debug(f"黑名单模式，排除{len(configs)}个配置")
            all_messages = self._get_all_messages(start_time, end_time)
            return self._filter_excluded_messages(all_messages, configs)

        elif filter_mode == "all":
            logger.debug("全部消息模式")
            return self._get_all_messages(start_time, end_time)

        logger.warning(f"未知的过滤模式: {filter_mode}")
        return []

    def _get_all_messages(self, start_time: float, end_time: float) -> List[Any]:
        """获取所有消息"""
        try:
            messages = message_api.get_messages_by_time(
                start_time=start_time,
                end_time=end_time,
                limit=0,
                limit_mode="earliest",
                filter_mai=False
            )
            logger.debug(f"获取到{len(messages)}条全部消息")
            return messages
        except Exception as e:
            logger.error(f"获取所有消息失败: {e}")
            return []

    def _filter_excluded_messages(self, all_messages: List[Any], excluded_configs: List[str]) -> List[Any]:
        """过滤掉黑名单中的消息"""
        excluded_privates, excluded_groups = self.fetcher._parse_configs(excluded_configs)
        filtered_messages = []
        excluded_count = 0

        excluded_chat_ids = set()
        for group_qq in excluded_groups:
            try:
                stream = chat_api.get_stream_by_group_id(group_qq)
                if stream:
                    excluded_chat_ids.add(stream.stream_id)
            except Exception as e:
                logger.error(f"获取黑名单群聊{group_qq}的chat_id失败: {e}")

        for msg in all_messages:
            is_excluded = False

            if self.fetcher._is_private_message(msg):
                user_id = getattr(msg.user_info, 'user_id', None)
                if user_id and user_id in excluded_privates:
                    is_excluded = True
                    excluded_count += 1

            if not is_excluded:
                chat_id = getattr(msg, 'chat_id', None)
                if chat_id and chat_id in excluded_chat_ids:
                    is_excluded = True
                    excluded_count += 1

            if not is_excluded:
                filtered_messages.append(msg)

        logger.debug(f"黑名单过滤: 原始{len(all_messages)}条 -> 过滤后{len(filtered_messages)}条，排除{excluded_count}条")
        return filtered_messages
