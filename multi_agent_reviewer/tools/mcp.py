"""工具调用模块 - MCP协议 + Function Calling"""
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
import inspect


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: dict  # JSON Schema格式
    handler: Callable = field(repr=False)
    timeout: float = 30.0
    retry_count: int = 2


@dataclass
class ToolCall:
    """工具调用记录"""
    tool_name: str
    arguments: dict
    start_time: datetime
    end_time: datetime = field(default=None)
    result: Any = field(default=None)
    error: str = field(default=None)
    success: bool = field(default=False)
    

class BaseTool(ABC):
    """工具基类"""
    
    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """返回工具定义"""
        pass
    
    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行工具"""
        pass


class ToolRegistry:
    """
    工具注册表
    
    设计原则:
    1. 中心化工具管理
    2. 统一的调用接口
    3. 自动发现可用工具
    """
    
    _tools: dict[str, ToolDefinition] = {}
    _instances: dict[str, BaseTool] = {}
    
    @classmethod
    def register(cls, tool: BaseTool) -> None:
        """注册工具"""
        definition = tool.definition
        cls._tools[definition.name] = definition
        cls._instances[definition.name] = tool
    
    @classmethod
    def get(cls, name: str) -> ToolDefinition | None:
        """获取工具定义"""
        return cls._tools.get(name)
    
    @classmethod
    def get_handler(cls, name: str) -> Callable | None:
        """获取工具处理器"""
        tool = cls._instances.get(name)
        return tool.execute if tool else None
    
    @classmethod
    def get_all_definitions(cls) -> list[dict]:
        """获取所有工具定义（用于Function Calling）"""
        return [
            {
                "name": d.name,
                "description": d.description,
                "parameters": d.parameters
            }
            for d in cls._tools.values()
        ]
    
    @classmethod
    async def call(
        cls,
        name: str,
        arguments: dict,
        timeout: float = 30.0,
        retry_count: int = 2
    ) -> ToolCall:
        """
        调用工具
        
        Args:
            name: 工具名称
            arguments: 工具参数
            timeout: 超时时间
            retry_count: 重试次数
        
        Returns:
            ToolCall记录
        """
        call_record = ToolCall(
            tool_name=name,
            arguments=arguments,
            start_time=datetime.now()
        )
        
        handler = cls.get_handler(name)
        if not handler:
            call_record.error = f"Tool not found: {name}"
            return call_record
        
        # 重试逻辑
        last_error = None
        for attempt in range(retry_count + 1):
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await asyncio.wait_for(
                        handler(**arguments),
                        timeout=timeout
                    )
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(handler, **arguments),
                        timeout=timeout
                    )
                
                call_record.result = result
                call_record.success = True
                break
            
            except asyncio.TimeoutError:
                last_error = f"Timeout after {timeout}s"
                if attempt == retry_count:
                    call_record.error = last_error
            
            except Exception as e:
                last_error = str(e)
                if attempt == retry_count:
                    call_record.error = last_error
        
        call_record.end_time = datetime.now()
        return call_record
    
    @classmethod
    def list_tools(cls) -> list[str]:
        """列出所有已注册的工具"""
        return list(cls._tools.keys())


class MCPServer:
    """
    MCP协议服务
    
    MCP (Model Context Protocol) 是一个标准化的工具发现和调用协议
    """
    
    def __init__(self, name: str):
        self.name = name
        self.tools: list[ToolDefinition] = []
        self._connected = False
    
    def add_tool(self, tool: ToolDefinition) -> None:
        """添加工具到服务器"""
        self.tools.append(tool)
        ToolRegistry._tools[tool.name] = tool
    
    def remove_tool(self, name: str) -> bool:
        """移除工具"""
        if name in ToolRegistry._tools:
            del ToolRegistry._tools[name]
            self.tools = [t for t in self.tools if t.name != name]
            return True
        return False
    
    def discover_tools(self) -> list[dict]:
        """发现可用工具"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "server": self.name
            }
            for t in self.tools
        ]
    
    async def call_tool(
        self,
        name: str,
        arguments: dict,
        timeout: float = 30.0
    ) -> ToolCall:
        """通过MCP协议调用工具"""
        return await ToolRegistry.call(name, arguments, timeout)
    
    def connect(self) -> bool:
        """连接服务器"""
        self._connected = True
        return True
    
    def disconnect(self) -> None:
        """断开连接"""
        self._connected = False


# 内置工具示例

class CodeFormatterTool(BaseTool):
    """代码格式化工具"""
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="format_code",
            description="格式化代码，支持多种语言",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要格式化的代码"},
                    "language": {"type": "string", "description": "语言: python, javascript, java"}
                },
                "required": ["code", "language"]
            },
            handler=self.execute
        )
    
    async def execute(self, code: str, language: str = "python") -> str:
        # 简化的格式化逻辑
        lines = code.split("\n")
        formatted = []
        
        for line in lines:
            # 移除行尾空格
            line = line.rstrip()
            # 增加适当缩进
            formatted.append(line)
        
        return "\n".join(formatted)


class DependencyCheckerTool(BaseTool):
    """依赖检查工具"""
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="check_dependencies",
            description="检查代码中使用的依赖是否安全",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "代码内容"},
                    "language": {"type": "string", "description": "语言"}
                },
                "required": ["code"]
            },
            handler=self.execute
        )
    
    async def execute(self, code: str, language: str = "python") -> dict:
        # 简化的依赖检查
        imports = []
        
        for line in code.split("\n"):
            if line.strip().startswith(("import ", "from ")):
                imports.append(line.strip())
        
        return {
            "imports": imports,
            "total": len(imports),
            "warnings": []
        }


# 注册内置工具
def register_builtin_tools():
    """注册内置工具"""
    ToolRegistry.register(CodeFormatterTool())
    ToolRegistry.register(DependencyCheckerTool())


# 全局MCP服务器
_mcp_server: MCPServer = None


def get_mcp_server() -> MCPServer:
    """获取MCP服务器"""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer("builtin")
        register_builtin_tools()
    return _mcp_server
