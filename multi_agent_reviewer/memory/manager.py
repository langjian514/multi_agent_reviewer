"""记忆管理模块 - 短期记忆(滑动窗口) + 长期记忆(Milvus向量存储)"""
import json
from typing import Optional, Any
from datetime import datetime, timedelta
from collections import deque
import hashlib

# Milvus 向量数据库
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility,
)

from config.settings import settings


class ShortTermMemory:
    """
    短期记忆 - 基于滑动窗口的对话上下文管理

    设计原则:
    1. 使用滑动窗口保持最近的N条消息
    2. 超过窗口自动摘要
    3. 定期清理过期记忆
    """

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self.messages = deque(maxlen=window_size)
        self.summaries = []

    def add(self, role: str, content: str, metadata: dict = None) -> None:
        """添加记忆"""
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        self.messages.append(entry)

    def get_recent(self, n: int = None) -> list[dict]:
        """获取最近的N条记忆"""
        if n is None:
            return list(self.messages)
        return list(self.messages)[-n:]

    def get_all(self) -> list[dict]:
        """获取所有记忆"""
        return list(self.messages)

    def summarize_oldest(self) -> str:
        """对最老的记忆进行摘要"""
        if len(self.messages) < self.window_size // 2:
            return ""

        oldest = list(self.messages)[: len(self.messages) // 2]

        summary = f"[早期对话摘要 ({len(oldest)}条消息)]\n"
        for msg in oldest:
            summary += f"- {msg['role']}: {msg['content'][:100]}...\n"

        self.summaries.append({
            "content": summary,
            "timestamp": datetime.now().isoformat(),
            "count": len(oldest),
        })

        for _ in range(len(oldest)):
            self.messages.popleft()

        return summary

    def clear(self) -> None:
        """清空记忆"""
        self.messages.clear()
        self.summaries.clear()

    def to_dict(self) -> dict:
        """序列化"""
        return {"messages": list(self.messages), "summaries": self.summaries}


class LongTermMemory:
    """
    长期记忆 - 基于 Milvus 向量存储的记忆系统

    设计原则:
    1. 使用向量相似度搜索 (IVF_FLAT 索引)
    2. 自动清理低频记忆
    3. 支持记忆增强检索
    """

    def __init__(self):
        self.collection_name = settings.milvus_collection
        self.dimension = settings.milvus_dimension
        self._connected = False
        self._collection: Collection | None = None

    def _connect(self) -> None:
        """连接 Milvus"""
        if self._connected:
            return
        try:
            connections.connect(
                alias="default",
                host=settings.milvus_host,
                port=settings.milvus_port,
            )
            self._ensure_collection()
            self._connected = True
        except Exception as e:
            print(f"[Milvus] 连接失败: {e}")

    def _ensure_collection(self) -> None:
        """确保集合存在"""
        if utility.has_collection(self.collection_name):
            self._collection = Collection(self.collection_name)
            return

        # 创建集合
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="memory_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
            FieldSchema(name="task_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="language", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=32),
        ]
        schema = CollectionSchema(fields, description="代码审查记忆库")
        self._collection = Collection(self.collection_name, schema)

        # 创建索引
        index_params = {
            "metric_type": "IP",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128},
        }
        self._collection.create_index(
            field_name="embedding", index_params=index_params
        )
        self._collection.load()

    def add(
        self,
        content: str,
        metadata: dict = None,
        task_id: str = None,
    ) -> Optional[str]:
        """
        添加记忆到 Milvus

        Args:
            content: 记忆内容
            metadata: 元数据
            task_id: 关联的任务ID

        Returns:
            记忆ID (MD5 hash)
        """
        self._connect()
        if not self._collection:
            return None

        memory_id = hashlib.md5(
            f"{content}_{datetime.now().isoformat()}".encode()
        ).hexdigest()

        metadata = metadata or {}
        vector = self._embed(content)

        try:
            self._collection.insert([
                [memory_id],
                [content],
                [vector],
                [task_id or ""],
                [metadata.get("language", "")],
                [metadata.get("category", "general")],
                [datetime.now().isoformat()],
            ])
            return memory_id
        except Exception as e:
            print(f"[Milvus] 插入失败: {e}")
            return None

    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: dict = None,
    ) -> list[dict]:
        """
        搜索记忆

        Args:
            query: 查询内容
            n_results: 返回数量
            filter_metadata: 元数据过滤条件

        Returns:
            相关记忆列表
        """
        self._connect()
        if not self._collection:
            return []

        query_vector = self._embed(query)

        try:
            self._collection.load()

            # 构造过滤表达式
            expr = None
            if filter_metadata:
                conditions = []
                if "language" in filter_metadata:
                    conditions.append(
                        f'language == "{filter_metadata["language"]}"'
                    )
                if "category" in filter_metadata:
                    conditions.append(
                        f'category == "{filter_metadata["category"]}"'
                    )
                if conditions:
                    expr = " and ".join(conditions)

            results = self._collection.search(
                data=[query_vector],
                anns_field="embedding",
                param={"metric_type": "IP", "params": {"nprobe": 10}},
                limit=n_results,
                expr=expr,
                output_fields=["memory_id", "content", "task_id", "language", "category", "created_at"],
            )

            memories = []
            for hits in results:
                for hit in hits:
                    memories.append({
                        "id": hit.entity.get("memory_id"),
                        "content": hit.entity.get("content"),
                        "task_id": hit.entity.get("task_id"),
                        "language": hit.entity.get("language"),
                        "category": hit.entity.get("category"),
                        "created_at": hit.entity.get("created_at"),
                        "score": hit.score,
                    })

            return memories
        except Exception as e:
            print(f"[Milvus] 搜索失败: {e}")
            return []

    def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        self._connect()
        if not self._collection:
            return False
        try:
            self._collection.delete(f'memory_id == "{memory_id}"')
            return True
        except Exception:
            return False

    def clear_old(self, days: int = 30) -> int:
        """清理旧记忆"""
        self._connect()
        if not self._collection:
            return 0

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            self._collection.delete(f'created_at < "{cutoff}"')
            return 1
        except Exception:
            return 0

    def close(self) -> None:
        """断开 Milvus 连接"""
        if self._connected:
            connections.disconnect("default")
            self._connected = False
            self._collection = None

    @staticmethod
    def _embed(text: str) -> list[float]:
        """
        文本向量化

        生产环境建议用 Qwen-Embedding 模型替代这个简易实现。
        此处使用带哈希特征的固定维度向量作为 fallback。
        """
        words = text.lower().split()
        unique_words = list(set(words))

        dimension = settings.milvus_dimension
        vector = [0.0] * dimension

        for i, word in enumerate(unique_words):
            if i >= dimension:
                break
            idx = hash(word) % dimension
            vector[idx] += 1.0

        # 归一化
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector


class MemoryManager:
    """
    记忆管理器 - 整合短期记忆和 Milvus 长期记忆

    设计原则:
    1. 短期记忆优先
    2. 长期记忆用于检索增强
    3. 自动管理记忆生命周期
    """

    def __init__(self, window_size: int = 10):
        self.short_term = ShortTermMemory(window_size=window_size)
        self.long_term = LongTermMemory()

    def add_interaction(
        self,
        role: str,
        content: str,
        metadata: dict = None,
        persist: bool = True,
    ) -> None:
        """添加交互到记忆"""
        self.short_term.add(role, content, metadata)
        if persist:
            self.long_term.add(content, metadata)

    def get_context(self, n: int = None) -> list[dict]:
        """获取上下文（短期记忆优先）"""
        return self.short_term.get_recent(n)

    def search_memory(self, query: str, n_results: int = 5) -> list[dict]:
        """搜索长期记忆 (Milvus)"""
        return self.long_term.search(query, n_results)

    def get_relevant_context(self, query: str, n: int = 5) -> str:
        """
        获取相关上下文（用于 RAG）

        策略:
        1. 先查 Milvus 获取相关内容
        2. 再补充短期记忆
        """
        context_parts = []

        # 搜索 Milvus 长期记忆
        memories = self.long_term.search(query, n_results=n)
        if memories:
            context_parts.append("[相关历史记忆]")
            for mem in memories:
                context_parts.append(f"- {mem['content'][:200]}")

        # 补充短期记忆
        recent = self.short_term.get_recent(n)
        if recent:
            context_parts.append("\n[近期对话]")
            for msg in recent:
                context_parts.append(f"- {msg['role']}: {msg['content'][:100]}")

        return "\n".join(context_parts) if context_parts else ""

    def clear(self) -> None:
        """清空所有记忆"""
        self.short_term.clear()

    def cleanup_old(self, days: int = 30) -> int:
        """清理旧记忆"""
        return self.long_term.clear_old(days)

    def close(self) -> None:
        """关闭管理器"""
        self.long_term.close()


# 全局记忆管理器
_memory_manager: MemoryManager = None


def get_memory_manager() -> MemoryManager:
    """获取记忆管理器单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(window_size=settings.memory_window_size)
    return _memory_manager
