"""记忆管理模块 - 短期记忆(对话上下文) + 长期记忆(向量存储)"""
import json
from typing import Optional, Any
from datetime import datetime, timedelta
from collections import deque
import hashlib

# 向量存储（可选，使用简单的内存实现）
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False


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
            "metadata": metadata or {}
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
        
        # 获取最老的一半
        oldest = list(self.messages)[:len(self.messages) // 2]
        
        # 生成摘要
        summary = f"[早期对话摘要 ({len(oldest)}条消息)]\n"
        for msg in oldest:
            summary += f"- {msg['role']}: {msg['content'][:100]}...\n"
        
        # 保存摘要
        self.summaries.append({
            "content": summary,
            "timestamp": datetime.now().isoformat(),
            "count": len(oldest)
        })
        
        # 清理旧记忆
        for _ in range(len(oldest)):
            self.messages.popleft()
        
        return summary
    
    def clear(self) -> None:
        """清空记忆"""
        self.messages.clear()
        self.summaries.clear()
    
    def to_dict(self) -> dict:
        """序列化"""
        return {
            "messages": list(self.messages),
            "summaries": self.summaries
        }


class LongTermMemory:
    """
    长期记忆 - 基于向量存储的记忆系统
    
    设计原则:
    1. 使用向量相似度搜索
    2. 自动清理低频记忆
    3. 支持记忆增强检索
    """
    
    def __init__(self, persist_path: str = "./data/vector_store"):
        self.persist_path = persist_path
        self.collection_name = "code_review_memory"
        self.client = None
        self.collection = None
        
        if CHROMA_AVAILABLE:
            self._init_vector_store()
    
    def _init_vector_store(self) -> None:
        """初始化向量存储"""
        try:
            self.client = chromadb.Client(Settings(
                anonymized_telemetry=False,
                allow_reset=True
            ))
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "代码审查记忆库"}
            )
        except Exception as e:
            print(f"向量存储初始化失败: {e}")
            self.client = None
            self.collection = None
    
    def add(
        self,
        content: str,
        metadata: dict = None,
        task_id: str = None
    ) -> Optional[str]:
        """
        添加记忆
        
        Args:
            content: 记忆内容
            metadata: 元数据
            task_id: 关联的任务ID
        
        Returns:
            记忆ID
        """
        if not self.collection:
            return None
        
        memory_id = hashlib.md5(
            f"{content}_{datetime.now().isoformat()}".encode()
        ).hexdigest()
        
        vector = self._simple_vectorize(content)
        
        self.collection.add(
            ids=[memory_id],
            embeddings=[vector],
            documents=[content],
            metadatas=[{
                **(metadata or {}),
                "task_id": task_id,
                "created_at": datetime.now().isoformat()
            }]
        )
        
        return memory_id
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: dict = None
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
        if not self.collection:
            return []
        
        query_vector = self._simple_vectorize(query)
        
        try:
            results = self.collection.query(
                query_embeddings=[query_vector],
                n_results=n_results,
                where=filter_metadata,
                include=["documents", "metadatas", "distances"]
            )
            
            memories = []
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    memories.append({
                        "content": doc,
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                        "distance": results["distances"][0][i] if results.get("distances") else 0
                    })
            
            return memories
        except Exception as e:
            print(f"记忆搜索失败: {e}")
            return []
    
    def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        if not self.collection:
            return False
        
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception:
            return False
    
    def clear_old(self, days: int = 30) -> int:
        """清理旧记忆"""
        if not self.collection:
            return 0
        
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        try:
            # 获取要删除的ID
            all_data = self.collection.get()
            to_delete = []
            
            for i, meta in enumerate(all_data.get("metadatas", [])):
                created_at = meta.get("created_at", "")
                if created_at and created_at < cutoff:
                    to_delete.append(all_data["ids"][i])
            
            # 删除
            if to_delete:
                self.collection.delete(ids=to_delete)
            
            return len(to_delete)
        except Exception:
            return 0
    
    def _simple_vectorize(self, text: str) -> list[float]:
        """简化的向量化（实际应用中应使用embedding模型）"""
        # 简单的词袋向量
        words = text.lower().split()
        unique_words = set(words)
        
        # 生成固定长度的向量
        vector = [0.0] * 1000
        for i, word in enumerate(unique_words):
            if i >= 1000:
                break
            vector[hash(word) % 1000] += 1
        
        # 归一化
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        
        return vector


class MemoryManager:
    """
    记忆管理器 - 整合短期和长期记忆
    
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
        persist: bool = True
    ) -> None:
        """添加交互到记忆"""
        # 添加到短期记忆
        self.short_term.add(role, content, metadata)
        
        # 可选：同时添加到长期记忆
        if persist:
            self.long_term.add(content, metadata)
    
    def get_context(self, n: int = None) -> list[dict]:
        """获取上下文（短期记忆优先）"""
        return self.short_term.get_recent(n)
    
    def search_memory(self, query: str, n_results: int = 5) -> list[dict]:
        """搜索长期记忆"""
        return self.long_term.search(query, n_results)
    
    def get_relevant_context(self, query: str, n: int = 5) -> str:
        """
        获取相关上下文（用于RAG）
        
        策略:
        1. 先查长期记忆获取相关内容
        2. 再补充短期记忆
        """
        context_parts = []
        
        # 搜索长期记忆
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


# 全局记忆管理器
_memory_manager: MemoryManager = None


def get_memory_manager() -> MemoryManager:
    """获取记忆管理器单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
