"""
Multi-Agent Code Reviewer
多智能体协作任务编排系统 - 智能代码审查助手

基于LangGraph状态机进行Agent编排：
Analyzer → Security → Linter → Reviewer → Reflection

核心特性:
- 状态机编排：支持条件分支、循环、并行
- 共享State：Agent间通过共享状态通信
- MCP协议：标准化的工具调用
- 记忆管理：短期(滑动窗口) + 长期(向量存储)
- 自反思：质量不达标自动重试
- 降级容错：超时中断 + 结果兜底
- 全链路追踪：输入输出、耗时、Token消耗
"""

from core.orchestrator import get_orchestrator
from core.state import ReviewState
import asyncio


async def demo():
    """演示代码审查流程"""
    print("=" * 60)
    print("Multi-Agent Code Reviewer Demo")
    print("=" * 60)
    
    # 示例代码
    sample_code = '''
import os
import sqlite3

def get_user_data(user_id):
    """获取用户数据"""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    
    result = cursor.fetchone()
    conn.close()
    
    return result

def render_profile(username, request_data):
    """渲染用户资料"""
    html = f"<h1>{username}</h1><p>{request_data}</p>"
    return html

api_key = "sk-1234567890abcdef"
password = "admin123"
'''

    print("\n[CODE] 原始代码:")
    print("-" * 40)
    print(sample_code[:500] + "..." if len(sample_code) > 500 else sample_code)
    print("-" * 40)
    
    # 创建编排器
    orchestrator = get_orchestrator()
    
    print("\n[START] 开始审查...")
    print("状态: Analyzer -> Security -> Linter -> Reviewer -> Reflection")
    print()
    
    # 执行审查
    result = await orchestrator.execute(
        code=sample_code,
        task_id="demo_task",
        language="python"
    )
    
    # 打印结果
    print("\n" + "=" * 60)
    print("审查结果")
    print("=" * 60)
    
    print(f"\n最终状态: {result.get('status')}")
    
    # 分析结果
    if result.get("analysis_result"):
        ar = result["analysis_result"]
        print(f"\n[ANALYSIS] 代码分析:")
        print(f"   - 复杂度评分: {ar.get('complexity_score', 0):.2f}")
        print(f"   - 函数数量: {len(ar.get('key_functions', []))}")
        print(f"   - 依赖: {', '.join(ar.get('dependencies', [])[:5])}")
    
    # 安全结果
    if result.get("security_result"):
        sr = result["security_result"]
        vuln_count = len(sr.get("vulnerabilities", []))
        sql_count = len(sr.get("sql_injection_risks", []))
        xss_count = len(sr.get("xss_risks", []))
        
        print(f"\n[SECURITY] 安全扫描:")
        print(f"   - SQL注入风险: {sql_count}")
        print(f"   - XSS风险: {xss_count}")
        print(f"   - 其他漏洞: {vuln_count}")
        
        if sql_count > 0:
            print(f"\n   [WARN] SQL注入详情:")
            for risk in sr.get("sql_injection_risks", [])[:2]:
                print(f"      - 第{risk.get('line')}行: {risk.get('description')}")
    
    # 规范结果
    if result.get("lint_result"):
        lr = result["lint_result"]
        style_count = len(lr.get("style_violations", []))
        naming_count = len(lr.get("naming_issues", []))
        
        print(f"\n[LINT] 规范检查:")
        print(f"   - 风格问题: {style_count}")
        print(f"   - 命名问题: {naming_count}")
    
    # 最终报告
    if result.get("review_report"):
        rr = result["review_report"]
        print(f"\n[REPORT] 最终报告:")
        print(f"   - 质量评分: {rr.get('quality_score', 0):.2f}/10")
        print(f"   - 置信度: {rr.get('confidence', 0):.2%}")
        print(f"   - 严重问题: {len(rr.get('critical_issues', []))}")
        print(f"   - 警告: {len(rr.get('warnings', []))}")
        print(f"\n   摘要: {rr.get('summary', '')}")
    
    # 可观测性
    if result.get("agent_timestamps"):
        print(f"\n[TIMING] 执行时间:")
        for agent, times in result["agent_timestamps"].items():
            duration = times.get("duration", 0)
            print(f"   - {agent}: {duration:.2f}s")
    
    print("\n" + "=" * 60)
    print("演示完成!")
    print("=" * 60)


def main():
    """主入口"""
    try:
        asyncio.run(demo())
    except KeyboardInterrupt:
        print("\n\n演示被用户中断")
    except Exception as e:
        print(f"\n\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
