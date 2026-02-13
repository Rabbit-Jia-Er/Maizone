"""Maizone Routine Mode - 日程驱动的统一行为管理

RoutineRunner 由 autonomous_planning_plugin 的日程数据驱动所有自动行为
（发说说 / 刷空间 / 日记）。

日程适配层（ActivityType / ActivityInfo / PlanningPluginProvider）
复用 mais_art_journal 的 schedule_provider 模式，在 Maizone 内独立实现，
避免跨插件导入。
"""

import asyncio
import datetime
import json
import os
import sqlite3
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, List

from src.common.logger import get_logger
from src.plugin_system.apis import llm_api, config_api

from .qzone import create_qzone_api, send_feed
from .helpers import get_napcat_config_and_renew, build_send_prompt

logger = get_logger("Maizone.routine")


# ============================================================
# 日程适配层（独立实现，与 mais_art_journal 结构一致）
# ============================================================

class ActivityType(Enum):
    """活动类型枚举"""
    SLEEPING = "sleeping"
    WAKING_UP = "waking_up"
    EATING = "eating"
    WORKING = "working"
    STUDYING = "studying"
    EXERCISING = "exercising"
    RELAXING = "relaxing"
    SOCIALIZING = "socializing"
    COMMUTING = "commuting"
    HOBBY = "hobby"
    SELF_CARE = "self_care"
    OTHER = "other"


@dataclass
class ActivityInfo:
    """活动信息数据类"""
    activity_type: ActivityType
    description: str
    mood: str = "neutral"
    time_point: str = ""


# ---------- goal_type / description → ActivityType 映射 ----------

_TYPE_MAP: dict[str, ActivityType] = {
    # 英文关键词
    "work": ActivityType.WORKING,
    "study": ActivityType.STUDYING,
    "exercise": ActivityType.EXERCISING,
    "eat": ActivityType.EATING,
    "meal": ActivityType.EATING,
    "rest": ActivityType.RELAXING,
    "relax": ActivityType.RELAXING,
    "social": ActivityType.SOCIALIZING,
    "hobby": ActivityType.HOBBY,
    "sleep": ActivityType.SLEEPING,
    "self_care": ActivityType.SELF_CARE,
    "commut": ActivityType.COMMUTING,
    # 中文关键词
    "工作": ActivityType.WORKING,
    "办公": ActivityType.WORKING,
    "会议": ActivityType.WORKING,
    "学习": ActivityType.STUDYING,
    "阅读": ActivityType.STUDYING,
    "读书": ActivityType.STUDYING,
    "审阅": ActivityType.STUDYING,
    "看书": ActivityType.STUDYING,
    "研究": ActivityType.STUDYING,
    "运动": ActivityType.EXERCISING,
    "锻炼": ActivityType.EXERCISING,
    "健身": ActivityType.EXERCISING,
    "散步": ActivityType.EXERCISING,
    "吃": ActivityType.EATING,
    "餐": ActivityType.EATING,
    "料理": ActivityType.EATING,
    "烹饪": ActivityType.EATING,
    "休息": ActivityType.RELAXING,
    "放松": ActivityType.RELAXING,
    "泡澡": ActivityType.RELAXING,
    "泡浴": ActivityType.RELAXING,
    "聊天": ActivityType.SOCIALIZING,
    "交流": ActivityType.SOCIALIZING,
    "社交": ActivityType.SOCIALIZING,
    "睡": ActivityType.SLEEPING,
    "梦": ActivityType.SLEEPING,
    "入眠": ActivityType.SLEEPING,
    "午休": ActivityType.SLEEPING,
    "小憩": ActivityType.SLEEPING,
    "梳妆": ActivityType.SELF_CARE,
    "打扮": ActivityType.SELF_CARE,
    "化妆": ActivityType.SELF_CARE,
    "护肤": ActivityType.SELF_CARE,
    "通勤": ActivityType.COMMUTING,
    "赶路": ActivityType.COMMUTING,
    "出行": ActivityType.COMMUTING,
    "起床": ActivityType.WAKING_UP,
    "醒": ActivityType.WAKING_UP,
}


def _classify_activity(goal_type: str, description: str) -> ActivityType:
    """根据 goal_type 和 description 推断 ActivityType"""
    combined = (goal_type + " " + description).lower()
    for key, atype in _TYPE_MAP.items():
        if key in combined:
            return atype
    return ActivityType.OTHER


def _row_to_activity(row: dict, current_time: str) -> ActivityInfo:
    """将数据库行转换为 ActivityInfo"""
    description = row.get("description", "") or row.get("name", "") or "日常活动"
    goal_type = (row.get("goal_type", "") or "").lower()
    activity_type = _classify_activity(goal_type, description)
    return ActivityInfo(
        activity_type=activity_type,
        description=description,
        mood="neutral",
        time_point=current_time,
    )


# ============================================================
# PlanningPluginProvider - 读取 autonomous_planning 的 SQLite 数据库
# ============================================================

class PlanningPluginProvider:
    """从 autonomous_planning 插件的 SQLite 数据库读取当前活动"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        logger.info(f"PlanningPluginProvider 初始化, db: {db_path}")

    async def get_current_activity(self) -> Optional[ActivityInfo]:
        """获取当前时间对应的活动"""
        try:
            if not os.path.exists(self.db_path):
                return None

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            now = datetime.datetime.now()
            current_time_str = now.strftime("%H:%M")
            today_str = now.strftime("%Y-%m-%d")
            current_minutes = now.hour * 60 + now.minute

            # 优先获取今天的活跃目标
            rows = []
            try:
                cursor.execute("""
                    SELECT * FROM goals
                    WHERE status = 'active'
                    AND substr(created_at, 1, 10) = ?
                    ORDER BY created_at DESC
                    LIMIT 20
                """, (today_str,))
                rows = cursor.fetchall()
            except Exception:
                pass

            conn.close()

            if not rows:
                return None

            # 尝试匹配当前时间窗口
            for row in rows:
                row_dict = dict(row)
                time_window = self._extract_time_window(row_dict)
                if time_window and len(time_window) == 2:
                    start_min, end_min = int(time_window[0]), int(time_window[1])
                    if self._is_minutes_in_range(current_minutes, start_min, end_min):
                        return _row_to_activity(row_dict, current_time_str)

            # 无精确匹配，返回最新记录
            return _row_to_activity(dict(rows[0]), current_time_str)

        except Exception as e:
            logger.error(f"PlanningPluginProvider 查询失败: {e}")
            return None

    @staticmethod
    def _extract_time_window(row: dict) -> Optional[List[int]]:
        params_raw = row.get("parameters")
        if not params_raw:
            return None
        try:
            params = json.loads(params_raw) if isinstance(params_raw, str) else params_raw
            return params.get("time_window")
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _is_minutes_in_range(current: int, start: int, end: int) -> bool:
        if end < start:
            return current >= start or current <= end
        return start <= current <= end


def _find_planning_db() -> Optional[str]:
    """自动查找 autonomous_planning 数据库"""
    plugins_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    search_dirs = [
        os.path.join(plugins_dir, "autonomous_planning_plugin"),
        os.path.join(plugins_dir, "autonomous_planning"),
    ]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        check_dirs = [search_dir, os.path.join(search_dir, "data")]
        for check_dir in check_dirs:
            if not os.path.isdir(check_dir):
                continue
            for fname in os.listdir(check_dir):
                if fname.endswith((".db", ".sqlite", ".sqlite3")):
                    db_path = os.path.join(check_dir, fname)
                    try:
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='goals'")
                        if cursor.fetchone():
                            conn.close()
                            logger.info(f"找到 autonomous_planning 数据库: {db_path}")
                            return db_path
                        conn.close()
                    except Exception:
                        pass
    return None


# ============================================================
# RoutineRunner - 日程驱动的统一行为管理器
# ============================================================

class RoutineRunner:
    """基于日程的统一行为管理器，用日程驱动所有自动行为。"""

    def __init__(self, plugin):
        self.plugin = plugin
        self.schedule_provider: Optional[PlanningPluginProvider] = None
        self.is_running = False
        self.task = None

        # 冷却时间追踪（Unix 时间戳）
        self.last_post_time: float = 0
        self.last_browse_time: float = 0

        # 日记相关
        self.last_diary_date: Optional[datetime.date] = None

    async def start(self):
        """初始化日程提供者并启动主循环"""
        if self.is_running:
            return

        # 查找 autonomous_planning 数据库
        db_path = _find_planning_db()
        if not db_path:
            logger.warning("未找到 autonomous_planning 数据库，routine 模式无法启动")
            return

        self.schedule_provider = PlanningPluginProvider(db_path)
        self.is_running = True
        self.task = asyncio.create_task(self._routine_loop())
        logger.info("Routine 模式已启动（日程驱动）")

    async def stop(self):
        """停止主循环"""
        if not self.is_running:
            return
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Routine 模式已停止")

    # ---------- 主循环 ----------

    async def _routine_loop(self):
        check_interval = self.plugin.get_config("routine.check_interval_minutes", 20)

        while self.is_running:
            try:
                activity = await self.schedule_provider.get_current_activity()

                if not activity:
                    logger.debug("routine: 无当前活动，跳过")
                    await asyncio.sleep(check_interval * 60)
                    continue

                logger.info(f"routine: 当前活动 [{activity.activity_type.value}] {activity.description}")

                # sleeping 不做任何事
                if activity.activity_type == ActivityType.SLEEPING:
                    logger.debug("routine: sleeping，跳过")
                    await asyncio.sleep(check_interval * 60)
                    continue

                # 发说说
                if await self._llm_decide(activity, "post"):
                    try:
                        await self._post_feed(activity)
                    except Exception as e:
                        logger.error(f"routine: 发说说失败: {e}")
                        traceback.print_exc()

                # 刷空间
                if await self._llm_decide(activity, "browse"):
                    try:
                        await self._browse_feeds()
                    except Exception as e:
                        logger.error(f"routine: 刷空间失败: {e}")
                        traceback.print_exc()

                # 日记（保持原有逻辑）
                self._check_diary()

                await asyncio.sleep(check_interval * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"routine 主循环出错: {e}")
                traceback.print_exc()
                await asyncio.sleep(300)

    # ---------- LLM 决策 ----------

    async def _llm_decide(self, activity: ActivityInfo, action: str) -> bool:
        """让 LLM 严格决策是否执行动作

        Args:
            activity: 当前活动信息
            action: "post"（发说说）或 "browse"（刷空间）
        """
        # 先检查冷却时间（硬限制）
        if action == "post":
            cooldown = self.plugin.get_config("routine.post_cooldown_minutes", 120) * 60
            if time.time() - self.last_post_time < cooldown:
                return False
        elif action == "browse":
            cooldown = self.plugin.get_config("routine.browse_cooldown_minutes", 40) * 60
            if time.time() - self.last_browse_time < cooldown:
                return False

        # 构建决策 prompt
        bot_personality = config_api.get_global_config("personality.personality", "")
        current_time = datetime.datetime.now().strftime("%H:%M")

        action_desc = "发一条QQ空间说说" if action == "post" else "刷一下QQ空间看看好友动态"

        prompt = (
            f"你是'{bot_personality}'，现在是{current_time}，你正在{activity.description}。\n"
            f"请判断你现在是否会自然地{action_desc}。\n"
            f"要求非常严格：只有在当前活动和时间确实适合的情况下才回答'是'。\n"
            f"大部分情况下应该回答'否'——正在专注做事、睡觉、忙碌时不会刷手机。\n"
            f"只回答'是'或'否'，不要输出其他内容。"
        )

        models = llm_api.get_available_models()
        text_model = self.plugin.get_config("models.text_model", "replyer")
        model_config = models[text_model]
        if not model_config:
            logger.warning("routine: 未配置LLM模型，跳过决策")
            return False

        try:
            result = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="routine.decide",
                temperature=0.3,
                max_tokens=10,
            )

            answer = result[1].strip() if result[0] else ""
            decision = "是" in answer and "否" not in answer
            logger.debug(f"routine: LLM 决策 {action} -> '{answer}' -> {decision}")
            return decision
        except Exception as e:
            logger.error(f"routine: LLM 决策异常: {e}")
            return False

    # ---------- 发说说 ----------

    async def _post_feed(self, activity: ActivityInfo):
        """根据当前活动发送一条说说"""
        logger.info(f"routine: 准备发说说，活动: {activity.description}")

        models = llm_api.get_available_models()
        text_model = self.plugin.get_config("models.text_model", "replyer")
        model_config = models[text_model]
        if not model_config:
            logger.error("routine: 未配置LLM模型")
            return

        bot_personality = config_api.get_global_config("personality.personality", "一个机器人")
        bot_expression = config_api.get_global_config("personality.reply_style", "内容积极向上")

        try:
            await get_napcat_config_and_renew(self.plugin.get_config)
        except Exception as e:
            logger.error(f"routine: 更新cookies失败: {e}")
            return

        history_number = self.plugin.get_config("send.history_number", 5)
        qzone = create_qzone_api()
        if not qzone:
            logger.error("routine: 创建QzoneAPI失败")
            return

        # 用活动描述作为主题
        topic = activity.description

        prompt = await build_send_prompt(
            self.plugin.get_config, qzone, topic,
            bot_personality, bot_expression, history_number,
            current_activity=activity.description,
        )

        show_prompt = self.plugin.get_config("models.show_prompt", False)
        if show_prompt:
            logger.info(f"routine 发说说 prompt: {prompt}")

        result = await llm_api.generate_with_model(
            prompt=prompt,
            model_config=model_config,
            request_type="story.generate",
            temperature=0.3,
            max_tokens=4096,
        )

        if len(result) == 4:
            success, story, reasoning, model_name = result
        elif len(result) == 3:
            success, story, reasoning = result
        else:
            logger.error(f"routine: LLM返回值格式不正确: {result}")
            return

        if not success:
            logger.error("routine: 生成说说内容失败")
            return

        logger.info(f"routine: 生成说说内容: '{story}'")

        image_dir = str(Path(__file__).parent.resolve() / "images")
        enable_image = self.plugin.get_config("send.enable_image", False)
        image_mode = self.plugin.get_config("send.image_mode", "random").lower()
        ai_probability = self.plugin.get_config("send.ai_probability", 0.5)
        image_number = self.plugin.get_config("send.image_number", 1)

        success = await send_feed(story, image_dir, enable_image, image_mode, ai_probability, image_number)
        if success:
            self.last_post_time = time.time()
            logger.info(f"routine: 发说说成功: {story}")
        else:
            logger.error("routine: 发说说失败")

    # ---------- 刷空间 ----------

    async def _browse_feeds(self):
        """刷空间（复用 FeedMonitor 的核心逻辑）"""
        logger.info("routine: 准备刷空间")

        # 延迟导入，避免循环依赖
        from .scheduled_tasks import FeedMonitor, _load_processed_list, _load_processed_comments, \
            _save_processed_list, _save_processed_comments

        try:
            await get_napcat_config_and_renew(self.plugin.get_config)
        except Exception as e:
            logger.error(f"routine: 更新cookies失败: {e}")
            return

        # 创建临时 FeedMonitor 实例来复用 check_feeds 逻辑
        temp_monitor = FeedMonitor(self.plugin)
        processed_list = await _load_processed_list()
        processed_comments = await _load_processed_comments()

        try:
            await temp_monitor.check_feeds(processed_list, processed_comments)
            self.last_browse_time = time.time()
        finally:
            await _save_processed_list(processed_list)
            await _save_processed_comments(processed_comments)

        logger.info("routine: 刷空间完成")

    # ---------- 日记 ----------

    def _check_diary(self):
        """检查是否到达日记生成时间，到达则触发异步任务"""
        diary_enabled = self.plugin.get_config("diary.enabled", False)
        if not diary_enabled:
            return

        diary_time = self.plugin.get_config("diary.schedule_time", "23:30")
        current_time_str = datetime.datetime.now().strftime("%H:%M")
        if current_time_str != diary_time:
            return

        today = datetime.datetime.now().date()
        if self.last_diary_date == today:
            return

        self.last_diary_date = today
        logger.info("routine: 到达日记生成时间，开始生成日记")
        asyncio.create_task(self._generate_diary())

    async def _generate_diary(self):
        """生成并发布日记（复用 ScheduleSender 的逻辑）"""
        try:
            from .scheduled_tasks import ScheduleSender
            temp_scheduler = ScheduleSender(self.plugin)
            await temp_scheduler.generate_and_publish_diary()
        except Exception as e:
            logger.error(f"routine: 日记生成失败: {e}")
            traceback.print_exc()
