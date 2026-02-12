import datetime
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from src.common.logger import get_logger
from src.plugin_system import BaseCommand
from src.plugin_system.apis import llm_api, config_api, message_api
from .qzone import create_qzone_api, send_feed
from .helpers import check_permission, get_napcat_config_and_renew, build_diary_config

logger = get_logger("Maizone.commands")


# ===== 插件Command组件 =====
class MaizoneCommand(BaseCommand):
    """Maizone 统一命令 - 响应 /mz 命令"""

    command_name = "mz"
    command_description = "Maizone插件统一命令：发说说、日记管理"

    command_pattern = r"^\s*/mz(?:\s+(?P<sub>.+))?\s*$"
    command_help = "Maizone插件命令，使用 /mz help 查看帮助"
    command_examples = ["/mz help", "/mz send", "/mz send topic", "/mz diary generate"]
    intercept_message = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .diary import DiaryStorage
        self.storage = DiaryStorage()

    def check_permission(self, qq_account: str, section: str = "send") -> bool:
        return check_permission(self.get_config, qq_account, section, self.command_name)

    async def execute(self) -> tuple[bool, Optional[str], bool]:
        raw_sub = (self.matched_groups.get("sub") or "").strip()

        if not raw_sub or raw_sub == "help":
            await self._show_help()
            return True, "success", True

        # 解析子命令
        parts = raw_sub.split(None, 1)
        action = parts[0].lower()
        param = parts[1].strip() if len(parts) > 1 else ""

        # === 发说说 ===
        if action == "send":
            return await self._handle_send(param)

        # === 日记子命令 ===
        if action == "diary":
            return await self._dispatch_diary(param)

        await self.send_text(f"未知子命令: {action}\n使用 /mz help 查看帮助")
        return False, "unknown action", True

    # ==================== help ====================
    async def _show_help(self):
        help_text = """Maizone 帮助

发说说（需要send权限）：
/mz send - 发一条随机主题的说说
/mz send <主题> - 发一条指定主题的说说
/mz send custom - 发送自定义私聊内容的说说

日记（view对所有人开放，其余需要send权限）：
/mz diary generate - 生成今天的日记
/mz diary generate <日期> - 生成指定日期日记
/mz diary list - 日记列表和统计
/mz diary view - 查看今天的日记
/mz diary view <日期> - 查看指定日期日记
/mz diary view <日期> <编号> - 查看指定编号日记"""
        await self.send_text(help_text)

    # ==================== send ====================
    async def _handle_send(self, param: str) -> tuple[bool, Optional[str], bool]:
        """处理 /mz send [topic]"""
        # 权限检查
        user_id = self.message.message_info.user_info.user_id
        if not self.check_permission(user_id, "send"):
            logger.info(f"{user_id}无send权限")
            await self.send_text(f"{user_id}权限不足，无权使用此命令")
            return False, f"{user_id}权限不足", True
        logger.info(f"{user_id}拥有send权限")

        topic = param.strip() or None
        models = llm_api.get_available_models()
        text_model = self.get_config("models.text_model", "replyer")
        model_config = models[text_model]
        if not model_config:
            return False, "未配置LLM模型", True

        # 人格配置
        bot_personality = config_api.get_global_config("personality.personality", "一个机器人")
        bot_expression = config_api.get_global_config("personality.reply_style", "内容积极向上")

        # 核心配置
        try:
            host, port, napcat_token = await get_napcat_config_and_renew(self.get_config)
        except Exception as e:
            logger.error(f"更新cookies失败: {str(e)}")
            return False, "更新cookies失败", True

        # 图片相关配置
        enable_image = self.get_config("send.enable_image", False)
        image_dir = str(Path(__file__).parent.resolve() / "images")
        image_mode = self.get_config("send.image_mode", "random").lower()
        ai_probability = self.get_config("send.ai_probability", 0.5)
        image_number = self.get_config("send.image_number", 1)

        # 说说生成相关配置
        history_number = self.get_config("send.history_number", 5)
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        qzone = create_qzone_api()
        if not qzone:
            logger.error("创建QzoneAPI失败，cookie可能不存在")
            return False, "cookie不存在", True

        prompt_pre = self.get_config(
            "send.prompt",
            "你是'{bot_personality}'，现在是'{current_time}'你想写一条主题是'{topic}'的说说发表在qq空间上，"
            "{bot_expression}，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，可以适当使用颜文字，"
            "只输出一条说说正文的内容，不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )"
        )

        if topic:
            if topic.lower() == "custom":
                success = await send_feed("custom", image_dir, enable_image, image_mode, ai_probability, image_number)
                if not success:
                    return False, "发送说说失败", True
                await self.send_text("已发送说说：\n自定义内容")
                return True, "success", True
            data = {
                "current_time": current_time,
                "bot_personality": bot_personality,
                "topic": topic,
                "bot_expression": bot_expression,
            }
            prompt = prompt_pre.format(**data)
        else:
            data = {
                "current_time": current_time,
                "bot_personality": bot_personality,
                "bot_expression": bot_expression,
                "topic": "随机",
            }
            prompt = prompt_pre.format(**data)

        prompt += "\n以下是你以前发过的说说，写新说说时注意不要在相隔不长的时间发送相同主题的说说\n"
        prompt += await qzone.get_send_history(history_number)
        prompt += "\n不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )"

        show_prompt = self.get_config("models.show_prompt", False)
        if show_prompt:
            logger.info(f"生成说说prompt内容：{prompt}")

        success, story, reasoning, model_name = await llm_api.generate_with_model(
            prompt=prompt,
            model_config=model_config,
            request_type="story.generate",
            temperature=0.3,
            max_tokens=4096,
        )

        if not success:
            return False, "生成说说内容失败", True

        logger.info(f"成功生成说说内容：'{story}'")

        success = await send_feed(story, image_dir, enable_image, image_mode, ai_probability, image_number)
        if not success:
            return False, "发送说说失败", True
        await self.send_text(f"已发送说说：\n{story}")
        return True, "success", True

    # ==================== diary 分发 ====================
    async def _dispatch_diary(self, param: str) -> tuple[bool, Optional[str], bool]:
        """分发 /mz diary <action> [param]"""
        if not param:
            await self.send_text("用法: /mz diary <generate|list|view> [参数]\n使用 /mz help 查看帮助")
            return False, "missing diary action", True

        parts = param.split(None, 1)
        diary_action = parts[0].lower()
        diary_param = parts[1].strip() if len(parts) > 1 else ""

        if diary_action == "generate":
            user_id = self.message.message_info.user_info.user_id
            if not self.check_permission(user_id, "send"):
                logger.info(f"{user_id}无send权限")
                await self.send_text(f"{user_id}权限不足，无权使用此命令")
                return False, f"{user_id}权限不足", True
            return await self._handle_diary_generate(diary_param)
        elif diary_action == "list":
            user_id = self.message.message_info.user_info.user_id
            if not self.check_permission(user_id, "send"):
                logger.info(f"{user_id}无send权限")
                await self.send_text(f"{user_id}权限不足，无权使用此命令")
                return False, f"{user_id}权限不足", True
            return await self._handle_diary_list(diary_param)
        elif diary_action == "view":
            return await self._handle_diary_view(diary_param)

        await self.send_text(f"未知日记子命令: {diary_action}\n可用: generate, list, view")
        return False, "unknown diary action", True

    # ==================== diary generate ====================
    async def _handle_diary_generate(self, param: str) -> tuple[bool, Optional[str], bool]:
        from .diary import DiaryService, SmartFilterSystem, DiaryConstants

        if param:
            date = self._parse_date(param)
        else:
            date = datetime.datetime.now().strftime("%Y-%m-%d")

        if not date:
            await self.send_text(f"日期格式错误: {param}\n支持格式: YYYY-MM-DD")
            return False, "invalid date", True

        await self.send_text(f"正在生成 {date} 的日记...")

        diary_config = build_diary_config(self.get_config)
        diary_service = DiaryService(plugin_config=diary_config)

        filter_mode = self.get_config("diary.filter_mode", "all")
        target_chats_str = self.get_config("diary.target_chats", "")
        target_chats = [c.strip() for c in target_chats_str.split("\n") if c.strip()] if target_chats_str else []

        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
        start_time = date_obj.timestamp()
        current_time = datetime.datetime.now()
        if current_time.strftime("%Y-%m-%d") == date:
            end_time = current_time.timestamp()
        else:
            end_time = (date_obj + datetime.timedelta(days=1)).timestamp()

        messages = []
        if not target_chats:
            try:
                from src.plugin_system.apis import chat_api
                group_info = self.message.message_info.group_info if hasattr(self.message, 'message_info') else None
                if group_info and group_info.group_id:
                    stream = chat_api.get_stream_by_group_id(str(group_info.group_id))
                    if stream:
                        messages = message_api.get_messages_by_time_in_chat(
                            chat_id=stream.stream_id,
                            start_time=start_time,
                            end_time=end_time,
                            limit=0,
                            limit_mode="earliest",
                            filter_mai=False,
                            filter_command=False,
                        )
            except Exception:
                pass

        if not messages:
            filter_system = SmartFilterSystem()
            messages = filter_system.apply_filter_mode(filter_mode, target_chats, start_time, end_time)

        if not messages:
            try:
                messages = message_api.get_messages_by_time(
                    start_time=start_time,
                    end_time=end_time,
                    limit=0,
                    limit_mode="earliest",
                    filter_mai=False,
                )
            except Exception as e:
                logger.error(f"获取全局消息失败: {e}")

        min_msg_count = self.get_config("diary.min_message_count", DiaryConstants.MIN_MESSAGE_COUNT)
        if len(messages) < min_msg_count:
            await self.send_text(f"消息数量不足({len(messages)}/{min_msg_count}条)，无法生成日记")
            return False, "not enough messages", True

        success, diary_content = await diary_service.generate_diary_from_messages(date, messages, force_50k=True)

        if not success:
            await self.send_text(f"日记生成失败: {diary_content}")
            return False, diary_content, True

        qzone_result = ""
        try:
            qzone_success = await diary_service.publish_to_qzone(date, diary_content)
            qzone_result = " (已发布到QQ空间)" if qzone_success else " (QQ空间发布失败)"
        except Exception as e:
            qzone_result = f" (QQ空间发布异常: {str(e)[:50]})"

        await self.send_text(f"{date} 的日记已生成{qzone_result}:\n\n{diary_content}")
        return True, "success", True

    # ==================== diary list ====================
    async def _handle_diary_list(self, param: str) -> tuple[bool, Optional[str], bool]:
        stats = await self.storage.get_stats()
        diaries = await self.storage.list_diaries(limit=10)

        text_parts = [
            "日记统计:",
            f"  总数: {stats['total_count']}篇",
            f"  总字数: {stats['total_words']}字",
            f"  平均字数: {stats['avg_words']}字",
            f"  最新日期: {stats['latest_date']}",
            "",
        ]

        if diaries:
            text_parts.append("最近日记:")
            for i, diary in enumerate(diaries, 1):
                date = diary.get("date", "未知")
                word_count = diary.get("word_count", 0)
                status = diary.get("status", "未知")
                published = "已发布" if diary.get("is_published_qzone") else "未发布"
                text_parts.append(f"  {i}. {date} | {word_count}字 | {published} | {status}")
        else:
            text_parts.append("暂无日记记录")

        await self.send_text("\n".join(text_parts))
        return True, "success", True

    # ==================== diary view ====================
    async def _handle_diary_view(self, param: str) -> tuple[bool, Optional[str], bool]:
        params = param.split() if param else []

        if not params:
            date = datetime.datetime.now().strftime("%Y-%m-%d")
        else:
            date = self._parse_date(params[0])
            if not date:
                await self.send_text(f"日期格式错误: {params[0]}")
                return False, "invalid date", True

        diaries = await self.storage.get_diaries_by_date(date)

        if not diaries:
            await self.send_text(f"{date} 没有日记记录")
            return False, "no diary found", True

        if len(params) > 1:
            try:
                index = int(params[1]) - 1
                if 0 <= index < len(diaries):
                    diary = diaries[index]
                    content = diary.get("diary_content", "(无内容)")
                    word_count = diary.get("word_count", 0)
                    weather = diary.get("weather", "未知")
                    await self.send_text(f"{date} 第{index + 1}条日记 ({word_count}字, {weather}):\n\n{content}")
                    return True, "success", True
                else:
                    await self.send_text(f"编号超出范围，{date} 共有{len(diaries)}条日记")
                    return False, "index out of range", True
            except ValueError:
                pass

        diary = diaries[-1]
        content = diary.get("diary_content", "(无内容)")
        word_count = diary.get("word_count", 0)
        weather = diary.get("weather", "未知")
        published = "已发布QQ空间" if diary.get("is_published_qzone") else "未发布"

        text = f"{date} 的日记 ({word_count}字, {weather}, {published})"
        if len(diaries) > 1:
            text += f"\n(共{len(diaries)}条，当前显示最新一条，用 /mz diary view {date} <编号> 查看其他)"
        text += f"\n\n{content}"

        await self.send_text(text)
        return True, "success", True

    # ==================== 工具方法 ====================
    def _parse_date(self, date_str: str) -> Optional[str]:
        """解析日期字符串"""
        import re

        if date_str == "今天":
            return datetime.datetime.now().strftime("%Y-%m-%d")
        elif date_str == "昨天":
            return (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        elif date_str == "前天":
            return (datetime.datetime.now() - datetime.timedelta(days=2)).strftime("%Y-%m-%d")

        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
            try:
                date_obj = datetime.datetime.strptime(date_str, fmt)
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                continue

        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date_str):
            return date_str

        return None
