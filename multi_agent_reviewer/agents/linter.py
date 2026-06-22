"""规范Agent - 编码规范、命名检查、异常处理"""
import re
from typing import Set

from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState


class LinterAgent(BaseAgent):
    """规范Agent - 负责编码规范检查"""
    
    def __init__(self):
        super().__init__(AgentType.LINTER)
    
    def process(self, state: SharedState) -> dict:
        """执行规范检查"""
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.LINTING
        
        code = state["original_code"]
        language = state.get("language", "python")
        
        try:
            result = self._lint_code(code, language)
            
            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"规范检查完成: {len(result['style_violations'])} 个风格问题，{len(result['naming_issues'])} 个命名问题",
                {"result": result}
            )
            
            self.log_end(state)
            
            return {
                "lint_result": result,
                "messages": [message]
            }
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}
    
    def _lint_code(self, code: str, language: str) -> dict:
        """执行代码规范检查"""
        style_violations = []
        naming_issues = []
        error_handling_issues = []
        best_practices = []
        
        if language == "python":
            style_violations = self._check_python_style(code)
            naming_issues = self._check_python_naming(code)
            error_handling_issues = self._check_error_handling(code)
            best_practices = self._check_best_practices(code)
        
        suggestion = self._generate_suggestion(
            style_violations, naming_issues, error_handling_issues
        )
        
        return {
            "style_violations": style_violations,
            "naming_issues": naming_issues,
            "error_handling_issues": error_handling_issues,
            "best_practices": best_practices,
            "suggestion": suggestion
        }
    
    def _check_python_style(self, code: str) -> list[dict]:
        """检查Python代码风格"""
        violations = []
        lines = code.split("\n")
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # 行太长 (>120字符)
            if len(line) > 120:
                violations.append({
                    "type": "line_too_long",
                    "severity": "info",
                    "message": f"行超过120字符 ({len(line)}字符)",
                    "line": i
                })
            
            # 行尾空格
            if line != line.rstrip():
                violations.append({
                    "type": "trailing_whitespace",
                    "severity": "info",
                    "message": "行尾存在空格",
                    "line": i
                })
            
            # 多余空行
            if stripped == "" and i > 1:
                prev_line = lines[i-2].strip() if i > 1 else ""
                next_line = lines[i] if i < len(lines) else ""
                if prev_line and next_line == "":
                    violations.append({
                        "type": "extra_blank_line",
                        "severity": "info",
                        "message": "多余空行",
                        "line": i
                    })
            
            # 不使用isinstance而用type()
            if re.search(r'type\([^)]+\)\s*==', line):
                violations.append({
                    "type": "use_isinstance",
                    "severity": "warning",
                    "message": "使用isinstance()代替type()比较",
                    "line": i
                })
            
            # 使用== None而不是is None
            if re.search(r'==\s*None', line):
                violations.append({
                    "type": "use_is_none",
                    "severity": "info",
                    "message": "使用 'is None' 而不是 '== None'",
                    "line": i
                })
            
            # 魔法数字
            magic_num = re.findall(r'\b([1-9]\d+)\b', line)
            if magic_num and any(int(n) > 1 for n in magic_num):
                # 排除常见无意义检查
                if not any(x in line.lower() for x in ['range', 'id', 'version', 'port', 'timeout']):
                    violations.append({
                        "type": "magic_number",
                        "severity": "info",
                        "message": f"发现魔法数字: {magic_num}",
                        "line": i,
                        "recommendation": "使用命名常量代替"
                    })
        
        # 检查import顺序
        import_lines = []
        for i, line in enumerate(lines, 1):
            if re.match(r'^(from|import)\s+', line.strip()):
                import_lines.append((i, line.strip()))
        
        if len(import_lines) > 3:
            # 检查是否按标准库、第三方、本地顺序排列
            stdlib = []
            thirdparty = []
            local = []
            current_section = None
            
            for line_num, line in import_lines:
                if 'from.' in line or 'from ' in line.split()[1]:
                    continue
                pkg = line.split()[1] if line.startswith('import') else line.split()[1]
                
                if pkg in ['__future__', 'builtins']:
                    if current_section and current_section != 'stdlib':
                        violations.append({
                            "type": "import_order",
                            "severity": "info",
                            "message": "import顺序不符合规范 (标准库/第三方/本地)",
                            "line": line_num
                        })
                    current_section = 'stdlib'
                elif '.' in pkg:
                    if current_section and current_section != 'local':
                        violations.append({
                            "type": "import_order",
                            "severity": "info",
                            "message": "import顺序不符合规范",
                            "line": line_num
                        })
                    current_section = 'local'
                else:
                    if current_section == 'local':
                        violations.append({
                            "type": "import_order",
                            "severity": "info",
                            "message": "import顺序不符合规范",
                            "line": line_num
                        })
                    current_section = 'thirdparty'
        
        return violations
    
    def _check_python_naming(self, code: str) -> list[dict]:
        """检查命名规范"""
        issues = []
        lines = code.split("\n")
        
        for i, line in enumerate(lines, 1):
            # 类名检查 (应该使用CapWords)
            class_match = re.match(r'class\s+([A-Z][a-zA-Z0-9]*)\s*[:\(]', line.strip())
            if class_match:
                class_name = class_match.group(1)
                if not re.match(r'^[A-Z][a-zA-Z0-9]*$', class_name):
                    issues.append({
                        "type": "class_naming",
                        "severity": "warning",
                        "message": f"类名 {class_name} 不符合CapWords规范",
                        "line": i
                    })
            
            # 函数名检查 (应该使用snake_case)
            func_match = re.match(r'def\s+([A-Z][a-zA-Z0-9_]*)\s*\(', line.strip())
            if func_match:
                func_name = func_match.group(1)
                issues.append({
                    "type": "function_naming",
                    "severity": "warning",
                    "message": f"函数名 {func_name} 不符合snake_case规范",
                    "line": i
                })
            
            # 变量名检查
            var_match = re.match(r'\s*([A-Z][A-Z0-9_]*)\s*=', line)
            if var_match:
                var_name = var_match.group(1)
                # 排除常量（全大写可能是故意的常量）
                if '_' in var_name and var_name.isupper():
                    issues.append({
                        "type": "constant_naming",
                        "severity": "info",
                        "message": f"常量 {var_name} 应该放在模块顶部并添加下划线前缀",
                        "line": i
                    })
            
            # 私有变量检查
            if re.match(r'\s*_[^_].*\s*=', line):
                pass  # 正常的私有变量
            
            # dunder方法检查
            if re.search(r'__\w+__\s*\(', line):
                if not re.match(r'__\w+__\s*=\s*', line):
                    issues.append({
                        "type": "dunder_method",
                        "severity": "warning",
                        "message": "避免直接定义dunder方法，使用标准库或框架提供的方法",
                        "line": i
                    })
        
        return issues
    
    def _check_error_handling(self, code: str) -> list[dict]:
        """检查异常处理"""
        issues = []
        lines = code.split("\n")
        
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # 裸except
            if stripped == 'except:':
                issues.append({
                    "type": "bare_except",
                    "severity": "warning",
                    "message": "使用具体的异常类型而不是裸except",
                    "line": i
                })
            
            # except pass (吞掉异常)
            if stripped == 'except' or 'except Exception:\n' in code or 'except Exception:\r' in code:
                # 检查下一行
                if i < len(lines) and lines[i].strip() == 'pass':
                    issues.append({
                        "type": "except_pass",
                        "severity": "warning",
                        "message": "不要用pass吞掉异常，至少记录日志",
                        "line": i
                    })
            
            # raise NotImplemented
            if 'NotImplemented' in stripped and 'raise' in stripped:
                issues.append({
                    "type": "not_implemented",
                    "severity": "info",
                    "message": "NotImplementedError是异常，NotImplemented是常量",
                    "line": i
                })
            
            # 捕获后又抛出相同异常
            if 'except' in stripped and 'raise' in stripped:
                issues.append({
                    "type": "re_raise_same",
                    "severity": "info",
                    "message": "捕获后又重新抛出相同的异常，可以直接使用raise而不捕获",
                    "line": i
                })
        
        return issues
    
    def _check_best_practices(self, code: str) -> list[dict]:
        """检查最佳实践"""
        practices = []
        lines = code.split("\n")
        
        # 检查使用列表/字典推导式
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # 使用with语句
            if 'open(' in stripped and 'with' not in stripped and not stripped.startswith('#'):
                practices.append({
                    "type": "use_with_statement",
                    "severity": "info",
                    "message": "文件操作应使用with语句",
                    "line": i
                })
            
            # 使用f-string
            if '+ \'' in stripped or '+ "' in stripped or ' % ' in stripped:
                practices.append({
                    "type": "use_fstring",
                    "severity": "info",
                    "message": "建议使用f-string代替字符串拼接",
                    "line": i
                })
            
            # 检查类型注解
            if re.match(r'def\s+\w+\s*\(', stripped) and '->' not in stripped:
                practices.append({
                    "type": "add_type_hints",
                    "severity": "info",
                    "message": "建议为函数添加类型注解",
                    "line": i
                })
        
        return practices
    
    def _generate_suggestion(
        self,
        style_violations: list,
        naming_issues: list,
        error_handling_issues: list
    ) -> str:
        """生成改进建议"""
        suggestions = []
        
        if style_violations:
            suggestions.append(f"修复{len(style_violations)}个风格问题")
        if naming_issues:
            suggestions.append(f"改进{len(naming_issues)}个命名")
        if error_handling_issues:
            suggestions.append(f"改进{len(error_handling_issues)}个异常处理")
        
        if not suggestions:
            return "代码规范良好，继续保持"
        
        return "; ".join(suggestions)
