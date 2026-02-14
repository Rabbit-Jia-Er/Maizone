import base64
import datetime
import time
import os
import random
import traceback
import asyncio
from io import BytesIO
from PIL import Image
from pathlib import Path
from typing import List, Dict

import httpx

from src.common.logger import get_logger
from src.plugin_system.apis import llm_api, config_api, emoji_api, message_api, chat_api
from src.plugin_system.core import component_registry
from .api import create_qzone_api

logger = get_logger('Maizone.组件')


async def generate_image_via_pic_plugin(image_prompt: str, image_dir: str, pic_plugin_model: str = "model1") -> bool:
    """
    通过麦麦绘卷(Mai's Art Journal)的 generate_image_standalone 生成图片

    Args:
        image_prompt: 图片描述提示词
        image_dir: 图片保存目录
        pic_plugin_model: 麦麦绘卷中的模型名称（如 model1, model2）

    Returns:
        bool: 是否成功生成并保存图片
    """
    try:
        from plugins.mais_art_journal.core.api_clients import generate_image_standalone

        # 读取麦麦绘卷的配置来获取对应模型配置
        pic_config = component_registry.get_plugin_config('mais_art_journal')
        if not pic_config:
            logger.warning("未找到麦麦绘卷配置，无法生图")
            return False

        # 构建 model_config
        model_prefix = f"models.{pic_plugin_model}"

        model_config = {}
        for key in ["base_url", "api_key", "format", "model", "default_size", "seed",
                     "guidance_scale", "num_inference_steps", "watermark",
                     "custom_prompt_add", "negative_prompt_add", "artist",
                     "support_img2img"]:
            val = config_api.get_plugin_config(pic_config, f"{model_prefix}.{key}", None)
            if val is not None:
                model_config[key] = val

        if not model_config.get("base_url") or not model_config.get("model"):
            logger.warning(f"麦麦绘卷模型 {pic_plugin_model} 配置不完整")
            return False

        # 注入 Bot 外观（selfie 配置：prompt_prefix / reference_image）
        bot_appearance = ""
        reference_image_path = ""
        try:
            bot_appearance = config_api.get_plugin_config(pic_config, "selfie.prompt_prefix", "")
            reference_image_path = config_api.get_plugin_config(pic_config, "selfie.reference_image_path", "").strip()
        except Exception:
            pass
        if bot_appearance:
            image_prompt = f"{bot_appearance}, {image_prompt}"

        # 加载参考图片（图生图模式）
        reference_image_b64 = None
        strength = None
        if reference_image_path:
            try:
                if not os.path.isabs(reference_image_path):
                    # 相对路径基于 mais_art_journal 插件目录
                    art_plugin_dir = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "mais_art_journal",
                    )
                    reference_image_path = os.path.join(art_plugin_dir, reference_image_path)
                if os.path.exists(reference_image_path):
                    with open(reference_image_path, "rb") as f:
                        reference_image_b64 = base64.b64encode(f.read()).decode("utf-8")
                    if model_config.get("support_img2img", True):
                        strength = 0.6
                        logger.info(f"使用自拍参考图片进行图生图: {reference_image_path}")
                    else:
                        reference_image_b64 = None
                        logger.debug("当前模型不支持图生图，回退文生图")
            except Exception as e:
                logger.debug(f"加载自拍参考图片失败: {e}")

        size = model_config.get("default_size", "1024x1024")

        success, image_data = await generate_image_standalone(
            prompt=image_prompt,
            model_config=model_config,
            size=size,
            negative_prompt=None,
            strength=strength,
            input_image_base64=reference_image_b64,
            max_retries=2,
        )

        if not success or not image_data:
            logger.warning(f"pic_plugin 生图失败: {image_data}")
            return False

        # 保存图片
        Path(image_dir).mkdir(parents=True, exist_ok=True)
        save_path = Path(image_dir) / "pic_plugin_0.png"

        if image_data.startswith("http"):
            # URL 类型，下载图片
            async with httpx.AsyncClient() as client:
                img_response = await client.get(image_data, timeout=60.0)
                img_response.raise_for_status()
                image = Image.open(BytesIO(img_response.content))
                image.save(save_path)
        else:
            # Base64 类型
            img_bytes = base64.b64decode(image_data)
            image = Image.open(BytesIO(img_bytes))
            image.save(save_path)

        logger.info(f"pic_plugin 生成图片已保存至: {save_path}")
        return True

    except ImportError:
        logger.warning("麦麦绘卷未安装，无法生图")
        return False
    except Exception as e:
        logger.error(f"pic_plugin 生图异常: {e}")
        return False


def format_feed_list(feed_list: List[Dict]) -> str:
    """
    格式化说说列表为分层清晰的字符串以便显示
    Args:
        feed_list: 说说列表

    Returns:
        str: 格式化后的字符串
    """
    if not feed_list:
        return "feed_list 为空"

    # 检查是否是错误情况
    if len(feed_list) == 1 and "error" in feed_list[0]:
        error_msg = feed_list[0].get("error", "未知错误")
        return f"{error_msg}"

    result = []
    result.append("=" * 80)
    result.append("FEED LIST")
    result.append("=" * 80)

    for i, feed in enumerate(feed_list, 1):
        result.append(f"\nFeed #{i}")
        result.append("-" * 40)

        # 基本信息
        result.append(f"target_qq: {feed.get('target_qq', 'N/A')}")
        result.append(f"tid: {feed.get('tid', 'N/A')}")
        result.append(f"content: {feed.get('content', 'N/A')}")

        # 图片信息
        images = feed.get('images', [])
        if images:
            result.append(f"images: {len(images)}")
            for j, img in enumerate(images, 1):
                result.append(f"  image_{j}: {img}")
        else:
            result.append("images: []")

        # 视频信息
        videos = feed.get('videos', [])
        if videos:
            result.append(f"videos: {len(videos)}")
            for j, video in enumerate(videos, 1):
                result.append(f"  video_{j}: {video}")
        else:
            result.append("videos: []")

        # 转发内容
        rt_con = feed.get('rt_con', '')
        result.append(f"rt_con: {rt_con if rt_con else 'N/A'}")

        # 评论信息
        comments = feed.get('comments', [])
        if comments:
            result.append(f"comments: {len(comments)}")
            for j, comment in enumerate(comments, 1):
                result.append(f"  comment_{j}:")
                result.append(f"    qq_account: {comment.get('qq_account', 'N/A')}")
                result.append(f"    nickname: {comment.get('nickname', 'N/A')}")
                result.append(f"    comment_tid: {comment.get('comment_tid', 'N/A')}")
                result.append(f"    content: {comment.get('content', 'N/A')}")
                parent_tid = comment.get('parent_tid')
                result.append(f"    parent_tid: {parent_tid if parent_tid else 'None'}")
                if j < len(comments):  # 不在最后一个评论后加空行
                    result.append("")
        else:
            result.append("comments: []")

    result.append("=" * 80)
    result.append(f"总数: {len(feed_list)}")

    return "\n".join(result)


async def send_feed(message: str,
                    image_directory: str = "",
                    enable_image: bool = False,
                    image_mode: str = "random",
                    ai_probability: float = 0.5,
                    image_number: int = 1,
                    ) -> bool:
    """
    根据说说及配置生成图片，发送说说及图片目录下的所有未处理图片。
    图片生成通过麦麦绘卷(Mai's Art Journal)实现。

    Args:
        message (str): 要发送的说说内容。为"custom"时内部改写为个人私聊最新内容
        image_directory (str): 图片存储的目录路径。
        enable_image (bool): 是否启用图片功能。
        image_mode (str): 图片模式，可选值为 "only_ai", "only_emoji", "random"。
        ai_probability (float): 在随机模式下使用AI生成图片的概率，范围为0到1。
        image_number (int): 要生成的图片数量，范围为1到4。

    Returns:
        bool: 如果发送成功返回True，否则返回False。
    """
    qzone = create_qzone_api()
    if not qzone:
        logger.error("创建QzoneAPI失败，cookie可能不存在")
        return False
    plugin_config = component_registry.get_plugin_config('MaizonePlugin')
    images = []  # 图片列表
    done_paths = []  # 已处理的图片路径
    clear_image = config_api.get_plugin_config(plugin_config, "models.clear_image", True)  # 是否清理图片

    if message == "custom":
        # message为"custom"时重写message
        uin = config_api.get_plugin_config(plugin_config, "send.custom_qqaccount", "")
        if not uin:  # 未配置uin
            logger.error("未配置custom模式自定义QQ账号，请检查配置文件")
            return False
        stream_id = chat_api.get_stream_by_user_id(uin, "qq").stream_id
        message_list = message_api.get_messages_before_time_in_chat(
            chat_id=stream_id,
            timestamp=time.time(),
            limit=20,
            filter_mai=False
        )
        if config_api.get_plugin_config(plugin_config, "send.custom_only_mai", True):
            # 只使用bot说的内容
            message_list = [msg for msg in message_list if message_api.is_bot_self(msg.user_info.platform, msg.user_info.user_id)]
        else: # 只使用私聊对象说的内容
            message_list = [msg for msg in message_list if not message_api.is_bot_self(msg.user_info.platform, msg.user_info.user_id)]
        if not message_list:
            logger.error("未获取到任何私聊消息，无法发送自定义说说")
            return False
        # 倒序获取最新消息，跳过命令消息
        for msg in reversed(message_list):
            content = msg.processed_plain_text
            if content and not content.startswith('/'):
                message = content
                break
        if not message or message == "custom":
            logger.error("私聊消息内容为空，无法发送")
            return False
        logger.info(f"获取到最新私聊消息内容: {message}")

    if not enable_image:
        # 如果未启用图片功能，直接发送纯文本
        try:
            tid = await qzone.publish_emotion(message, [])
            logger.info(f"成功发送说说，tid: {tid}")
            return True
        except Exception as e:
            logger.error("发送说说失败")
            logger.error(traceback.format_exc())
            return False
    # 验证配置有效性
    if image_mode not in ["only_ai", "only_emoji", "random"]:
        logger.error(f"无效的图片模式: {image_mode}，已默认更改为 random")
        image_mode = "random"
    ai_probability = max(0.0, min(1.0, ai_probability))  # 限制在0-1之间
    image_number = max(1, min(4, image_number))  # 限制在1-4之间

    # 决定图片来源
    if image_mode == "only_ai":
        use_ai = True
    elif image_mode == "only_emoji":
        use_ai = False
    else:  # random模式
        use_ai = random.random() < ai_probability

    # 获取图片
    if use_ai:
        # 通过麦麦绘卷生成图片
        pic_plugin_model = config_api.get_plugin_config(plugin_config, "send.pic_plugin_model", "")
        if not pic_plugin_model:
            logger.warning("未配置 send.pic_plugin_model，无法生成AI图片，将发送纯文本说说")
        else:
            # 优先尝试麦麦绘卷的 PromptOptimizer 生成英文提示词
            image_prompt = None
            try:
                from plugins.mais_art_journal.core.utils import PromptOptimizer
                optimizer = PromptOptimizer(log_prefix="[Maizone.send_feed]")
                success, image_prompt = await optimizer.optimize(message)
                if not success:
                    image_prompt = None
            except ImportError:
                pass

            # PromptOptimizer 不可用时，走 Maizone 自身 LLM 方式
            if not image_prompt:
                models = llm_api.get_available_models()
                prompt_model = config_api.get_plugin_config(plugin_config, "models.text_model", "replyer")
                model_config = models[prompt_model]
                personality = config_api.get_global_config("personality.personality", "一只猫娘")
                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                prompt_pre = config_api.get_plugin_config(plugin_config, "models.image_prompt", "")
                data = {
                    "current_time": current_time,
                    "personality": personality,
                    "message": message
                }
                prompt = prompt_pre.format(**data)
                success, image_prompt, reasoning, model_name = await llm_api.generate_with_model(
                    prompt=prompt,
                    model_config=model_config,
                    request_type="story.generate",
                    temperature=0.3,
                    max_tokens=4096
                )
                if not success:
                    logger.warning("生成图片提示词失败")
                    image_prompt = None

            if image_prompt:
                logger.info(f'使用 pic_plugin 生成配图: {image_prompt}')
                ai_success = await generate_image_via_pic_plugin(
                    image_prompt=image_prompt,
                    image_dir=image_directory,
                    pic_plugin_model=pic_plugin_model
                )
                if ai_success:
                    # 处理生成的图片文件
                    all_files = [f for f in os.listdir(image_directory)
                                 if os.path.isfile(os.path.join(image_directory, f))]
                    unprocessed_files = [f for f in all_files if not f.startswith("done_")]
                    for image_file in sorted(unprocessed_files):
                        full_path = os.path.join(image_directory, image_file)
                        with open(full_path, "rb") as img:
                            images.append(img.read())
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        new_filename = f"done_{timestamp}_{image_file}"
                        new_path = os.path.join(image_directory, new_filename)
                        os.rename(full_path, new_path)
                        done_paths.append(new_path)
                else:
                    logger.warning("pic_plugin 生图失败")
            else:
                logger.warning("生成图片提示词失败，将发送纯文本说说")
    else:
        # 使用表情包
        for _ in range(image_number):
            image = await emoji_api.get_by_description(message)
            if image:
                image_base64, description, scene = image
                image_data = base64.b64decode(image_base64)
                images.append(image_data)

    try:
        tid = await qzone.publish_emotion(message, images)
        logger.info(f"成功发送说说，tid: {tid}")
        if clear_image and done_paths:
            for path in done_paths:
                os.remove(path)
                logger.info(f"已删除图片: {path}")
        return True
    except Exception as e:
        logger.error("发送说说失败")
        logger.error(traceback.format_exc())
        return False


async def read_feed(target_qq: str, num: int) -> list[dict]:
    """
    通过调用QZone API的`get_list`方法阅读指定QQ号的说说，返回说说列表。
    """
    qzone = create_qzone_api()
    if not qzone:
        logger.error("创建QzoneAPI失败，cookie可能不存在")
        return []

    try:
        feeds_list = await qzone.get_list(target_qq, num)
        logger.debug(f"获取到的说说列表: {format_feed_list(feeds_list)}")
        return feeds_list
    except Exception as e:
        logger.error("获取list失败")
        logger.error(traceback.format_exc())
        return []


async def monitor_read_feed(self_readnum) -> list[dict]:
    """
    通过调用QZone API的`monitor_get_list`方法定时阅读说说，返回说说列表。
    """
    qzone = create_qzone_api()
    if not qzone:
        logger.error("创建QzoneAPI失败，cookie可能不存在")
        return []

    try:
        feeds_list = await qzone.monitor_get_list(self_readnum)
        logger.debug(f"获取到的说说列表: {format_feed_list(feeds_list)}")
        return feeds_list
    except Exception as e:
        logger.error("获取list失败")
        logger.error(traceback.format_exc())
        return []


async def like_feed(target_qq: str, fid: str) -> bool:
    """调用QZone API的`like`方法点赞指定说说。"""
    qzone = create_qzone_api()
    if not qzone:
        logger.error("创建QzoneAPI失败，cookie可能不存在")
        return False

    try:
        success = await qzone.like(fid, target_qq)
        if not success:
            logger.error("点赞失败")
            return False
        return True
    except Exception as e:
        logger.error(f"点赞异常: {e}")
        return False


async def comment_feed(target_qq: str, fid: str, content: str) -> bool:
    """通过调用QZone API的`comment`方法评论指定说说。"""
    qzone = create_qzone_api()
    if not qzone:
        logger.error("创建QzoneAPI失败，cookie可能不存在")
        return False

    try:
        success = await qzone.comment(fid, target_qq, content)
        if not success:
            logger.error("评论失败")
            return False
        return True
    except Exception as e:
        logger.error(f"评论异常: {e}")
        return False


async def reply_feed(fid: str, target_qq: str, target_nickname: str, content: str, comment_tid: str, host_uin=None) -> bool:
    """通过调用QZone API的`reply`方法回复指定评论。"""
    qzone = create_qzone_api()
    if not qzone:
        logger.error("创建QzoneAPI失败，cookie可能不存在")
        return False

    try:
        success = await qzone.reply(fid, target_qq, target_nickname, content, comment_tid, host_uin=host_uin)
        if not success:
            logger.error("回复失败")
            return False
        return True
    except Exception as e:
        logger.error(f"回复异常: {e}")
        return False
