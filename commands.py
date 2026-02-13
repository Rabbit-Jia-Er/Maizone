import datetime
import re
from pathlib import Path
from typing import Optional

from src.common.logger import get_logger
from src.plugin_system import BaseCommand
from src.plugin_system.apis import llm_api, config_api, message_api
from .qzone import create_qzone_api, send_feed
from .helpers import check_permission, get_napcat_config_and_renew, build_diary_config, build_send_prompt

logger = get_logger("Maizone.commands")


def _parse_date(date_str: str) -> Optional[str]:
    """解析日期字符串，返回 YYYY-MM-DD 或 None"""
    mapping = {"今天": 0, "昨天": -1, "前天": -2}
    if date_str in mapping:
        return (datetime.datetime.now() + datetime.timedelta(days=mapping[date_str])).strftime("%Y-%m-%d")
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date_str):
        return date_str
    return None


# 子命令关键词（不会被当作发说说主题）
_KEYWORDS = {"gen", "generate", "ls", "list", "v", "view", "custom", "help"}


class MaizoneCommand(BaseCommand):
    """/zn 统一命令"""

    command_name = "zn"
    command_description = "Maizone: 发说说、日记"

    command_pattern = r"^\s*/zn(?:\s+(?P<sub>.+))?\s*$"
    command_help = "/zn help 查看帮助"
    command_examples = ["/zn 今日穿搭", "/zn gen", "/zn ls", "/zn v"]
    intercept_message = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .diary import DiaryStorage
        self.storage = DiaryStorage()

    def _check_perm(self, section: str = "send") -> tuple[bool, str]:
        uid = self.message.message_info.user_info.user_id
        ok = check_permission(self.get_config, uid, section, self.command_name)
        return ok, uid

    async def execute(self) -> tuple[bool, Optional[str], bool]:
        raw = (self.matched_groups.get("sub") or "").strip()

        if not raw or raw == "help":
            await self._help()
            return True, "success", True

        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        param = parts[1].strip() if len(parts) > 1 else ""

        # /zn gen [日期]
        if cmd in ("gen", "generate"):
            ok, uid = self._check_perm()
            if not ok:
                await self.send_text(f"{uid}权限不足")
                return False, "no perm", True
            return await self._diary_gen(param)

        # /zn ls
        if cmd in ("ls", "list"):
            ok, uid = self._check_perm()
            if not ok:
                await self.send_text(f"{uid}权限不足")
                return False, "no perm", True
            return await self._diary_list()

        # /zn v [日期] [编号]
        if cmd in ("v", "view"):
            return await self._diary_view(param)

        # /zn custom
        if cmd == "custom":
            ok, uid = self._check_perm()
            if not ok:
                await self.send_text(f"{uid}权限不足")
                return False, "no perm", True
            return await self._send_custom()

        # /zn 2025-01-01 [编号] → 查看日记
        date = _parse_date(cmd)
        if date:
            return await self._diary_view(f"{date} {param}".strip() if param else date)

        # /zn <主题> → 发说说
        ok, uid = self._check_perm()
        if not ok:
            await self.send_text(f"{uid}权限不足")
            return False, "no perm", True
        return await self._send(raw)

    # ==================== help ====================
    async def _help(self):
        await self.send_text("""/zn <主题> - 发说说
/zn custom - 发自定义说说
/zn gen [日期] - 生成日记
/zn ls - 日记列表
/zn v [日期] - 查看日记
/zn <日期> - 查看日记""")

    # ==================== send ====================
    async def _send(self, topic: str) -> tuple[bool, Optional[str], bool]:
        models = llm_api.get_available_models()
        text_model = self.get_config("models.text_model", "replyer")
        model_config = models[text_model]
        if not model_config:
            return False, "未配置LLM模型", True

        bot_personality = config_api.get_global_config("personality.personality", "一个机器人")
        bot_expression = config_api.get_global_config("personality.reply_style", "内容积极向上")

        try:
            await get_napcat_config_and_renew(self.get_config)
        except Exception as e:
            logger.error(f"更新cookies失败: {e}")
            return False, "更新cookies失败", True

        image_dir = str(Path(__file__).parent.resolve() / "images")
        enable_image = self.get_config("send.enable_image", False)
        image_mode = self.get_config("send.image_mode", "random").lower()
        ai_probability = self.get_config("send.ai_probability", 0.5)
        image_number = self.get_config("send.image_number", 1)
        history_number = self.get_config("send.history_number", 5)

        qzone = create_qzone_api()
        if not qzone:
            return False, "cookie不存在", True

        if not topic:
            topic = "随机"

        prompt = await build_send_prompt(self.get_config, qzone, topic, bot_personality, bot_expression, history_number)

        if self.get_config("models.show_prompt", False):
            logger.info(f"生成说说prompt: {prompt}")

        success, story, reasoning, model_name = await llm_api.generate_with_model(
            prompt=prompt,
            model_config=model_config,
            request_type="story.generate",
            temperature=0.3,
            max_tokens=4096,
        )

        if not success:
            return False, "生成说说内容失败", True

        logger.info(f"生成说说内容: '{story}'")

        success = await send_feed(story, image_dir, enable_image, image_mode, ai_probability, image_number)
        if not success:
            return False, "发送说说失败", True
        await self.send_text(f"已发送说说：\n{story}")
        return True, "success", True

    async def _send_custom(self) -> tuple[bool, Optional[str], bool]:
        image_dir = str(Path(__file__).parent.resolve() / "images")
        enable_image = self.get_config("send.enable_image", False)
        image_mode = self.get_config("send.image_mode", "random").lower()
        ai_probability = self.get_config("send.ai_probability", 0.5)
        image_number = self.get_config("send.image_number", 1)

        try:
            await get_napcat_config_and_renew(self.get_config)
        except Exception as e:
            logger.error(f"更新cookies失败: {e}")
            return False, "更新cookies失败", True

        success = await send_feed("custom", image_dir, enable_image, image_mode, ai_probability, image_number)
        if not success:
            return False, "发送说说失败", True
        await self.send_text("已发送说说：\n自定义内容")
        return True, "success", True

    # ==================== diary gen ====================
    async def _diary_gen(self, param: str) -> tuple[bool, Optional[str], bool]:
        from .diary import DiaryService, SmartFilterSystem, DiaryConstants

        date = _parse_date(param) if param else datetime.datetime.now().strftime("%Y-%m-%d")
        if not date:
            await self.send_text(f"日期格式错误: {param}")
            return False, "invalid date", True

        await self.send_text(f"正在生成 {date} 的日记...")

        diary_config = build_diary_config(self.get_config)
        diary_service = DiaryService(plugin_config=diary_config)

        filter_mode = self.get_config("diary.filter_mode", "all")
        target_chats_str = self.get_config("diary.target_chats", "")
        target_chats = [c.strip() for c in target_chats_str.split("\n") if c.strip()] if target_chats_str else []

        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
        start_time = date_obj.timestamp()
        now = datetime.datetime.now()
        end_time = now.timestamp() if now.strftime("%Y-%m-%d") == date else (date_obj + datetime.timedelta(days=1)).timestamp()

        messages = []
        if not target_chats:
            try:
                from src.plugin_system.apis import chat_api
                group_info = self.message.message_info.group_info if hasattr(self.message, 'message_info') else None
                if group_info and group_info.group_id:
                    stream = chat_api.get_stream_by_group_id(str(group_info.group_id))
                    if stream:
                        messages = message_api.get_messages_by_time_in_chat(
                            chat_id=stream.stream_id, start_time=start_time, end_time=end_time,
                            limit=0, limit_mode="earliest", filter_mai=False, filter_command=False,
                        )
            except Exception:
                pass

        if not messages:
            filter_system = SmartFilterSystem()
            messages = filter_system.apply_filter_mode(filter_mode, target_chats, start_time, end_time)

        if not messages:
            try:
                messages = message_api.get_messages_by_time(
                    start_time=start_time, end_time=end_time,
                    limit=0, limit_mode="earliest", filter_mai=False,
                )
            except Exception as e:
                logger.error(f"获取全局消息失败: {e}")

        min_msg_count = self.get_config("diary.min_message_count", DiaryConstants.MIN_MESSAGE_COUNT)
        if len(messages) < min_msg_count:
            await self.send_text(f"消息不足({len(messages)}/{min_msg_count}条)")
            return False, "not enough messages", True

        success, diary_content = await diary_service.generate_diary_from_messages(date, messages, force_50k=True)
        if not success:
            await self.send_text(f"生成失败: {diary_content}")
            return False, diary_content, True

        qzone_result = ""
        try:
            ok = await diary_service.publish_to_qzone(date, diary_content)
            qzone_result = " (已发布到空间)" if ok else " (空间发布失败)"
        except Exception as e:
            qzone_result = f" (空间发布异常: {str(e)[:50]})"

        await self.send_text(f"{date} 日记已生成{qzone_result}:\n\n{diary_content}")
        return True, "success", True

    # ==================== diary list ====================
    async def _diary_list(self) -> tuple[bool, Optional[str], bool]:
        stats = await self.storage.get_stats()
        diaries = await self.storage.list_diaries(limit=10)

        lines = [
            f"共{stats['total_count']}篇 | 均{stats['avg_words']}字 | 最新{stats['latest_date']}",
            "",
        ]
        if diaries:
            for i, d in enumerate(diaries, 1):
                pub = "已发" if d.get("is_published_qzone") else "未发"
                lines.append(f"  {i}. {d.get('date','?')} | {d.get('word_count',0)}字 | {pub}")
        else:
            lines.append("暂无日记")

        await self.send_text("\n".join(lines))
        return True, "success", True

    # ==================== diary view ====================
    async def _diary_view(self, param: str) -> tuple[bool, Optional[str], bool]:
        params = param.split() if param else []

        date = _parse_date(params[0]) if params else datetime.datetime.now().strftime("%Y-%m-%d")
        if params and not date:
            await self.send_text(f"日期格式错误: {params[0]}")
            return False, "invalid date", True
        if not date:
            date = datetime.datetime.now().strftime("%Y-%m-%d")

        diaries = await self.storage.get_diaries_by_date(date)
        if not diaries:
            await self.send_text(f"{date} 没有日记")
            return False, "no diary", True

        if len(params) > 1:
            try:
                idx = int(params[1]) - 1
                if 0 <= idx < len(diaries):
                    d = diaries[idx]
                    await self.send_text(f"{date} #{idx+1} ({d.get('word_count',0)}字):\n\n{d.get('diary_content','')}")
                    return True, "success", True
                await self.send_text(f"编号超出范围，共{len(diaries)}条")
                return False, "out of range", True
            except ValueError:
                pass

        d = diaries[-1]
        text = f"{date} 的日记 ({d.get('word_count',0)}字)"
        if len(diaries) > 1:
            text += f"\n(共{len(diaries)}条，/zn {date} <编号> 看其他)"
        text += f"\n\n{d.get('diary_content','')}"
        await self.send_text(text)
        return True, "success", True
