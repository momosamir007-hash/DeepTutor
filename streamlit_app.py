import streamlit as st
import asyncio
import base64
import os
import sys

# التأكد من مسار المشروع
sys.path.insert(0, os.path.abspath("."))

from deeptutor.app import DeepTutorApp
from deeptutor.core.turn_request import TurnRequest, OutgoingAttachment

st.set_page_config(page_title="DeepTutor - المدرس الذكي", page_icon="🎓", layout="wide")

st.title("🎓 DeepTutor - محرك التدريس الذكي")
st.caption("يعمل بمحرك DeepTutor الأصلي والقدرات المتعددة (Multi-Stage Agentic Capabilities)")

# 1. القائمة الجانبية (Sidebar) للإعدادات وقدرات DeepTutor الأصلية
with st.sidebar:
    st.header("⚙️ قدرات DeepTutor")
    
    # اختيار القدرة (Capability)
    capability_options = {
        "chat": "💬 محادثة وتدريس عام (Chat)",
        "deep_solve": "🧠 حل مسائل وتفكير عميق (Deep Solve)",
        "deep_question": "❓ توليد أسئلة واختبارات (Quiz / Questions)",
        "deep_research": "🔬 بحث وتفكيك مفاهيم شامل (Deep Research)",
        "visualize": "📊 شرح وتوليد رسوم بيانية (Visualize)"
    }
    selected_cap = st.selectbox(
        "اختر وضعية التعلم (Capability):",
        options=list(capability_options.keys()),
        format_func=lambda x: capability_options[x]
    )
    
    # اختيار شخصية المعلم (Persona)
    persona_options = {
        "teacher": "👨‍🏫 المعلم (Teacher) - صبور وأكاديمي",
        "peer": "🧑‍🎓 الزميل (Peer) - مبسط وودود",
        "research-assistant": "🔬 المساعد البحثي (Research Assistant)"
    }
    selected_persona = st.selectbox(
        "اختر شخصية المعلم (Persona):",
        options=list(persona_options.keys()),
        format_func=lambda x: persona_options[x]
    )

    st.markdown("---")
    st.subheader("📚 المرفقات والكتب")
    uploaded_file = st.file_uploader("ارفع كتاباً أو ملفاً (PDF/TXT):", type=["pdf", "txt", "md"])

# 2. تهيئة جلسة DeepTutor في الذاكرة
if "app" not in st.session_state:
    st.session_state.app = DeepTutorApp()

if "session_id" not in st.session_state:
    st.session_state.session_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []

# عرض سجل الرسائل السابقة
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 3. إرسال الرسالة إلى محرك DeepTutor
if prompt := st.chat_input("اكتب سؤالك أو موضوع الدرس هنا..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # تجهيز المرفقات عبر نظام OutgoingAttachment الأصلي في DeepTutor
    attachments = []
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        mime = uploaded_file.type or "application/pdf"
        attachments.append(
            OutgoingAttachment(
                type="file",
                filename=uploaded_file.name,
                base64=b64,
                mime_type=mime
            )
        )

    # بناء TurnRequest الأصلي الخاص بـ DeepTutor
    turn_req = TurnRequest(
        content=prompt,
        capability=selected_cap,
        persona=selected_persona,
        session_id=st.session_state.session_id,
        attachments=attachments,
        language="ar"
    )

    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        status_box = st.status("🧠 جاري تشغيل قدرات DeepTutor...", expanded=True)
        
        async def execute_turn():
            session, turn = await st.session_state.app.start_turn(turn_req)
            st.session_state.session_id = session["id"]
            
            full_response = []
            async for event in st.session_state.app.stream_turn(turn["id"]):
                event_type = event.get("type")
                
                # التقاط المحتوى المكتوب
                if event_type == "content":
                    chunk = event.get("content", "")
                    full_response.append(chunk)
                    response_placeholder.markdown("".join(full_response) + "▌")
                
                # التقاط تفكير النموذج في الخلفية
                elif event_type == "thinking":
                    thinking_text = event.get("thinking", "")
                    status_box.write(f"💭 **تفكير:** {thinking_text}")
                
                # التقاط استدعاء الأدوات
                elif event_type == "tool_call":
                    tool_name = event.get("name", "")
                    status_box.write(f"🔧 **استخدام أداة:** `{tool_name}`")
                
                elif event_type == "done":
                    break
            
            status_box.update(label="✅ تم اكتمال الإجابة بنجاح!", state="complete", expanded=False)
            final_text = "".join(full_response).strip()
            response_placeholder.markdown(final_text)
            return final_text

        # تشغيل الدورة عبر حلقة الأحداث (Async Loop)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            answer = loop.run_until_complete(execute_turn())
            loop.close()
            st.session_state.messages.append({"role": "assistant", "content": answer})
        except Exception as exc:
            status_box.update(label="❌ حدث خطأ", state="error", expanded=True)
            st.error(f"خطأ أثناء تشغيل محرك DeepTutor: {exc}")

