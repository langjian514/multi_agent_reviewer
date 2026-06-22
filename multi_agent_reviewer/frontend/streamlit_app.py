"""Streamlit前端 - 实时展示Agent协作过程"""
import streamlit as st
import asyncio
import websocket
import json
import time
from datetime import datetime

# 配置页面
st.set_page_config(
    page_title="Multi-Agent Code Reviewer",
    page_icon="🔍",
    layout="wide"
)


def init_session_state():
    """初始化会话状态"""
    if "task_id" not in st.session_state:
        st.session_state.task_id = None
    if "review_status" not in st.session_state:
        st.session_state.review_status = "idle"
    if "review_result" not in st.session_state:
        st.session_state.review_result = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "ws_connected" not in st.session_state:
        st.session_state.ws_connected = False


def create_websocket_client():
    """创建WebSocket客户端"""
    try:
        ws = websocket.WebSocketApp(
            f"ws://localhost:8000/ws/{st.session_state.task_id or 'client'}",
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        return ws
    except Exception as e:
        st.error(f"WebSocket连接失败: {e}")
        return None


def on_message(ws, message):
    """消息处理"""
    try:
        data = json.loads(message)
        
        if data["type"] == "task_started":
            st.session_state.review_status = "started"
            st.session_state.task_id = data["data"]["task_id"]
        
        elif data["type"] == "status_update":
            st.session_state.review_status = data["data"]["status"]
        
        elif data["type"] == "review_completed":
            st.session_state.review_status = "completed"
            st.session_state.review_result = data["data"]
        
        elif data["type"] == "error":
            st.session_state.review_status = "error"
            st.error(f"错误: {data['data']['error']}")
        
        elif data["type"] == "subscribed":
            st.session_state.ws_connected = True
        
        elif data["type"] == "pong":
            pass  # 心跳响应
        
        st.experimental_rerun()
    
    except Exception as e:
        print(f"消息处理错误: {e}")


def on_error(ws, error):
    """错误处理"""
    st.session_state.ws_connected = False
    print(f"WebSocket错误: {error}")


def on_close(ws):
    """连接关闭"""
    st.session_state.ws_connected = False


def on_open(ws):
    """连接打开"""
    st.session_state.ws_connected = True
    # 发送订阅消息
    if st.session_state.task_id:
        ws.send(json.dumps({
            "type": "subscribe",
            "task_id": st.session_state.task_id
        }))


def display_agents_panel():
    """显示Agent状态面板"""
    st.subheader("Agent 协作状态")
    
    agents = {
        "Analyzer": {"icon": "📊", "states": ["idle", "analyzing", "completed"]},
        "Security": {"icon": "🔒", "states": ["idle", "security_scanning", "completed"]},
        "Linter": {"icon": "📏", "states": ["idle", "linting", "completed"]},
        "Reviewer": {"icon": "📝", "states": ["idle", "reviewing", "completed"]},
        "Reflection": {"icon": "🤔", "states": ["idle", "reflecting", "completed"]}
    }
    
    cols = st.columns(len(agents))
    
    for i, (name, info) in enumerate(agents.items()):
        with cols[i]:
            status = "idle"
            
            if name.lower() == st.session_state.review_status:
                status = "active"
            elif "completed" in st.session_state.review_status:
                status = "completed"
            
            icon = info["icon"]
            
            if status == "active":
                st.markdown(f"""
                <div style="text-align: center; padding: 10px; border-radius: 10px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
                    <div style="font-size: 2em;">{icon}</div>
                    <div>{name}</div>
                    <div style="font-size: 0.8em;">🔄 运行中</div>
                </div>
                """, unsafe_allow_html=True)
            elif status == "completed":
                st.markdown(f"""
                <div style="text-align: center; padding: 10px; border-radius: 10px; background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white;">
                    <div style="font-size: 2em;">{icon}</div>
                    <div>{name}</div>
                    <div style="font-size: 0.8em;">✅ 完成</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="text-align: center; padding: 10px; border-radius: 10px; border: 1px solid #ddd;">
                    <div style="font-size: 2em; opacity: 0.3;">{icon}</div>
                    <div>{name}</div>
                    <div style="font-size: 0.8em; opacity: 0.5;">⏸️ 等待</div>
                </div>
                """, unsafe_allow_html=True)


def display_code_input():
    """显示代码输入区域"""
    st.subheader("代码输入")
    
    code = st.text_area(
        "粘贴要审查的代码",
        height=300,
        placeholder="在这里粘贴您的Python代码..."
    )
    
    col1, col2 = st.columns([1, 4])
    
    with col1:
        language = st.selectbox("语言", ["python", "javascript", "java", "go", "rust"])
    
    with col2:
        submitted = st.button("🚀 开始审查", type="primary", use_container_width=True)
    
    return code, language, submitted


def display_results(result):
    """显示审查结果"""
    if not result:
        return
    
    st.subheader("审查结果")
    
    # 质量评分
    quality_score = result.get("quality_score", 0)
    confidence = result.get("confidence", 0)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("质量评分", f"{quality_score:.2f}/10", 
                  delta="优秀" if quality_score >= 8 else "良好" if quality_score >= 6 else "需改进")
    
    with col2:
        st.metric("置信度", f"{confidence:.2%}")
    
    # 详细结果（简化展示）
    st.markdown("---")
    st.markdown("### 详细报告")
    
    st.info("详细报告功能正在开发中...")
    
    # TODO: 实现完整的报告展示
    # - 关键问题列表
    # - 安全漏洞
    # - 规范问题
    # - 改进建议


def main():
    """主函数"""
    init_session_state()
    
    st.title("🔍 Multi-Agent Code Reviewer")
    st.markdown("*基于多智能体协作的智能代码审查系统*")
    
    # 左侧：输入区域
    with st.container():
        code, language, submitted = display_code_input()
    
    # Agent状态
    with st.container():
        display_agents_panel()
    
    # 审查状态
    if st.session_state.review_status != "idle" and st.session_state.review_status != "completed":
        with st.container():
            st.info(f"🔄 审查进行中: {st.session_state.review_status}")
            
            # 动态进度条
            progress_bar = st.progress(0)
            for i in range(100):
                time.sleep(0.1)
                progress_bar.progress(i + 1)
    
    # 结果展示
    if st.session_state.review_result:
        with st.container():
            display_results(st.session_state.review_result)
    
    # 底部信息
    st.markdown("---")
    st.markdown(
        """
        <div style="text-align: center; color: gray;">
            <p>Multi-Agent Code Reviewer | 基于LangGraph状态机编排</p>
            <p>支持: Analyzer → Security → Linter → Reviewer → Reflection</p>
        </div>
        """,
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
