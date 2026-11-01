import os
import sys

# 1. إجبار نظام بايثون على قراءة المجلد الحالي والمجلد الأب لحل مسارات الاستيراد
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

PARENT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import streamlit as st
import asyncio
import threading
import base64
from queue import Queue

from deeptutor.app import DeepTutorApp
from deeptutor.core.turn_request import TurnRequest, OutgoingAttachment

st.set_page_config(page_title="DeepTutor - المدرس الذكي", page_icon="🎓", layout="wide")

st.title("🎓 DeepTutor - محرك التدريس الذكي")
st.caption("يعمل بمحرك DeepTutor الأصلي مع القدرات التوليدية المتعددة (Agentic Multi-Capabilities)")

# 2. حلقة أحداث خلفية وتهيئة صريحة لإعدادات النموذج في DeepTutor
@st.cache_resource
def get_background_engine():
    """تنشيط حلقة أحداث خلفية وتكوين النموذج والنموذج الفعال برمجياً"""
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
        app = DeepTutorApp()
        
        # جلب المفاتيح من Streamlit Secrets أو بيئة النظام
        gemini_key = ""
        openai_key = ""
        try:
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass
        gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY", "")

        try:
            openai_key = st.secrets.get("OPENAI_API_KEY", "")
        except Exception:
            pass
        openai_key = openai_key or os.environ.get("OPENAI_API_KEY", "")

        # اختيار المزود والنموذج الافتراضي
        if gemini_key:
            provider = "gemini"
            model_name = "gemini-1.5-flash"
            active_key = gemini_key
            os.environ["GEMINI_API_KEY"] = gemini_key
        elif openai_key:
            provider = "openai"
            model_name = "gpt-4o-mini"
            active_key = openai_key
            os.environ["OPENAI_API_KEY"] = openai_key
        else:
            provider = "gemini"
            model_name = "gemini-1.5-flash"
            active_key = "DEMO_KEY"

        # تسجيل النموذج والمزود صراحة في خدمة إعدادات DeepTutor
        try:
            settings_svc = app.container.settings()
            
            # بناء هيكل الإعدادات المطلوبة
            config_data = {
                "active_model": model_name,
                "active_provider": provider,
                "providers": {
                    provider: {
                        "api_key": active_key,
                        "enabled": True,
                        "default_model": model_name
                    }
                }
            }
            
            if hasattr(settings_svc, "update_settings"):
                await settings_svc.update_settings(config_data)
        except Exception as err:
            print(f"[DeepTutor Settings Init Error]: {err}")

        return app

    future = asyncio.run_coroutine_threadsafe(_init(), loop)
    app = future.result()
    return loop, app

# تشغيل المحرك
loop, app = get_background_engine()

# 3. القائمة الجانبية (Sidebar)
with st.sidebar:
    st.header("⚙️ إعدادات DeepTutor")
    
    # إمكانية إدخال المفتاح يدويًا إذا لم يكن مضبوطاً في Secrets
    user_key = st.text_input("مفتاح API (Gemini / OpenAI):", type="password")
    if user_key:
        os.environ["GEMINI_API_KEY"] = user_key
        os.environ["OPENAI_API_KEY"] = user_key
    
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
    uploaded_file = st.file_uploader("ارفع كتاباً أو ملفاً (PDF/TXT/MD):", type=["pdf", "txt", "md"])

    st.markdown("---")
    if st.button("🔄 إعادة ضبط الجلسة والمحرك"):
        st.cache_resource.clear()
        st.session_state.session_id = None
        st.session_state.messages = []
        st.rerun()

# 4. إدارة حالة الجلسة
if "session_id" not in st.session_state:
    st.session_state.session_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 5. معالجة الرسائل
if prompt := st.chat_input("اكتب سؤالك أو الدرس الذي تريد شرحه..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

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
                
                try:
                    store = app.turns.store_provider.get()
                    db_msgs = await store.get_messages(session["id"])
                    for m in reversed(db_msgs):
                        if m.get("role") == "assistant" and m.get("content"):
                            q.put(("db_assistant_message", m["content"]))
                            break
                except Exception:
                    pass

            except Exception as e:
                q.put(("error", str(e)))
            finally:
                q.put(("done", None))

        asyncio.run_coroutine_threadsafe(_run_turn_coro(turn_req, event_queue), loop)

        full_response = []
        error_occurred = None

        while True:
            msg_type, data = event_queue.get()
            if msg_type == "session_id":
                st.session_state.session_id = data
            elif msg_type == "db_assistant_message":
                if not full_response and data:
                    full_response.append(data)
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
                        status_box.write(f"💭 **تفكير المحرك:** {thinking_text}")
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
            st.error(f"خطأ أثناء تشغيل محرك DeepTutor: {error_occurred}")
        elif not full_response:
            status_box.update(label="⚠️ لم يتم استلام نص للإجابة", state="error", expanded=True)
            st.warning("انتهت المعالجة دون إرجاع نص، يُرجى المحاولة مرة أخرى.")
        else:
            status_box.update(label="✅ تم اكتمال الإجابة بنجاح!", state="complete", expanded=False)
            final_text = "".join(full_response).strip()
            response_placeholder.markdown(final_text)
            st.session_state.messages.append({"role": "assistant", "content": final_text})
