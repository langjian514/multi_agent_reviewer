"""分析Agent - 代码结构分析 + Qwen LLM 深度分析"""
import json
import re

from agents.base import BaseAgent, QwenClient
from core.state import SharedState, AgentType, ReviewState
from config.settings import settings


class AnalyzerAgent(BaseAgent):
    """分析Agent - 负责代码结构分析、复杂度评估，由 Qwen 增强"""

    def __init__(self):
        super().__init__(AgentType.ANALYZER, model=settings.analyzer_model)

    def process(self, state: SharedState) -> dict:
        """执行代码分析（规则 + Qwen LLM）"""
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.ANALYZING

        code = state["original_code"]
        language = state.get("language", "python")

        try:
            # 1. 规则分析
            rule_result = self._analyze_code(code, language)

            # 2. Qwen LLM 深度分析
            llm_result = self._llm_analyze(code, language)

            # 合并结果（LLM 覆盖/补充规则分析）
            merged = self._merge_results(rule_result, llm_result)

            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"分析完成: {len(merged['key_functions'])} 个关键函数, "
                f"复杂度 {merged['complexity_score']:.2f}, "
                f"发现 {len(merged['issues'])} 个问题",
                {"result": merged},
            )

            self.log_end(state)
            return {"analysis_result": merged, "messages": [message]}
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}

    def _llm_analyze(self, code: str, language: str) -> dict:
        """使用 Qwen 进行深度代码分析"""
        system_prompt = (
            "你是一位资深代码审查专家。请分析以下代码，输出 JSON，包含：\n"
            "- complexity_score (0-10)：综合复杂度\n"
            "- key_functions：核心函数名列表\n"
            "- weaknesses：弱点列表 [{\"type\", \"severity\", \"description\", \"line\", \"recommendation\"}]\n"
            "- summary：一句话分析总结\n"
            "仅输出 JSON，不要额外文字。"
        )
        user_prompt = f"语言: {language}\n\n```\n{code}\n```"

        try:
            result = self.llm.chat_json(
                self.build_prompt(system_prompt, user_prompt),
                temperature=0.2,
            )
            return {
                "complexity_score": result.get("complexity_score", 5.0),
                "key_functions": result.get("key_functions", []),
                "llm_issues": result.get("weaknesses", []),
                "summary": result.get("summary", ""),
            }
        except Exception as e:
            print(f"[Qwen] 分析失败: {e}")
            return {}

    def _merge_results(self, rule: dict, llm: dict) -> dict:
        """合并规则分析和 LLM 分析结果"""
        # 复杂度取较高值
        if llm.get("complexity_score", 0) > rule.get("complexity_score", 0):
            rule["complexity_score"] = llm["complexity_score"]

        # 补充 LLM 发现的问题
        llm_issues = llm.get("llm_issues", [])
        existing = {json.dumps(i, ensure_ascii=False) for i in rule.get("issues", [])}
        for issue in llm_issues:
            key = json.dumps(issue, ensure_ascii=False)
            if key not in existing:
                issue["source"] = "qwen"
                rule["issues"].append(issue)
                existing.add(key)

        # 补充 LLM 提到的函数（去重）
        known = set(rule.get("key_functions", []))
        known.update(llm.get("key_functions", []))
        rule["key_functions"] = list(known)

        # LLM 摘要
        if llm.get("summary"):
            rule["llm_summary"] = llm["summary"]

        return rule

    # ----- 以下为原有规则分析方法，保持不变 -----

    def _analyze_code(self, code: str, language: str) -> dict:
        lines = code.split("\n")
        total_lines = len(lines)
        code_lines = [l for l in lines if l.strip() and not l.strip().startswith(("#", "//"))]
        functions = self._extract_functions(code, language)
        classes = self._extract_classes(code, language)
        complexity = self._calculate_complexity(code, functions, classes)
        dependencies = self._extract_dependencies(code, language)
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
            "issues": issues,
        }

    def _extract_functions(self, code: str, language: str) -> list[dict]:
        functions = []
        if language == "python":
            pattern = r"def\s+(\w+)\s*\([^)]*\)\s*(?:->\s*[\w\[\],\s]+)?:"
            for match in re.finditer(pattern, code):
                functions.append({"name": match.group(1), "line": code[: match.start()].count("\n") + 1})
        return functions

    def _extract_classes(self, code: str, language: str) -> list[dict]:
        classes = []
        if language == "python":
            pattern = r"class\s+(\w+)(?:\([^)]*\))?\s*:"
            for match in re.finditer(pattern, code):
                classes.append({"name": match.group(1), "line": code[: match.start()].count("\n") + 1})
        return classes

    def _calculate_complexity(self, code: str, functions: list, classes: list) -> float:
        complexity = 1.0
        for_count = len(re.findall(r"\bfor\b", code))
        while_count = len(re.findall(r"\bwhile\b", code))
        if_count = len(re.findall(r"\bif\b", code))
        try_count = len(re.findall(r"\btry\b", code))
        cyclomatic = 1 + for_count + while_count + if_count + try_count
        complexity = min(cyclomatic / 10, 10)
        if len(functions) > 20:
            complexity += 1
        if len(classes) > 10:
            complexity += 1
        return round(complexity, 2)

    def _extract_dependencies(self, code: str, language: str) -> list[str]:
        deps = []
        if language == "python":
            import_pattern = r"^import\s+(\w+)|^from\s+(\w+)"
            for line in code.split("\n"):
                match = re.match(import_pattern, line.strip())
                if match:
                    dep = match.group(1) or match.group(2)
                    if dep and dep not in deps:
                        deps.append(dep)
        return deps

    def _identify_issues(self, code: str, functions: list, classes: list) -> list[dict]:
        issues = []
        for func in functions:
            func_lines = self._get_function_lines(code, func["line"], len(code.split("\n")))
            if func_lines > 100:
                issues.append({"type": "long_function", "severity": "warning",
                               "message": f"函数 {func['name']} 超过100行 ({func_lines}行)",
                               "line": func["line"], "source": "rule"})
        for func in functions:
            if not self._has_docstring(code, func["line"]):
                issues.append({"type": "missing_docstring", "severity": "info",
                               "message": f"函数 {func['name']} 缺少文档字符串",
                               "line": func["line"], "source": "rule"})
        max_nesting = self._get_max_nesting(code)
        if max_nesting > 4:
            issues.append({"type": "deep_nesting", "severity": "warning",
                           "message": f"代码嵌套过深 (最大{max_nesting}层)",
                           "line": None, "source": "rule"})
        return issues

    def _get_function_lines(self, code: str, start_line: int, total_lines: int) -> int:
        lines = code.split("\n")
        if start_line > len(lines):
            return 0
        indent = len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())
        end_line = start_line
        for i in range(start_line, len(lines)):
            line = lines[i]
            if line.strip() and not line.strip().startswith("#"):
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= indent and i > start_line:
                    break
            end_line = i + 1
        return end_line - start_line + 1

    def _has_docstring(self, code: str, func_line: int) -> bool:
        lines = code.split("\n")
        if func_line > len(lines):
            return False
        if func_line < len(lines) and ('"""' in lines[func_line] or "'''" in lines[func_line]):
            return True
        return False

    def _get_max_nesting(self, code: str) -> int:
        max_nesting = 0
        current_nesting = 0
        for line in code.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", '"""', "'''")):
                continue
            if any(kw in line for kw in ["if ", "for ", "while ", "with "]):
                if "{" not in line and ":" in line:
                    current_nesting += 1
                    max_nesting = max(max_nesting, current_nesting)
            if stripped.startswith("return ") or stripped.startswith("break") or stripped.startswith("continue"):
                current_nesting = max(0, current_nesting - 1)
        return max_nesting
