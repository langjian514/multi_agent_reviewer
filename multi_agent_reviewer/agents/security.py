"""安全Agent - 漏洞检测、SQL注入/XSS扫描"""
import re
from typing import TypedDict

from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState


class SecurityAgent(BaseAgent):
    """安全Agent - 负责漏洞检测和安全扫描"""
    
    def __init__(self):
        super().__init__(AgentType.SECURITY)
    
    def process(self, state: SharedState) -> dict:
        """执行安全扫描"""
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.SECURITY_SCANNING
        
        code = state["original_code"]
        language = state.get("language", "python")
        
        try:
            result = self._scan_security(code, language)
            
            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"安全扫描完成: 发现 {len(result['vulnerabilities'])} 个漏洞，{len(result['sql_injection_risks'])} 个SQL注入风险",
                {"result": result}
            )
            
            self.log_end(state)
            
            return {
                "security_result": result,
                "messages": [message]
            }
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}
    
    def _scan_security(self, code: str, language: str) -> dict:
        """执行安全扫描"""
        vulnerabilities = []
        sql_injection_risks = []
        xss_risks = []
        other_risks = []
        
        # SQL注入检测
        sql_injection_risks = self._check_sql_injection(code, language)
        
        # XSS检测
        xss_risks = self._check_xss(code, language)
        
        # 命令注入
        cmd_injection = self._check_command_injection(code, language)
        other_risks.extend(cmd_injection)
        
        # 硬编码敏感信息
        secrets = self._check_hardcoded_secrets(code)
        vulnerabilities.extend(secrets)
        
        # 不安全的依赖
        insecure_deps = self._check_insecure_dependencies(code, language)
        vulnerabilities.extend(insecure_deps)
        
        # 统计
        severity_counts = {
            "critical": len([v for v in vulnerabilities if v.get("severity") == "critical"]),
            "high": len([v for v in vulnerabilities if v.get("severity") == "high"]),
            "medium": len(sql_injection_risks) + len(xss_risks),
            "low": len(other_risks)
        }
        
        return {
            "vulnerabilities": vulnerabilities,
            "sql_injection_risks": sql_injection_risks,
            "xss_risks": xss_risks,
            "other_risks": other_risks,
            "severity_counts": severity_counts
        }
    
    def _check_sql_injection(self, code: str, language: str) -> list[dict]:
        """检测SQL注入风险"""
        risks = []
        
        # 不安全的SQL拼接模式
        patterns = [
            # Python - SQLAlchemy raw SQL
            (r'execute\s*\(\s*["\'].*%s.*["\']', "execute() with string formatting"),
            (r'execute\s*\(\s*f["\']', "execute() with f-string"),
            (r'cursor\.execute\s*\([^,]+%s', "cursor.execute() with % formatting"),
            
            # Python - 直接字符串拼接
            (r'SELECT\s+.*\+.*FROM', "SELECT with string concatenation"),
            (r'INSERT\s+.*\+.*INTO', "INSERT with string concatenation"),
            (r'UPDATE\s+.*\+.*SET', "UPDATE with string concatenation"),
            
            # Django raw()
            (r'raw\s*\(\s*f["\']', "Django raw() with f-string"),
            (r'extra\s*\(\s*where\s*=', "Django extra() with user input"),
            
            # MySQLdb/execute
            (r'execute\s*\([^,]*%', "execute() with % placeholder without tuple"),
        ]
        
        for pattern, desc in patterns:
            matches = re.finditer(pattern, code, re.IGNORECASE)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                risks.append({
                    "type": "sql_injection",
                    "severity": "high",
                    "description": f"SQL注入风险: {desc}",
                    "line": line_num,
                    "code": match.group(0)[:50],
                    "recommendation": "使用参数化查询或ORM"
                })
        
        return risks
    
    def _check_xss(self, code: str, language: str) -> list[dict]:
        """检测XSS风险"""
        risks = []
        
        # XSS风险模式
        patterns = [
            # 直接输出用户输入
            (r'render_template_string\s*\([^)]*request\.', "render_template_string with request data"),
            (r'Markup\s*\([^)]*request\.', "Markup with request data"),
            
            # 不安全的HTML生成
            (r'\.html\(.*request\.', "HTML generation with request data"),
            (r'response\s*=\s*.*\+.*{', "String concatenation for HTML response"),
            
            # 危险的innerHTML
            (r'innerHTML\s*=', "Direct innerHTML assignment"),
        ]
        
        for pattern, desc in patterns:
            matches = re.finditer(pattern, code, re.IGNORECASE)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                risks.append({
                    "type": "xss",
                    "severity": "medium",
                    "description": f"XSS风险: {desc}",
                    "line": line_num,
                    "code": match.group(0)[:50],
                    "recommendation": "对用户输入进行HTML转义"
                })
        
        return risks
    
    def _check_command_injection(self, code: str, language: str) -> list[dict]:
        """检测命令注入风险"""
        risks = []
        
        patterns = [
            (r'os\.system\s*\(', "os.system() - command injection risk"),
            (r'subprocess\.\w+\s*\([^)]*\+', "subprocess with string concatenation"),
            (r'eval\s*\(', "eval() - code injection risk"),
            (r'exec\s*\(', "exec() - code injection risk"),
            (r'os\.popen\s*\(', "os.popen() - command injection risk"),
            (r'commands\.getoutput\s*\(', "commands module - command injection risk"),
        ]
        
        for pattern, desc in patterns:
            matches = re.finditer(pattern, code)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                risks.append({
                    "type": "command_injection",
                    "severity": "critical",
                    "description": desc,
                    "line": line_num,
                    "code": match.group(0)[:50],
                    "recommendation": "使用subprocess.run() with shell=False"
                })
        
        return risks
    
    def _check_hardcoded_secrets(self, code: str) -> list[dict]:
        """检测硬编码的敏感信息"""
        secrets = []
        
        patterns = [
            # API密钥
            (r'api[_-]?key\s*=\s*["\'][^"\']{10,}["\']', "API密钥硬编码"),
            (r'apikey\s*=\s*["\'][^"\']{10,}["\']', "API密钥硬编码"),
            
            # 密码
            (r'password\s*=\s*["\'][^"\']+["\']', "密码硬编码"),
            (r'passwd\s*=\s*["\'][^"\']+["\']', "密码硬编码"),
            
            # 数据库连接
            (r'mysql:\/\/[^:]+:[^@]+@', "数据库密码在连接字符串中"),
            (r'postgresql:\/\/[^:]+:[^@]+@', "数据库密码在连接字符串中"),
            
            # JWT/Token
            (r'jwt\s*=\s*["\'][^"\']+["\']', "JWT令牌硬编码"),
            (r'bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+', "Bearer Token硬编码"),
            
            # 私钥
            (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "私钥文件"),
            (r'sk-[A-Za-z0-9]{20,}', "可能的Secret Key"),
        ]
        
        for pattern, desc in patterns:
            matches = re.finditer(pattern, code, re.IGNORECASE)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                secrets.append({
                    "type": "hardcoded_secret",
                    "severity": "critical",
                    "description": desc,
                    "line": line_num,
                    "code": "[REDACTED]",
                    "recommendation": "使用环境变量或密钥管理服务"
                })
        
        return secrets
    
    def _check_insecure_dependencies(self, code: str, language: str) -> list[dict]:
        """检测不安全的依赖"""
        issues = []
        
        if language == "python":
            # 已知有安全问题的包
            known_insecure = {
                "requests": "2.25.0",  # 低于此版本有漏洞
                "urllib3": "1.26.0",
                "jinja2": "3.0.0",
                "django": "3.2.0",
                "flask": "1.1.0",
                "numpy": "1.22.0",
                "pillow": "8.3.0",
                "pyyaml": "5.4.0",
            }
            
            # 简化检测：检查导入语句中的包名
            import_pattern = r'^(?:from|import)\s+(\w+)'
            for line in code.split('\n'):
                match = re.match(import_pattern, line.strip())
                if match:
                    pkg = match.group(1)
                    if pkg in known_insecure:
                        issues.append({
                            "type": "insecure_dependency",
                            "severity": "medium",
                            "description": f"导入可能存在安全问题的包: {pkg}",
                            "line": None,
                            "recommendation": f"确保 {pkg} 版本 >= {known_insecure[pkg]}"
                        })
        
        return issues
