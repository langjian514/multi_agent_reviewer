"""规范Agent - 规则检查 + Qwen LLM 最佳实践分析"""
import re

from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState
from config.settings import settings


class LinterAgent(BaseAgent):
    """规范Agent - 负责编码规范检查，由 Qwen 增强"""

    def __init__(self):
        super().__init__(AgentType.LINTER, model=settings.linter_model)

    def process(self, state: SharedState) -> dict:
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.LINTING

        code = state["original_code"]
        language = state.get("language", "python")

        try:
            rule_result = self._lint_code(code, language)
            llm_result = self._llm_lint(code, language)
            merged = self._merge_results(rule_result, llm_result)

            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"规范检查完成: {len(merged['style_violations'])} 个风格问题, "
                f"{len(merged['naming_issues'])} 个命名问题",
                {"result": merged},
            )
            self.log_end(state)
            return {"lint_result": merged, "messages": [message]}
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}

    def _llm_lint(self, code: str, language: str) -> dict:
        """使用 Qwen 规范检查"""
        system_prompt = (
            "你是一位资深代码审查专家。请检查以下代码的编码规范，输出 JSON，包含：\n"
            "- issues：问题列表 [{\"type\", \"severity\", \"description\", \"line\", \"recommendation\"}]\n"
            "- code_quality (good/fair/poor)：代码质量评级\n"
            "- suggestions：改进建议列表\n"
            "仅输出 JSON，不要额外文字。"
        )
        user_prompt = f"语言: {language}\n\n```\n{code}\n```"
        try:
            result = self.llm.chat_json(
                self.build_prompt(system_prompt, user_prompt),
                temperature=0.2,
            )
            return {
                "llm_issues": result.get("issues", []),
                "code_quality": result.get("code_quality", "fair"),
                "llm_suggestions": result.get("suggestions", []),
            }
        except Exception as e:
            print(f"[Qwen] 规范检查失败: {e}")
            return {}

    def _merge_results(self, rule: dict, llm: dict) -> dict:
        llm_issues = llm.get("llm_issues", [])
        for issue in llm_issues:
            issue["source"] = "qwen"
            cat = issue.get("type", "")
            if "naming" in cat:
                rule["naming_issues"].append(issue)
            elif "style" in cat or "format" in cat:
                rule["style_violations"].append(issue)
            elif "error" in cat or "exception" in cat:
                rule["error_handling_issues"].append(issue)
            else:
                rule["best_practices"].append({"type": "llm_suggestion",
                                                "message": issue.get("description")})
        if llm.get("llm_suggestions"):
            rule["llm_suggestions"] = llm["llm_suggestions"]
        if llm.get("code_quality"):
            rule["code_quality"] = llm["code_quality"]
        return rule

    # ===== 规则检查逻辑 =====

    def _lint_code(self, code: str, language: str) -> dict:
        style_violations = []; naming_issues = []; error_handling_issues = []; best_practices = []
        if language == "python":
            style_violations = self._check_python_style(code)
            naming_issues = self._check_python_naming(code)
            error_handling_issues = self._check_error_handling(code)
            best_practices = self._check_best_practices(code)
        suggestion = self._generate_suggestion(style_violations, naming_issues, error_handling_issues)
        return {
            "style_violations": style_violations,
            "naming_issues": naming_issues,
            "error_handling_issues": error_handling_issues,
            "best_practices": best_practices,
            "suggestion": suggestion,
        }

    def _check_python_style(self, code: str) -> list[dict]:
        violations = []
        for i, line in enumerate(code.split("\n"), 1):
            if len(line) > 120:
                violations.append({"type": "line_too_long", "severity": "info",
                                   "message": f"行超过120字符 ({len(line)}字符)", "line": i})
            if line != line.rstrip():
                violations.append({"type": "trailing_whitespace", "severity": "info",
                                   "message": "行尾存在空格", "line": i})
            if re.search(r'type\([^)]+\)\s*==', line):
                violations.append({"type": "use_isinstance", "severity": "warning",
                                   "message": "使用isinstance()代替type()比较", "line": i})
            if re.search(r'==\s*None', line):
                violations.append({"type": "use_is_none", "severity": "info",
                                   "message": "使用 'is None' 而不是 '== None'", "line": i})
        return violations

    def _check_python_naming(self, code: str) -> list[dict]:
        issues = []
        for i, line in enumerate(code.split("\n"), 1):
            m = re.match(r'def\s+([A-Z][a-zA-Z0-9_]*)\s*\(', line.strip())
            if m:
                issues.append({"type": "function_naming", "severity": "warning",
                               "message": f"函数名 {m.group(1)} 不符合snake_case规范", "line": i})
        return issues

    def _check_error_handling(self, code: str) -> list[dict]:
        issues = []
        for i, line in enumerate(code.split("\n"), 1):
            if line.strip() == "except:":
                issues.append({"type": "bare_except", "severity": "warning",
                               "message": "使用具体的异常类型而不是裸except", "line": i})
        return issues

    def _check_best_practices(self, code: str) -> list[dict]:
        practices = []
        for i, line in enumerate(code.split("\n"), 1):
            if 'open(' in line and 'with' not in line and not line.strip().startswith('#'):
                practices.append({"type": "use_with_statement", "severity": "info",
                                  "message": "文件操作应使用with语句", "line": i})
            if re.match(r'def\s+\w+\s*\(', line.strip()) and '->' not in line:
                practices.append({"type": "add_type_hints", "severity": "info",
                                  "message": "建议为函数添加类型注解", "line": i})
        return practices

    def _generate_suggestion(self, style, naming, error):
        parts = []
        if style:
            parts.append(f"修复{len(style)}个风格问题")
        if naming:
            parts.append(f"改进{len(naming)}个命名")
        if error:
            parts.append(f"改进{len(error)}个异常处理")
        return "; ".join(parts) if parts else "代码规范良好，继续保持"
