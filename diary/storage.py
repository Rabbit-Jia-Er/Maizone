"""
日记存储模块

提供 JSON 文件格式的日记数据持久化：按日期组织、多版本管理、统计分析。
QQ空间发布功能已由 Maizone 的 qzone_api 统一处理，此处不再包含。
"""

import datetime
import time
import json
import os
from typing import List, Dict, Any, Optional

from src.plugin_system.apis import get_logger

from .utils import format_date_str

logger = get_logger("Maizone.diary.storage")


class DiaryStorage:
    """JSON文件存储的日记管理类"""

    def __init__(self):
        base_dir = os.path.dirname(__file__)
        self.data_dir = os.path.join(base_dir, "..", "data", "diaries")
        self.index_file = os.path.join(base_dir, "..", "data", "diary_index.json")

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.index_file), exist_ok=True)

    async def save_diary(self, diary_data: Dict[str, Any], expected_hour: int = None, expected_minute: int = None) -> bool:
        """保存日记到JSON文件"""
        try:
            date = diary_data["date"]
            generation_time = diary_data.get("generation_time", time.time())

            if expected_hour is not None and expected_minute is not None:
                filename = f"{format_date_str(date)}_{expected_hour:02d}{expected_minute:02d}00.json"
            else:
                timestamp = datetime.datetime.fromtimestamp(generation_time)
                filename = f"{format_date_str(date)}_{timestamp.strftime('%H%M%S')}.json"

            file_path = os.path.join(self.data_dir, filename)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(diary_data, f, ensure_ascii=False, indent=2)

            await self._update_index(diary_data)
            return True
        except Exception as e:
            logger.error(f"保存日记失败: {e}")
            return False

    async def get_diary(self, date: str) -> Optional[Dict[str, Any]]:
        """获取指定日期的最新日记"""
        try:
            if not os.path.exists(self.data_dir):
                return None

            date_files = []
            for filename in os.listdir(self.data_dir):
                if filename.startswith(f"{format_date_str(date)}_") and filename.endswith('.json'):
                    file_path = os.path.join(self.data_dir, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        diary_data = json.load(f)
                        date_files.append(diary_data)

            if date_files:
                return max(date_files, key=lambda x: x.get('generation_time', 0))
            return None
        except Exception as e:
            logger.error(f"读取日记失败: {e}")
            return None

    async def get_diaries_by_date(self, date: str) -> List[Dict[str, Any]]:
        """获取指定日期的所有日记"""
        try:
            if not os.path.exists(self.data_dir):
                return []

            date_files = []
            for filename in os.listdir(self.data_dir):
                if filename.startswith(f"{format_date_str(date)}_") and filename.endswith('.json'):
                    file_path = os.path.join(self.data_dir, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        diary_data = json.load(f)
                        date_files.append(diary_data)

            date_files.sort(key=lambda x: x.get('generation_time', 0))
            return date_files
        except Exception as e:
            logger.error(f"读取日期日记失败: {e}")
            return []

    async def list_diaries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """列出最近的日记"""
        try:
            diary_files = []

            if not os.path.exists(self.data_dir):
                return []

            for filename in os.listdir(self.data_dir):
                if filename.endswith('.json'):
                    file_path = os.path.join(self.data_dir, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        diary_data = json.load(f)
                        diary_files.append(diary_data)

            diary_files.sort(key=lambda x: x.get('generation_time', 0), reverse=True)
            return diary_files[:limit] if limit > 0 else diary_files
        except Exception as e:
            logger.error(f"列出日记失败: {e}")
            return []

    async def get_stats(self) -> Dict[str, Any]:
        """获取日记统计信息"""
        try:
            diaries = await self.list_diaries(limit=0)
            if not diaries:
                return {"total_count": 0, "total_words": 0, "avg_words": 0, "latest_date": "无"}

            total_count = len(diaries)
            total_words = sum(diary.get("word_count", 0) for diary in diaries)
            avg_words = total_words // total_count if total_count > 0 else 0
            latest_date = max(diaries, key=lambda x: x.get('generation_time', 0)).get('date', '无')

            return {
                "total_count": total_count,
                "total_words": total_words,
                "avg_words": avg_words,
                "latest_date": latest_date
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {"total_count": 0, "total_words": 0, "avg_words": 0, "latest_date": "无"}

    async def _update_index(self, diary_data: Dict[str, Any]):
        """更新索引文件"""
        try:
            index_data = {"last_update": time.time(), "total_diaries": 0, "success_count": 0, "failed_count": 0}
            if os.path.exists(self.index_file):
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)

            index_data["last_update"] = time.time()

            if os.path.exists(self.data_dir):
                all_files = [f for f in os.listdir(self.data_dir) if f.endswith('.json')]
                success_count = 0
                failed_count = 0

                for filename in all_files:
                    file_path = os.path.join(self.data_dir, filename)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            if data.get("is_published_qzone", False):
                                success_count += 1
                            else:
                                failed_count += 1
                    except Exception:
                        failed_count += 1

                index_data["success_count"] = success_count
                index_data["failed_count"] = failed_count
                index_data["total_diaries"] = len(all_files)

            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"更新索引失败: {e}")
