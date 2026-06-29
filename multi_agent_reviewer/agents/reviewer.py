"""总结Agent - 规则汇总 + Qwen LLM 报告生成"""
from agents.base import BaseAgent
from core.state import SharedState, AgentType, ReviewState
from config.settings import settings


class ReviewerAgent(BaseAgent):
    """总结Agent - 汇总各Agent结果，由 Qwen 生成专业审查报告"""

    def __init__(self):
        super().__init__(AgentType.REVIEWER, model=settings.reviewer_model)

    def process(self, state: SharedState) -> dict:
        self.log_start(state)
        state["current_agent"] = self.name
        state["status"] = ReviewState.REVIEWING

        try:
            # 1. 规则生成报告
            rule_report = self._generate_report(state)

            # 2. Qwen 增强报告
            llm_report = self._llm_report(state)

            # 合并
            merged = self._merge_reports(rule_report, llm_report)

            message = self.create_message(
                AgentType.ORCHESTRATOR,
                f"审查报告生成完成: 质量评分 {merged['quality_score']:.2f}, "
                f"置信度 {merged['confidence']:.2f}",
                {"report": merged},
            )
            self.log_end(state)
            return {"review_report": merged, "messages": [message]}
        except Exception as e:
            self.add_error(state, str(e))
            self.log_end(state)
            return {"agent_errors": state["agent_errors"]}

    def _llm_report(self, state: SharedState) -> dict:
        """使用 Qwen 生成全面审查报告"""
        analysis = state.get("analysis_result") or {}
        security = state.get("security_result") or {}
        lint = state.get("lint_result") or {}

        context = (
            f"=== 分析结果 ===\n复杂度: {analysis.get('complexity_score', 'N/A')}\n"
            f"函数: {analysis.get('code_structure', {}).get('functions', [])}\n"
            f"依赖: {analysis.get('dependencies', [])}\n\n"
            f"=== 安全扫描 ===\n漏洞数: {len(security.get('vulnerabilities', []))}\n"
            f"统计: {security.get('severity_counts', {})}\n\n"
            f"=== 规范检查 ===\n风格问题: {len(lint.get('style_violations', []))}\n"
            f"命名问题: {len(lint.get('naming_issues', []))}"
        )

        system_prompt = (
            "你是一位资深代码审查专家。基于以下各Agent的分析结果，生成最终审查报告，输出 JSON，包含：\n"
            "- summary：综合摘要（中文，一段话）\n"
            "- quality_score (0-10)：质量评分\n"
            "- confidence (0-1)：置信度\n"
            "- critical_issues：最严重的 3-5 个问题列表 [{\"description\", \"priority\"}]\n"
            "- suggestions：改进建议列表\n"
            "仅输出 JSON，不要额外文字。"
        )
        user_prompt = context

        try:
            return self.llm.chat_json(
                self.build_prompt(system_prompt, user_prompt),
                temperature=0.3,
            )
        except Exception as e:
            print(f"[Qwen] 报告生成失败: {e}")
            return {}

    def _merge_reports(self, rule: dict, llm: dict) -> dict:
        if llm.get("summary"):
            rule["summary"] = llm["summary"]
        if llm.get("quality_score"):
            rule["quality_score"] = (rule["quality_score"] + llm["quality_score"]) / 2
        if llm.get("confidence"):
            rule["confidence"] = (rule["confidence"] + llm["confidence"]) / 2
        if llm.get("suggestions"):
            for s in llm["suggestions"]:
                if s not in rule["suggestions"]:
                    rule["suggestions"].append(s)
        return rule

    # ===== 规则报告逻辑 =====

    def _generate_report(self, state: SharedState) -> dict:
        analysis = state.get("analysis_result") or {}
        security = state.get("security_result") or {}
        lint = state.get("lint_result") or {}

        all_issues = []
        critical_issues = []
        warnings = []
        suggestions = []

        for issue in analysis.get("issues", []):
            issue["category"] = "analysis"
            all_issues.append(issue)
            if issue.get("severity") == "warning":
                warnings.append(issue)

        for vuln in security.get("vulnerabilities", []):
            vuln["category"] = "security"
            all_issues.append(vuln)
            if vuln.get("severity") in ("critical", "high"):
                critical_issues.append(vuln)

        for risk in security.get("sql_injection_risks", []):
            risk["category"] = "security"
            all_issues.append(risk)
            critical_issues.append(risk)

        for v in lint.get("style_violations", []):
            v["category"] = "style"
            all_issues.append(v)
        for issue in lint.get("naming_issues", []):
            issue["category"] = "naming"
            all_issues.append(issue)
        for bp in lint.get("best_practices", []):
            suggestions.append(bp.get("message", ""))
        if lint.get("suggestion"):
            suggestions.append(lint["suggestion"])

        return {
            "summary": self._generate_summary(analysis, security, lint, critical_issues, warnings),
            "all_issues": all_issues,
            "critical_issues": critical_issues,
            "warnings": warnings,
            "suggestions": list(dict.fromkeys(suggestions)),
            "quality_score": self._calculate_quality_score(analysis, security, lint, critical_issues, warnings),
            "confidence": self._calculate_confidence(state),
        }

    def _calculate_quality_score(self, analysis, security, lint, critical_issues, warnings):
        score = 10.0
        score -= len(critical_issues) * 2.0
        score -= len(warnings) * 0.3
        complexity = analysis.get("complexity_score", 0)
        if complexity > 5:
            score -= (complexity - 5) * 0.5
        sev = security.get("severity_counts", {})
        score -= sev.get("critical", 0) * 3.0
        score -= sev.get("high", 0) * 1.5
        score -= sev.get("medium", 0) * 0.5
        score -= len(lint.get("style_violations", [])) * 0.05
        score -= len(lint.get("naming_issues", [])) * 0.1
        return max(0.0, min(10.0, round(score, 2)))

    def _calculate_confidence(self, state):
        confidence = 1.0
        timestamps = state.get("agent_timestamps", {})
        for agent, times in timestamps.items():
            if times.get("duration", 0) < 0.5:
                confidence -= 0.1
        errors = state.get("agent_errors", {})
        if errors:
            confidence -= len(errors) * 0.15
        if len(state.get("original_code", "")) < 50:
            confidence -= 0.3
        ref_count = state.get("reflection_count", 0)
        if ref_count > 2:
            confidence -= 0.1 * (ref_count - 2)
        return max(0.0, min(1.0, round(confidence, 2)))

    def _generate_summary(self, analysis, security, lint, critical_issues, warnings):
        lines = []
        structure = analysis.get("code_structure", {})
        if structure:
            lines.append(f"代码包含 {len(structure.get('functions', []))} 个函数，"
                        f"{len(structure.get('classes', []))} 个类，"
                        f"共 {structure.get('total_lines', 0)} 行代码。")
        sev = security.get("severity_counts", {})
        total_vuln = sum(sev.values())
        if total_vuln > 0:
            lines.append(f"安全扫描发现 {total_vuln} 个问题。")
        else:
            lines.append("安全扫描未发现问题。")
        if critical_issues:
            lines.append("存在严重安全隐患，建议优先修复。")
        elif warnings:
            lines.append("存在一些可改进之处。")
        else:
            lines.append("代码质量良好。")
        return " ".join(lines)
