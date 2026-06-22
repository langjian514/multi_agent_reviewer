"""总结Agent - 汇总各Agent结果、生成审查报告"""
from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState


class ReviewerAgent(BaseAgent):
    """总结Agent - 负责汇总结果并生成最终报告"""
    
    def __init__(self):
        super().__init__(AgentType.REVIEWER)
    
    def process(self, state: SharedState) -> dict:
        """生成最终审查报告"""
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.REVIEWING
        
        try:
            report = self._generate_report(state)
            
            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"审查报告生成完成: 质量评分 {report['quality_score']:.2f}, 置信度 {report['confidence']:.2f}",
                {"report": report}
            )
            
            self.log_end(state)
            
            return {
                "review_report": report,
                "messages": [message]
            }
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}
    
    def _generate_report(self, state: SharedState) -> dict:
        """生成完整的审查报告"""
        analysis = state.get("analysis_result") or {}
        security = state.get("security_result") or {}
        lint = state.get("lint_result") or {}
        
        # 收集所有问题
        all_issues = []
        critical_issues = []
        warnings = []
        suggestions = []
        
        # 从分析结果中提取问题
        if analysis.get("issues"):
            for issue in analysis["issues"]:
                issue["category"] = "analysis"
                all_issues.append(issue)
                if issue.get("severity") == "warning":
                    warnings.append(issue)
        
        # 从安全结果中提取漏洞
        if security.get("vulnerabilities"):
            for vuln in security["vulnerabilities"]:
                vuln["category"] = "security"
                all_issues.append(vuln)
                if vuln.get("severity") in ("critical", "high"):
                    critical_issues.append(vuln)
        
        if security.get("sql_injection_risks"):
            for risk in security["sql_injection_risks"]:
                risk["category"] = "security"
                all_issues.append(risk)
                critical_issues.append(risk)
        
        if security.get("xss_risks"):
            for risk in security["xss_risks"]:
                risk["category"] = "security"
                all_issues.append(risk)
                warnings.append(risk)
        
        if security.get("other_risks"):
            for risk in security["other_risks"]:
                risk["category"] = "security"
                all_issues.append(risk)
                if risk.get("severity") == "critical":
                    critical_issues.append(risk)
                else:
                    warnings.append(risk)
        
        # 从规范检查中提取问题
        if lint.get("style_violations"):
            for v in lint["style_violations"]:
                v["category"] = "style"
                all_issues.append(v)
        
        if lint.get("naming_issues"):
            for issue in lint["naming_issues"]:
                issue["category"] = "naming"
                all_issues.append(issue)
                if issue.get("severity") == "warning":
                    warnings.append(issue)
        
        if lint.get("error_handling_issues"):
            for issue in lint["error_handling_issues"]:
                issue["category"] = "error_handling"
                all_issues.append(issue)
                warnings.append(issue)
        
        if lint.get("best_practices"):
            for bp in lint["best_practices"]:
                bp["category"] = "best_practice"
                suggestions.append(bp.get("message", ""))
        
        # 添加lint建议
        if lint.get("suggestion"):
            suggestions.append(lint["suggestion"])
        
        # 计算质量评分
        quality_score = self._calculate_quality_score(
            analysis, security, lint, critical_issues, warnings
        )
        
        # 计算置信度
        confidence = self._calculate_confidence(state)
        
        # 生成摘要
        summary = self._generate_summary(
            analysis, security, lint, critical_issues, warnings
        )
        
        # 去重建议
        suggestions = list(dict.fromkeys(suggestions))
        
        return {
            "summary": summary,
            "all_issues": all_issues,
            "critical_issues": critical_issues,
            "warnings": warnings,
            "suggestions": suggestions,
            "quality_score": quality_score,
            "confidence": confidence
        }
    
    def _calculate_quality_score(
        self,
        analysis: dict,
        security: dict,
        lint: dict,
        critical_issues: list,
        warnings: list
    ) -> float:
        """计算代码质量评分 (0-10)"""
        score = 10.0
        
        # 严重问题扣分
        critical_count = len(critical_issues)
        warning_count = len(warnings)
        
        score -= critical_count * 2.0  # 每个严重问题扣2分
        score -= warning_count * 0.3    # 每个警告扣0.3分
        
        # 复杂度扣分
        complexity = analysis.get("complexity_score", 0)
        if complexity > 5:
            score -= (complexity - 5) * 0.5
        
        # 安全问题扣分
        severity_counts = security.get("severity_counts", {})
        score -= severity_counts.get("critical", 0) * 3.0
        score -= severity_counts.get("high", 0) * 1.5
        score -= severity_counts.get("medium", 0) * 0.5
        
        # 规范问题扣分
        style_count = len(lint.get("style_violations", []))
        naming_count = len(lint.get("naming_issues", []))
        score -= style_count * 0.05
        score -= naming_count * 0.1
        
        return max(0.0, min(10.0, round(score, 2)))
    
    def _calculate_confidence(self, state: SharedState) -> float:
        """计算报告置信度"""
        confidence = 1.0
        
        # Agent执行时间过短可能是API调用失败
        timestamps = state.get("agent_timestamps", {})
        for agent, times in timestamps.items():
            duration = times.get("duration", 0)
            if duration < 0.5:  # 少于500ms
                confidence -= 0.1
        
        # 有错误时降低置信度
        errors = state.get("agent_errors", {})
        if errors:
            confidence -= len(errors) * 0.15
        
        # 原始代码过短
        code_len = len(state.get("original_code", ""))
        if code_len < 50:
            confidence -= 0.3
        
        # 重试次数过多
        reflection_count = state.get("reflection_count", 0)
        if reflection_count > 2:
            confidence -= 0.1 * (reflection_count - 2)
        
        return max(0.0, min(1.0, round(confidence, 2)))
    
    def _generate_summary(
        self,
        analysis: dict,
        security: dict,
        lint: dict,
        critical_issues: list,
        warnings: list
    ) -> str:
        """生成审查摘要"""
        lines = []
        
        # 代码基本信息
        structure = analysis.get("code_structure", {})
        if structure:
            lines.append(f"代码包含 {structure.get('functions', []).__len__()} 个函数，"
                        f"{structure.get('classes', []).__len__()} 个类，"
                        f"共 {structure.get('total_lines', 0)} 行代码。")
        
        # 安全状况
        severity_counts = security.get("severity_counts", {})
        vuln_count = len(security.get("vulnerabilities", []))
        sql_count = len(security.get("sql_injection_risks", []))
        xss_count = len(security.get("xss_risks", []))
        
        if vuln_count > 0 or sql_count > 0 or xss_count > 0:
            critical = severity_counts.get("critical", 0)
            high = severity_counts.get("high", 0)
            lines.append(f"安全扫描发现 {vuln_count + sql_count + xss_count} 个问题，"
                        f"其中 {critical + high} 个为高危。")
        else:
            lines.append("安全扫描未发现问题。")
        
        # 规范状况
        style_count = len(lint.get("style_violations", []))
        naming_count = len(lint.get("naming_issues", []))
        error_count = len(lint.get("error_handling_issues", []))
        
        if style_count + naming_count + error_count > 0:
            lines.append(f"规范检查发现 {style_count} 个风格问题，"
                        f"{naming_count} 个命名问题，"
                        f"{error_count} 个异常处理问题。")
        else:
            lines.append("规范检查通过。")
        
        # 总体评价
        if critical_issues:
            lines.append("存在严重安全隐患，建议优先修复。")
        elif warnings:
            lines.append("存在一些可改进之处，建议适当优化。")
        else:
            lines.append("代码质量良好。")
        
        return " ".join(lines)
