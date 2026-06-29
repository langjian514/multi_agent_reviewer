"""安全Agent - 规则扫描 + Qwen LLM 深度漏洞分析"""
import re

from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState
from config.settings import settings


class SecurityAgent(BaseAgent):
    """安全Agent - 负责漏洞检测和安全扫描，由 Qwen 增强"""

    def __init__(self):
        super().__init__(AgentType.SECURITY, model=settings.security_model)

    def process(self, state: SharedState) -> dict:
        """执行安全扫描（规则 + Qwen LLM）"""
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.SECURITY_SCANNING

        code = state["original_code"]
        language = state.get("language", "python")

        try:
            rule_result = self._scan_security(code, language)
            llm_result = self._llm_scan(code, language)
            merged = self._merge_results(rule_result, llm_result)

            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"安全扫描完成: {merged['severity_counts'].get('critical', 0)} 个严重漏洞, "
                f"{len(merged['vulnerabilities'])} 个漏洞",
                {"result": merged},
            )
            self.log_end(state)
            return {"security_result": merged, "messages": [message]}
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}

    def _llm_scan(self, code: str, language: str) -> dict:
        """使用 Qwen 进行深度安全分析"""
        system_prompt = (
            "你是一位资深安全工程师。请分析以下代码的安全风险，输出 JSON，包含：\n"
            "- vulnerabilities：漏洞列表 [{\"type\", \"severity\"(critical/high/medium/low), "
            "\"description\", \"line\", \"recommendation\"}]\n"
            "- security_score (0-10)：安全评分\n"
            "- summary：安全分析总结\n"
            "仅输出 JSON，不要额外文字。"
        )
        user_prompt = f"语言: {language}\n\n```\n{code}\n```"
        try:
            result = self.llm.chat_json(
                self.build_prompt(system_prompt, user_prompt),
                temperature=0.2,
            )
            return {
                "llm_vulnerabilities": result.get("vulnerabilities", []),
                "security_score": result.get("security_score", 5.0),
                "summary": result.get("summary", ""),
            }
        except Exception as e:
            print(f"[Qwen] 安全分析失败: {e}")
            return {}

    def _merge_results(self, rule: dict, llm: dict) -> dict:
        llm_vulns = llm.get("llm_vulnerabilities", [])
        for vuln in llm_vulns:
            vuln["source"] = "qwen"
            rule["vulnerabilities"].append(vuln)
        sev = rule["severity_counts"]
        for v in rule["vulnerabilities"]:
            s = v.get("severity", "low")
            if s in sev:
                sev[s] = sev.get(s, 0) + 1
        if llm.get("security_score"):
            rule["security_score"] = llm["security_score"]
        if llm.get("summary"):
            rule["llm_summary"] = llm["summary"]
        return rule

    # ===== 规则扫描逻辑 =====

    def _scan_security(self, code: str, language: str) -> dict:
        vulnerabilities = []; sql_injection_risks = []; xss_risks = []; other_risks = []
        sql_injection_risks = self._check_sql_injection(code, language)
        xss_risks = self._check_xss(code, language)
        other_risks.extend(self._check_command_injection(code, language))
        vulnerabilities.extend(self._check_hardcoded_secrets(code))
        vulnerabilities.extend(self._check_insecure_dependencies(code, language))
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for v in vulnerabilities:
            s = v.get("severity", "low")
            if s in severity_counts:
                severity_counts[s] += 1
        return {
            "vulnerabilities": vulnerabilities,
            "sql_injection_risks": sql_injection_risks,
            "xss_risks": xss_risks,
            "other_risks": other_risks,
            "severity_counts": severity_counts,
        }

    def _check_sql_injection(self, code: str, language: str) -> list[dict]:
        risks = []
        patterns = [
            (r'execute\s*\(\s*["\'].*%s.*["\']', "execute() with string formatting"),
            (r'execute\s*\(\s*f["\']', "execute() with f-string"),
            (r'cursor\.execute\s*\([^,]+%s', "cursor.execute() with % formatting"),
            (r'SELECT\s+.*\+.*FROM', "SELECT with string concatenation"),
            (r'INSERT\s+.*\+.*INTO', "INSERT with string concatenation"),
            (r'UPDATE\s+.*\+.*SET', "UPDATE with string concatenation"),
            (r'execute\s*\([^,]*%', "execute() with % placeholder without tuple"),
        ]
        for pattern, desc in patterns:
            for match in re.finditer(pattern, code, re.IGNORECASE):
                line_num = code[: match.start()].count("\n") + 1
                risks.append({"type": "sql_injection", "severity": "high",
                               "description": f"SQL注入风险: {desc}", "line": line_num,
                               "code": match.group(0)[:50],
                               "recommendation": "使用参数化查询或ORM", "source": "rule"})
        return risks

    def _check_xss(self, code: str, language: str) -> list[dict]:
        risks = []
        patterns = [
            (r'render_template_string\s*\([^)]*request\.', "render_template_string with request data"),
            (r'Markup\s*\([^)]*request\.', "Markup with request data"),
            (r'\.html\(.*request\.', "HTML generation with request data"),
            (r'innerHTML\s*=', "Direct innerHTML assignment"),
        ]
        for pattern, desc in patterns:
            for match in re.finditer(pattern, code, re.IGNORECASE):
                line_num = code[: match.start()].count("\n") + 1
                risks.append({"type": "xss", "severity": "medium",
                               "description": f"XSS风险: {desc}", "line": line_num,
                               "code": match.group(0)[:50],
                               "recommendation": "对用户输入进行HTML转义", "source": "rule"})
        return risks

    def _check_command_injection(self, code: str, language: str) -> list[dict]:
        risks = []
        patterns = [
            (r'os\.system\s*\(', "os.system() - command injection risk"),
            (r'subprocess\.\w+\s*\([^)]*\+', "subprocess with string concatenation"),
            (r'eval\s*\(', "eval() - code injection risk"),
            (r'exec\s*\(', "exec() - code injection risk"),
            (r'os\.popen\s*\(', "os.popen() - command injection risk"),
        ]
        for pattern, desc in patterns:
            for match in re.finditer(pattern, code):
                line_num = code[: match.start()].count("\n") + 1
                risks.append({"type": "command_injection", "severity": "critical",
                               "description": desc, "line": line_num,
                               "code": match.group(0)[:50],
                               "recommendation": "使用subprocess.run() with shell=False",
                               "source": "rule"})
        return risks

    def _check_hardcoded_secrets(self, code: str) -> list[dict]:
        secrets = []
        patterns = [
            (r'api[_-]?key\s*=\s*["\'][^"\']{10,}["\']', "API密钥硬编码"),
            (r'password\s*=\s*["\'][^"\']+["\']', "密码硬编码"),
            (r'mysql:\/\/[^:]+:[^@]+@', "数据库密码在连接字符串中"),
            (r'jwt\s*=\s*["\'][^"\']+["\']', "JWT令牌硬编码"),
            (r'sk-[A-Za-z0-9]{20,}', "可能的 Secret Key"),
        ]
        for pattern, desc in patterns:
            for match in re.finditer(pattern, code, re.IGNORECASE):
                line_num = code[: match.start()].count("\n") + 1
                secrets.append({"type": "hardcoded_secret", "severity": "critical",
                                 "description": desc, "line": line_num, "code": "[REDACTED]",
                                 "recommendation": "使用环境变量或密钥管理服务", "source": "rule"})
        return secrets

    def _check_insecure_dependencies(self, code: str, language: str) -> list[dict]:
        issues = []
        if language == "python":
            known = {"requests": "2.25.0", "urllib3": "1.26.0", "jinja2": "3.0.0",
                     "django": "3.2.0", "flask": "1.1.0", "numpy": "1.22.0",
                     "pillow": "8.3.0", "pyyaml": "5.4.0"}
            for line in code.split("\n"):
                m = re.match(r"^(?:from|import)\s+(\w+)", line.strip())
                if m and m.group(1) in known:
                    pkg = m.group(1)
                    issues.append({"type": "insecure_dependency", "severity": "medium",
                                   "description": f"导入可能存在安全问题的包: {pkg}",
                                   "line": None,
                                   "recommendation": f"确保 {pkg} 版本 >= {known[pkg]}",
                                   "source": "rule"})
        return issues
