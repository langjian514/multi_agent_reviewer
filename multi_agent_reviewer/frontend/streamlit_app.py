"""Streamlit前端 - 实时展示Agent协作过程"""
import streamlit as st
import requests
import json
import os
from datetime import datetime

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Multi-Agent Code Reviewer", page_icon="🔍", layout="wide")


def init():
    for k, v in {"task_id": None, "status": "idle", "result": None, "error": None, "start_time": None, "end_time": None}.items():
        if k not in st.session_state:
            st.session_state[k] = v


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s"


def main():
    init()

    st.title("🔍 Multi-Agent Code Reviewer")
    st.markdown("*基于多智能体协作的智能代码审查系统*")

    code = st.text_area("粘贴要审查的代码", height=200, placeholder="在这里粘贴您的Python代码...")
    col1, col2 = st.columns([1, 4])
    with col1:
        language = st.selectbox("语言", ["python", "javascript", "java", "go", "rust"])
    with col2:
        submitted = st.button("🚀 开始审查", type="primary", use_container_width=True)

    # === 顶部计时器 ===
    timer_placeholder = st.empty()

    # === 提交审查 ===
    if submitted and code.strip():
        st.session_state.status = "analyzing"
        st.session_state.task_id = None
        st.session_state.result = None
        st.session_state.error = None
        st.session_state.start_time = datetime.now()
        st.session_state.end_time = None
        try:
            resp = requests.post(f"{BACKEND_URL}/api/review", json={"code": code, "language": language}, timeout=10)
            resp.raise_for_status()
            st.session_state.task_id = resp.json()["task_id"]
        except Exception as e:
            st.session_state.error = f"提交失败: {e}"
            st.session_state.status = "idle"
        st.rerun()

    # === 轮询结果 ===
    if st.session_state.task_id and st.session_state.status not in ("completed", "idle"):
        try:
            resp = requests.get(f"{BACKEND_URL}/api/review/{st.session_state.task_id}", timeout=5)
            if resp.ok:
                data = resp.json()
                if data.get("status") == "completed":
                    report_resp = requests.get(f"{BACKEND_URL}/api/review/{st.session_state.task_id}/report", timeout=5)
                    if report_resp.ok:
                        st.session_state.result = report_resp.json().get("report", {})
                    st.session_state.end_time = datetime.now()
                    st.session_state.status = "completed"
                    st.rerun()
                elif data.get("status") == "failed":
                    st.session_state.error = "审查执行失败"
                    st.session_state.status = "idle"
                    st.rerun()
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            st.session_state.error = f"查询失败: {e}"
            st.session_state.status = "idle"
            st.rerun()

    # === 计时器显示 ===
    now = datetime.now()
    if st.session_state.start_time and not st.session_state.end_time:
        elapsed = (now - st.session_state.start_time).total_seconds()
        timer_placeholder.markdown(f"### ⏱️ 已运行 **{format_elapsed(elapsed)}**")
    elif st.session_state.start_time and st.session_state.end_time:
        elapsed = (st.session_state.end_time - st.session_state.start_time).total_seconds()
        timer_placeholder.markdown(f"### ✅ 总耗时 **{format_elapsed(elapsed)}**")
    else:
        timer_placeholder.empty()

    # === Agent 状态面板 ===
    status = st.session_state.status
    agents = {"Analyzer": "📊", "Security": "🔒", "Linter": "📏", "Reviewer": "📝", "Reflection": "🤔"}
    cols = st.columns(len(agents))
    for i, (name, icon) in enumerate(agents.items()):
        with cols[i]:
            s = "⏸️ 等待"
            bg = "border:1px solid #334155"
            if status == "completed":
                s = "✅ 完成"
                bg = "background:linear-gradient(135deg,#11998e,#38ef7d);color:white"
            elif status not in ("idle", "completed"):
                s = "🔄 运行中"
                bg = "background:linear-gradient(135deg,#667eea,#764ba2);color:white"
            st.markdown(f'<div style="text-align:center;padding:8px;border-radius:8px;{bg}"><div style="font-size:1.8em;">{icon}</div><div style="font-size:13px">{name}</div><div style="font-size:11px">{s}</div></div>', unsafe_allow_html=True)

    # === 进度提示 ===
    if status not in ("idle", "completed"):
        st.info(f"⏳ 审查进行中... (当前状态: {status})")

    # === 结果显示 ===
    result = st.session_state.result
    if result:
        st.subheader("📋 审查结果")
        col1, col2, col3 = st.columns(3)
        score = result.get("quality_score", 0)
        with col1:
            st.metric("质量评分", f"{score:.2f}/10", delta="优秀" if score >= 8 else "良好" if score >= 6 else "需改进")
        with col2:
            st.metric("置信度", f"{result.get('confidence', 0):.2%}")
        with col3:
            if st.session_state.end_time and st.session_state.start_time:
                total = (st.session_state.end_time - st.session_state.start_time).total_seconds()
                st.metric("总耗时", format_elapsed(total))

        st.markdown("---")
        st.markdown("### 审查摘要")
        st.info(result.get("summary", "无摘要"))

        if result.get("critical_issues"):
            st.markdown("### 🔴 严重问题")
            for issue in result["critical_issues"][:5]:
                st.warning(issue.get("description", issue.get("message", "")))

        if result.get("suggestions"):
            st.markdown("### 💡 改进建议")
            for s in result["suggestions"][:5]:
                st.markdown(f"- {s}")

        # Agent 耗时明细
        if result.get("agent_timings"):
            st.markdown("---")
            st.markdown("### ⏱️ Agent 耗时明细")
            for agent, secs in result["agent_timings"].items():
                st.markdown(f"- **{agent}**: {format_elapsed(secs)}")

    if st.session_state.error:
        st.error(st.session_state.error)

    st.markdown("---")
    st.caption("Multi-Agent Code Reviewer | Analyzer → Security → Linter → Reviewer → Reflection")
    if status not in ("idle", "completed"):
        st.caption("🔄 自动刷新中 (每 3 秒)...")
        st.rerun()


if __name__ == "__main__":
    main()
