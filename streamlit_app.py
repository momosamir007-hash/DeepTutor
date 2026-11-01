import streamlit as st
import asyncio
import threading
import base64
import os
import sys
from queue import Queue

# التأكد من مسار المشروع
sys.path.insert(0, os.path.abspath("."))

from deeptutor.app import DeepTutorApp
from deeptutor.core.turn_request import TurnRequest, OutgoingAttachment

st.set_page_config(page_title="DeepTutor - المدرس الذكي", page_icon="🎓", layout="wide")

st.title("🎓 DeepTutor - محرك التدريس الذكي")
st.caption("يعمل بمحرك DeepTutor الأصلي والقدرات التوليدية المتعددة (Multi-Stage Agentic Capabilities)")

# 1. إنشاء حلقة أحداث مستمرة (Persistent Event Loop) لتفادي خطأ Event Loop
@st.cache_resource
def get_background_engine():
    """حلقة أحداث مخصصة تعمل في خلفية التطبيق لمنع تعارض الأقفال (Asyncio Locks)"""
    # تنظيف أي أقفال أو حاويات قديمة من جلسات سابقة
    try:
        import deeptutor.app.container as app_container
        import deeptutor.services.session.sqlite_store as sqlite_store
        app_container._default_container = None
        sqlite_store._instances.clear()
    except Exception:
        pass

    loop = asyncio.new_event_loop()
    
    def _run_worker(l):
        asyncio.set_event_loop(l)
        l.run_forever()

    thread = threading.Thread(target=_run_worker, args=(loop,), daemon=True)
    thread.start()

    async def _init():
        return DeepTutorApp()

    future = asyncio.run_coroutine_threadsafe(_init(), loop)
    app = future.result()
    return loop, app

# جلب الحلقة والمحرك
loop, app = get_background_engine()

# 2. القائمة الجانبية (Sidebar)
with st.sidebar:
    st.header("⚙️ قدرات DeepTutor الأصلية")
    
    capability_options = {
        "chat": "💬 محادثة وتدريس تفاعلي (Chat)",
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
    
    persona_options = {
        "teacher": "👨‍🏫 المعلم (Teacher) - صبور ومنظم",
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

    st.markdown("---")
    if st.button("🔄 إعادة ضبط الجلسة والمحرك"):
        st.cache_resource.clear()
        st.session_state.session_id = None
        st.session_state.messages = []
        st.rerun()

# 3. إدارة الجلسة في Streamlit
if "session_id" not in st.session_state:
    st.session_state.session_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []

# عرض سجل الرسائل السابقة
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 4. معالجة رسالة الطالب
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

    # بناء طلب الجلسة الأصلي TurnRequest
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
        
        # طابور آمن لتبادل الأحداث بين ثريد البايثون وثريد Streamlit
        event_queue = Queue()

        async def _run_turn_coro(req, q):
            try:
                try:
                    session, turn = await app.start_turn(req)
                except Exception as ex:
                    if "not found in this workspace" in str(ex):
                        req.session_id = None
                        session, turn = await app.start_turn(req)
                    else:
                        raise ex
                q.put(("session_id", session["id"]))
                async for event in app.stream_turn(turn["id"]):
                    q.put(("event", event))
            except Exception as e:
                q.put(("error", str(e)))
            finally:
                q.put(("done", None))

        # إرسال الكوروتين إلى الحلقة المستمرة بأمان
        asyncio.run_coroutine_threadsafe(_run_turn_coro(turn_req, event_queue), loop)

        full_response = []
        error_occurred = None

        while True:
            msg_type, data = event_queue.get()
            if msg_type == "session_id":
                st.session_state.session_id = data
            elif msg_type == "event":
                e_type = data.get("type")
                if e_type == "content":
                    chunk = data.get("content", "")
                    if chunk:
                        full_response.append(chunk)
                        response_placeholder.markdown("".join(full_response) + "▌")
                elif e_type == "result":
                    meta = data.get("metadata", {})
                    resp_val = meta.get("response") or meta.get("answer") or data.get("content", "")
                    if resp_val and not full_response:
                        full_response.append(resp_val)
                elif e_type == "thinking":
                    thinking_text = data.get("thinking", "")
                    if thinking_text:
                        status_box.write(f"💭 **تفكير:** {thinking_text}")
                elif e_type == "tool_call":
                    tool_name = data.get("name", "")
                    status_box.write(f"🔧 **استخدام أداة:** `{tool_name}`")
                elif e_type == "progress":
                    prog_content = data.get("content", "")
                    if prog_content:
                        status_box.write(f"⏳ **المرحلة:** {prog_content}")
                elif e_type == "error":
                    err_msg = data.get("content") or data.get("message") or str(data)
                    error_occurred = err_msg
                    break
            elif msg_type == "error":
                error_occurred = data
                break
            elif msg_type == "done":
                break

        if error_occurred:
            status_box.update(label="❌ حدث خطأ أثناء المعالجة", state="error", expanded=True)
            if "503" in str(error_occurred):
                st.error("⚠️ خوادم النموذج تواجه ضغطاً مؤقتاً (503 High Demand). يرجى إرسال الرسالة مرة أخرى.")
            elif "429" in str(error_occurred):
                st.error("⚠️ تم تجاوز الحصة اللحظية لمفتاح API (Rate Limit 429). انتظر بضع ثوانٍ وأعد المحاولة.")
            else:
                st.error(f"خطأ أثناء تشغيل محرك DeepTutor: {error_occurred}")
        elif not full_response:
            status_box.update(label="⚠️ لم يتم استلام نص للإجابة", state="error", expanded=True)
            st.warning("انتهت المعالجة لكن لم يُرجع النموذج أي نص. يُرجى إعادة إرسال السؤال.")
        else:
            status_box.update(label="✅ تم اكتمال الإجابة بنجاح!", state="complete", expanded=False)
            final_text = "".join(full_response).strip()
            response_placeholder.markdown(final_text)
            st.session_state.messages.append({"role": "assistant", "content": final_text})
