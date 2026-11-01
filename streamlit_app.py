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

# 2. إدخال مفتاح Gemini قبل إنشاء المحرك حتى يكون متاحاً أثناء التهيئة
try:
    configured_gemini_key = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    configured_gemini_key = ""

with st.sidebar:
    st.header("⚙️ إعدادات Gemini")
    gemini_key_input = st.text_input(
        "مفتاح Gemini API:",
        value=os.environ.get("GEMINI_API_KEY", "") or configured_gemini_key,
        type="password",
        help="يمكن أيضاً وضعه في Streamlit Secrets باسم GEMINI_API_KEY."
    )

if gemini_key_input:
    os.environ["GEMINI_API_KEY"] = gemini_key_input

# 3. حلقة أحداث خلفية وتهيئة سجل النماذج الأصلي في DeepTutor
def _configure_gemini_catalog(api_key: str):
    """Create/select an active Gemini LLM profile using DeepTutor's own catalog schema."""
    if not api_key:
        raise RuntimeError(
            "أدخل مفتاح Gemini API في الشريط الجانبي أو عرّف GEMINI_API_KEY."
        )

    from uuid import uuid4
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    catalog_service = get_model_catalog_service()
    catalog = catalog_service.load()
    services = catalog.setdefault("services", {})
    llm_service = services.setdefault(
        "llm", {"active_profile_id": None, "active_model_id": None, "profiles": []}
    )
    profiles = llm_service.setdefault("profiles", [])

    # Prefer an existing Gemini profile; otherwise create one without deleting
    # any profiles or models already configured by the user.
    profile = next(
        (
            p for p in profiles
            if isinstance(p, dict)
            and str(p.get("binding", "")).lower() == "gemini"
            and not p.get("provider_only")
        ),
        None,
    )
    if profile is None:
        profile = {
            "id": f"streamlit-gemini-{uuid4().hex[:10]}",
            "name": "Gemini (Streamlit)",
            "binding": "gemini",
            "provider": "gemini",
            "api_key": api_key,
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "models": [],
        }
        profiles.append(profile)
    else:
        profile["binding"] = "gemini"
        profile["provider"] = "gemini"
        profile["api_key"] = api_key
        profile["base_url"] = (
            profile.get("base_url")
            or "https://generativelanguage.googleapis.com/v1beta/openai/"
        )

    models = profile.setdefault("models", [])
    model = next(
        (
            m for m in models
            if isinstance(m, dict) and m.get("model") == "gemini-2.5-flash"
        ),
        None,
    )
    if model is None:
        model = {
            "id": f"streamlit-gemini-model-{uuid4().hex[:10]}",
            "name": "Gemini 2.5 Flash",
            "model": "gemini-2.5-flash",
        }
        models.append(model)

    llm_service["active_profile_id"] = profile["id"]
    llm_service["active_model_id"] = model["id"]
    catalog_service.save(catalog)

    # DeepTutor caches the resolved LLM config; clear it after changing catalog.
    from deeptutor.services.llm.config import clear_llm_config_cache
    clear_llm_config_cache()

@st.cache_resource
def get_background_engine(api_key: str):
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
        # Parsing is an optional DeepTutor module. In a source checkout it is
        # already present in the repository; it only needs to be enabled in
        # the official module-selection state before the engine is created.
        from deeptutor.modules.lifecycle import change as change_module
        change_module("enable", "parsing")

        # Configure the official model catalog before DeepTutorApp creates
        # services that resolve the active LLM.
        _configure_gemini_catalog(api_key)
        app = DeepTutorApp()
        return app

    future = asyncio.run_coroutine_threadsafe(_init(), loop)
    app = future.result()
    return loop, app

# تشغيل المحرك بعد إدخال مفتاح Gemini وتهيئة السجل الأصلي
if not gemini_key_input:
    st.info("أدخل مفتاح Gemini API في الشريط الجانبي لتشغيل المحرك.")
    st.stop()

try:
    loop, app = get_background_engine(gemini_key_input)
except Exception as init_error:
    st.error(f"تعذر تهيئة DeepTutor مع Gemini أو تفعيل وحدة parsing: {init_error}")
    st.stop()

# 3. القائمة الجانبية (Sidebar)
with st.sidebar:
    st.header("⚙️ إعدادات DeepTutor")
    
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
