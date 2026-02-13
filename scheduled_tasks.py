import asyncio
import random
import datetime
import os
import json
from pathlib import Path

from src.common.logger import get_logger
from src.plugin_system.apis import llm_api, config_api, person_api

from .qzone import monitor_read_feed, reply_feed, comment_feed, like_feed
from .helpers import get_napcat_config_and_renew, build_diary_config, build_comment_prompt

logger = get_logger("Maizone.定时任务")

# 添加文件读写锁
_processed_list_lock = asyncio.Lock()
_processed_comments_lock = asyncio.Lock()


def _is_in_silent_period(silent_hours_config: str, like_during_silent: bool = False, comment_during_silent: bool = False) -> tuple[bool, bool, bool]:
    """
    检查当前时间是否在静默时间段内

    Args:
        silent_hours_config: 静默时间段配置，格式如"23:00-07:00,12:00-14:00"
        like_during_silent: 静默时间段内是否允许点赞
        comment_during_silent: 静默时间段内是否允许评论

    Returns:
        tuple: (是否在静默时间段, 是否允许点赞, 是否允许评论)
    """
    if not silent_hours_config or not silent_hours_config.strip():
        return False, True, True

    try:
        now = datetime.datetime.now()
        current_time = now.hour * 60 + now.minute  # 当前时间转换为分钟数

        # 解析静默时间段
        periods = silent_hours_config.split(',')
        is_silent = False

        for period in periods:
            period = period.strip()
            if not period:
                continue

            # 解析时间段
            if '-' not in period:
                continue

            start_str, end_str = period.split('-', 1)
            start_time = _parse_time_to_minutes(start_str.strip())
            end_time = _parse_time_to_minutes(end_str.strip())

            if start_time is None or end_time is None:
                continue

            # 检查时间范围（处理跨天的情况）
            if start_time <= end_time:
                # 不跨天，如 12:00-14:00
                if start_time <= current_time <= end_time:
                    is_silent = True
                    break
            else:
                # 跨天，如 23:00-07:00
                if current_time >= start_time or current_time <= end_time:
                    is_silent = True
                    break

        # 如果在静默时间段内，返回相应的权限控制
        if is_silent:
            return True, like_during_silent, comment_during_silent

        return False, True, True

    except Exception as e:
        logger.error(f"解析静默时间段配置失败: {str(e)}")
        return False, True, True


def _parse_time_to_minutes(time_str: str) -> int:
    """
    将时间字符串转换为分钟数

    Args:
        time_str: 时间字符串，格式"HH:MM"

    Returns:
        int: 分钟数，解析失败返回None
    """
    try:
        if ':' not in time_str:
            return None

        hour_str, minute_str = time_str.split(':', 1)
        hour = int(hour_str.strip())
        minute = int(minute_str.strip())

        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour * 60 + minute
        else:
            return None

    except (ValueError, AttributeError):
        return None


# ===== 定时任务功能 =====
async def _save_processed_list(processed_list: dict[str, list[str]]):
    """保存已处理说说及评论字典到文件"""
    async with _processed_list_lock:
        try:
            file_path = str(Path(__file__).parent.resolve() / "processed_list.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(processed_list, f, ensure_ascii=False, indent=2)
                logger.debug(f"已保存已处理说说列表，内容: {processed_list}")
        except Exception as e:
            logger.error(f"保存已处理说说失败: {str(e)}")


async def _load_processed_list() -> dict[str, list[str]]:
    """从文件加载已处理说说及评论字典"""
    async with _processed_list_lock:
        file_path = str(Path(__file__).parent.resolve() / "processed_list.json")

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    logger.debug(f"正在加载已处理说说列表，内容: {loaded_data}")
                    return loaded_data
            except Exception as e:
                logger.error(f"加载已处理说说失败: {str(e)}")
                return {}
        logger.warning("未找到已处理说说列表，将创建新列表")
        return {}


async def _save_processed_comments(processed_comments: dict[str, list[str]]):
    """保存已处理评论到独立的文件"""
    async with _processed_comments_lock:
        try:
            file_path = str(Path(__file__).parent.resolve() / "processed_comments.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(processed_comments, f, ensure_ascii=False, indent=2)
                logger.debug(f"已保存已处理评论列表，内容: {processed_comments}")
        except Exception as e:
            logger.error(f"保存已处理评论失败: {str(e)}")


async def _load_processed_comments() -> dict[str, list[str]]:
    """从文件加载已处理评论字典"""
    async with _processed_comments_lock:
        file_path = str(Path(__file__).parent.resolve() / "processed_comments.json")

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    logger.debug(f"正在加载已处理评论列表，内容: {loaded_data}")
                    return loaded_data
            except Exception as e:
                logger.error(f"加载已处理评论失败: {str(e)}")
                return {}
        logger.warning("未找到已处理评论列表，将创建新列表")
        return {}


class FeedMonitor:
    """刷空间核心逻辑，由 RoutineRunner 调用 check_feeds()"""

    def __init__(self, plugin):
        self.plugin = plugin

    async def check_feeds(self, processed_list: dict[str, list[str]], processed_comments: dict[str, list[str]]):
        """检查空间说说并回复未读说说和评论"""

        # 检查时间段控制
        silent_hours = self.plugin.get_config("monitor.silent_hours", "")
        like_during_silent = self.plugin.get_config("monitor.like_during_silent", False)
        comment_during_silent = self.plugin.get_config("monitor.comment_during_silent", False)

        is_silent, allow_like, allow_comment = _is_in_silent_period(silent_hours, like_during_silent, comment_during_silent)

        if is_silent:
            logger.info(f"当前时间在静默时间段内，点赞权限: {allow_like}, 评论权限: {allow_comment}")
            # 如果在静默时间段且不允许点赞和评论，直接返回
            if not allow_like and not allow_comment:
                logger.info("静默时间段内不允许点赞和评论，跳过本次刷空间")
                return True, "静默时间段内跳过刷空间"

        qq_account = config_api.get_global_config("bot.qq_account", "")
        show_prompt = self.plugin.get_config("models.show_prompt", False)
        self_readnum = self.plugin.get_config("monitor.self_readnum", 5)
        #模型配置
        models = llm_api.get_available_models()
        text_model = self.plugin.get_config("models.text_model", "replyer")
        model_config = models[text_model]
        if not model_config:
            return False, "未配置LLM模型"

        bot_personality = config_api.get_global_config("personality.personality", "一个机器人")
        bot_expression = config_api.get_global_config("personality.reply_style", "内容积极向上")
        # 更新cookies
        try:
            await get_napcat_config_and_renew(self.plugin.get_config)
        except Exception as e:
            logger.error(f"更新cookies失败: {str(e)}")
            return False, "更新cookies失败"

        try:
            logger.info(f"监控任务: 正在获取说说列表")
            feeds_list = await monitor_read_feed(self_readnum)
        except Exception as e:
            logger.error(f"获取说说列表失败: {str(e)}")
            return False, "获取说说列表失败"
            # 逐条点赞回复
        try:
            if len(feeds_list) == 0:
                logger.info('未读取到新说说')
                return True, "success"
            # 获取自动阅读名单及类型
            read_list = self.plugin.get_config("monitor.read_list", [])
            list_type = self.plugin.get_config("monitor.read_list_type", "whitelist")
            for feed in feeds_list:
                await asyncio.sleep(3 + random.random())
                content = feed["content"]
                if feed["images"]:
                    for image in feed["images"]:
                        content = content + image
                fid = feed["tid"]
                target_qq = feed["target_qq"]
                rt_con = feed.get("rt_con", "")
                comments_list = feed["comments"]
                # 名单机制：根据类型判断处理
                in_list = str(target_qq) in [str(q) for q in read_list]
                if (list_type == "whitelist" and not in_list) or (list_type == "blacklist" and in_list):
                    logger.info(f"跳过不在名单策略内的QQ号: {target_qq}")
                    continue
                #回复自己的说说评论
                if target_qq == qq_account:
                    enable_auto_reply = self.plugin.get_config("monitor.enable_auto_reply", False)
                    if not enable_auto_reply:
                        continue
                    #获取未回复的评论
                    list_to_reply = [] #待回复的评论
                    if comments_list:
                        for comment in comments_list:
                            comment_qq = comment.get('qq_account', '')
                            if int(comment_qq) != int(qq_account): #只考虑不是自己的评论
                                if comment['comment_tid'] not in processed_comments.get(fid, []): #只考虑未处理过的评论
                                    list_to_reply.append(comment) #添加到待回复列表

                    if len(list_to_reply) == 0:
                        continue
                    for comment in list_to_reply:
                        #逐条回复评论
                        user_id = comment['qq_account']
                        person_id = person_api.get_person_id("qq", user_id)
                        impression = await person_api.get_person_value(person_id, "memory_points", ["无"])
                        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")  #获取当前时间
                        prompt_pre = self.plugin.get_config("monitor.reply_prompt", "你是'{bot_personality}'，你的好友'{nickname}'在'{created_time}'评论了你QQ空间上的一条内容为"
                                                "'{content}'的说说，你的好友对该说说的评论为:'{comment_content}'，"
                                                "现在是'{current_time}'，你想要对此评论进行回复，你对该好友的印象是:"
                                                "'{impression}'，若与你的印象点相关，可以适当回复相关内容，无关则忽略此印象，"
                                                "{bot_expression}，回复的平淡一些，简短一些，说中文，不要刻意突出自身学科背景，不要浮夸，不要夸张修辞，"
                                                "不要输出多余内容(包括前后缀，冒号和引号，括号()，表情包，at或 @等 )。只输出回复内容")
                        data = {
                            "current_time": current_time,
                            "created_time": comment['created_time'],
                            "bot_personality": bot_personality,
                            "bot_expression": bot_expression,
                            "nickname": comment['nickname'],
                            "content": content,
                            "comment_content": comment['content'],
                            "impression": impression,
                        }
                        prompt = prompt_pre.format(**data)
                        logger.info(f"正在回复{comment['nickname']}的评论：{comment['content']}...")

                        if show_prompt:
                            logger.info(f"回复评论prompt内容：{prompt}")

                        success, reply, reasoning, model_name = await llm_api.generate_with_model(
                            prompt=prompt,
                            model_config=model_config,
                            request_type="story.generate",
                            temperature=0.3,
                            max_tokens=4096
                        )

                        if not success:
                            return False, "生成回复内容失败"

                        logger.info(f"正在回复{comment['nickname']}的评论：{comment['content']}...")

                        await get_napcat_config_and_renew(self.plugin.get_config)
                        success = await reply_feed(fid, target_qq, comment['nickname'], reply, comment['comment_tid'])
                        if not success:
                            logger.error(f"回复评论{comment['content']}失败")
                            return False, "回复评论失败"
                        logger.info(f"发送回复'{reply}'成功")
                        # 只有在成功发送评论后才将其标记为已处理
                        processed_comments.setdefault(fid, []).append(comment['comment_tid'])
                        # 为防止字典无限增长，限制字典大小
                        while len(processed_comments) > self.plugin.get_config("monitor.processed_comments_cache_size", 100):
                            oldest_fid = next(iter(processed_comments))
                            processed_comments.pop(oldest_fid)
                        await asyncio.sleep(5 + random.random() * 5)
                    continue
                # 评论他人说说
                if fid in processed_list:
                    # 该说说已处理过，跳过
                    continue
                person_id = person_api.get_person_id("qq", target_qq)
                impression = await person_api.get_person_value(person_id, "memory_points", ["无"])
                created_time = feed.get("created_time", "未知时间")

                prompt = build_comment_prompt(
                    self.plugin.get_config, target_qq, content,
                    created_time, bot_personality, bot_expression,
                    impression, rt_con,
                )
                logger.info(f"正在评论'{target_qq}'的说说：{content[:30]}...")

                if show_prompt:
                    logger.info(f"评论说说prompt内容：{prompt}")

                success, comment, reasoning, model_name = await llm_api.generate_with_model(
                    prompt=prompt,
                    model_config=model_config,
                    request_type="story.generate",
                    temperature=0.3,
                    max_tokens=4096
                )

                if not success:
                    return False, "生成评论内容失败"

                logger.info(f"成功生成评论内容：'{comment}'，即将发送")

                # 根据时间段控制决定是否评论
                if allow_comment and random.random() <= self.plugin.get_config("monitor.comment_possibility", 1.0):
                    success = await comment_feed(target_qq, fid, comment)
                    if not success:
                        logger.error(f"评论说说{content}失败")
                        return False, "评论说说失败"
                    logger.info(f"发送评论'{comment}'成功")
                else:
                    logger.info(f"静默时间段内或按概率跳过，跳过评论")

                # 根据时间段控制决定是否点赞
                if allow_like and random.random() <= self.plugin.get_config("monitor.like_possibility", 1.0):
                    # 点赞说说
                    success = await like_feed(target_qq, fid)
                    if not success:
                        logger.error(f"点赞说说{content}失败")
                        return False, "点赞说说失败"
                    logger.info(f'点赞说说{content[:10]}..成功')
                else:
                    logger.info(f"静默时间段内或按概率跳过，跳过点赞")
                # 记录该说说已处理
                processed_list[fid] = []
                while len(processed_list) > self.plugin.get_config("monitor.processed_feeds_cache_size", 100):
                    # 为防止字典无限增长，限制字典大小
                    oldest_fid = next(iter(processed_list))
                    processed_list.pop(oldest_fid)
                await _save_processed_list(processed_list)  # 每处理一条说说即保存
            return True, 'success'
        except Exception as e:
            logger.error(f"点赞评论失败: {str(e)}")
            return False, "点赞评论失败"


class ScheduleSender:
    """日记生成与发布（由 RoutineRunner 调用 generate_and_publish_diary()）"""

    def __init__(self, plugin):
        self.plugin = plugin

    async def generate_and_publish_diary(self):
        """生成日记并发布到QQ空间"""
        try:
            from .diary import DiaryService, SmartFilterSystem, DiaryConstants

            today = datetime.datetime.now().strftime("%Y-%m-%d")

            # 构建 diary 配置字典供 DiaryService 使用
            diary_config = build_diary_config(self.plugin.get_config)

            diary_service = DiaryService(plugin_config=diary_config)

            # 获取消息
            filter_mode = self.plugin.get_config("diary.filter_mode", "all")
            target_chats_str = self.plugin.get_config("diary.target_chats", "")
            target_chats = [c.strip() for c in target_chats_str.split("\n") if c.strip()] if target_chats_str else []

            date_obj = datetime.datetime.strptime(today, "%Y-%m-%d")
            start_time = date_obj.timestamp()
            end_time = datetime.datetime.now().timestamp()

            filter_system = SmartFilterSystem()
            messages = filter_system.apply_filter_mode(filter_mode, target_chats, start_time, end_time)

            min_msg_count = self.plugin.get_config("diary.min_message_count", DiaryConstants.MIN_MESSAGE_COUNT)
            if len(messages) < min_msg_count:
                logger.info(f"日记生成跳过: 消息数量不足({len(messages)}/{min_msg_count})")
                return

            success, diary_content = await diary_service.generate_diary_from_messages(today, messages, force_50k=True)

            if not success:
                logger.error(f"定时日记生成失败: {today} - {diary_content}")
                return

            # 使用 Maizone 的 qzone_api 发布
            qzone_success = await diary_service.publish_to_qzone(today, diary_content)
            if qzone_success:
                logger.info(f"定时日记生成成功: {today} ({len(diary_content)}字) - QQ空间发布成功")
            else:
                logger.info(f"定时日记生成成功: {today} ({len(diary_content)}字) - QQ空间发布失败")

        except Exception as e:
            logger.error(f"定时生成日记出错: {e}")