"""分析Agent - 代码结构分析和复杂度评估"""
import re
from typing import Counter

from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState


class AnalyzerAgent(BaseAgent):
    """分析Agent - 负责代码结构分析、复杂度评估"""
    
    def __init__(self):
        super().__init__(AgentType.ANALYZER)
    
    def process(self, state: SharedState) -> dict:
        """执行代码分析"""
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.ANALYZING
        
        code = state["original_code"]
        language = state.get("language", "python")
        
        try:
            result = self._analyze_code(code, language)
            
            # 添加消息
            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"分析完成: 发现 {len(result['key_functions'])} 个关键函数，复杂度 {result['complexity_score']:.2f}",
                {"result": result}
            )
            
            self.log_end(state)
            
            return {
                "analysis_result": result,
                "messages": [message]
            }
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}
    
    def _analyze_code(self, code: str, language: str) -> dict:
        """执行代码分析"""
        # 基础指标
        lines = code.split("\n")
        total_lines = len(lines)
        code_lines = [l for l in lines if l.strip() and not l.strip().startswith(("#", "//"))]
        
        # 函数检测
        functions = self._extract_functions(code, language)
        
        # 类检测
        classes = self._extract_classes(code, language)
        
        # 复杂度评估
        complexity = self._calculate_complexity(code, functions, classes)
        
        # 依赖分析
        dependencies = self._extract_dependencies(code, language)
        
        # 识别问题
        issues = self._identify_issues(code, functions, classes)
        
        return {
            "code_structure": {
                "total_lines": total_lines,
                "code_lines": len(code_lines),
                "comment_lines": total_lines - len(code_lines),
                "functions": [f["name"] for f in functions],
                "classes": [c["name"] for c in classes],
            },
            "complexity_score": complexity,
            "key_functions": [f["name"] for f in functions],
            "dependencies": dependencies,
            "issues": issues
        }
    
    def _extract_functions(self, code: str, language: str) -> list[dict]:
        """提取函数"""
        functions = []
        
        if language == "python":
            # 匹配def函数
            pattern = r'def\s+(\w+)\s*\([^)]*\)\s*(?:->\s*[\w\[\],\s]+)?:'
            for match in re.finditer(pattern, code):
                functions.append({
                    "name": match.group(1),
                    "line": code[:match.start()].count('\n') + 1
                })
        
        return functions
    
    def _extract_classes(self, code: str, language: str) -> list[dict]:
        """提取类"""
        classes = []
        
        if language == "python":
            pattern = r'class\s+(\w+)(?:\([^)]*\))?\s*:'
            for match in re.finditer(pattern, code):
                classes.append({
                    "name": match.group(1),
                    "line": code[:match.start()].count('\n') + 1
                })
        
        return classes
    
    def _calculate_complexity(self, code: str, functions: list, classes: list) -> float:
        """计算代码复杂度"""
        complexity = 1.0
        
        # 循环复杂度
        for_count = len(re.findall(r'\bfor\b', code))
        while_count = len(re.findall(r'\bwhile\b', code))
        
        # 条件复杂度
        if_count = len(re.findall(r'\bif\b', code))
        
        # 异常处理
        try_count = len(re.findall(r'\btry\b', code))
        
        # 计算
        cyclomatic = 1 + for_count + while_count + if_count + try_count
        complexity = min(cyclomatic / 10, 10)  # 归一化到0-10
        
        # 考虑函数和类数量
        if len(functions) > 20:
            complexity += 1
        if len(classes) > 10:
            complexity += 1
        
        return round(complexity, 2)
    
    def _extract_dependencies(self, code: str, language: str) -> list[str]:
        """提取依赖"""
        deps = []
        
        if language == "python":
            # import 语句
            import_pattern = r'^import\s+(\w+)|^from\s+(\w+)'
            for line in code.split('\n'):
                match = re.match(import_pattern, line.strip())
                if match:
                    dep = match.group(1) or match.group(2)
                    if dep and dep not in deps:
                        deps.append(dep)
        
        return deps
    
    def _identify_issues(self, code: str, functions: list, classes: list) -> list[dict]:
        """识别代码问题"""
        issues = []
        
        # 长函数检测
        if len(functions) > 0:
            for func in functions:
                func_lines = self._get_function_lines(code, func["line"], len(code.split("\n")))
                if func_lines > 100:
                    issues.append({
                        "type": "long_function",
                        "severity": "warning",
                        "message": f"函数 {func['name']} 超过100行 ({func_lines}行)",
                        "line": func["line"]
                    })
        
        # 缺少文档字符串
        for func in functions:
            if not self._has_docstring(code, func["line"]):
                issues.append({
                    "type": "missing_docstring",
                    "severity": "info",
                    "message": f"函数 {func['name']} 缺少文档字符串",
                    "line": func["line"]
                })
        
        # 嵌套过深
        max_nesting = self._get_max_nesting(code)
        if max_nesting > 4:
            issues.append({
                "type": "deep_nesting",
                "severity": "warning",
                "message": f"代码嵌套过深 (最大{max_nesting}层)",
                "line": None
            })
        
        return issues
    
    def _get_function_lines(self, code: str, start_line: int, total_lines: int) -> int:
        """获取函数行数"""
        lines = code.split("\n")
        if start_line > len(lines):
            return 0
        
        indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())
        
        end_line = start_line
        for i in range(start_line, len(lines)):
            line = lines[i]
            if line.strip() and not line.strip().startswith('#'):
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= indent and i > start_line:
                    break
            end_line = i + 1
        
        return end_line - start_line + 1
    
    def _has_docstring(self, code: str, func_line: int) -> bool:
        """检查是否有文档字符串"""
        lines = code.split("\n")
        if func_line > len(lines):
            return False
        
        # 检查函数定义后的第一行是否是文档字符串
        if func_line < len(lines) and '"""' in lines[func_line]:
            return True
        if func_line < len(lines) and "'''" in lines[func_line]:
            return True
        
        return False
    
    def _get_max_nesting(self, code: str) -> int:
        """获取最大嵌套深度"""
        max_nesting = 0
        current_nesting = 0
        
        for line in code.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith(('#', '//', '"""', "'''")):
                continue
            
            # 计算缩进
            indent = len(line) - len(line.lstrip())
            
            # 增加缩进
            if any(kw in line for kw in ['if ', 'for ', 'while ', 'with ']):
                if '{' not in line and ':' in line:
                    current_nesting += 1
                    max_nesting = max(max_nesting, current_nesting)
            
            # 减少缩进 (简化处理)
            if stripped.startswith('return ') or stripped.startswith('break') or stripped.startswith('continue'):
                current_nesting = max(0, current_nesting - 1)
        
        return max_nesting
