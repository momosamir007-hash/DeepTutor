"""Streamlit entry point for DeepTutor with native Gemini catalog configuration."""
from __future__ import annotations

import asyncio
import base64
import os
import sys
import threading
from queue import Queue
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEEPTUTOR_HOME", str(ROOT))

import streamlit as st

st.set_page_config(page_title="DeepTutor - المدرس الذكي", page_icon="🎓", layout="wide")
st.title("🎓 DeepTutor - المدرس الذكي")
st.caption("واجهة Streamlit تستخدم محرك DeepTutor الأصلي وإعدادات Gemini الأصلية.")


def _secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


def configure_gemini(api_key: str, model_name: str) -> str:
    """Persist Gemini as the active LLM using DeepTutor's own model catalog."""
    from deeptutor.services.config import get_model_catalog_service

    catalog_service = get_model_catalog_service()
    catalog = catalog_service.load()
    services = catalog.setdefault("services", {})
    llm_service = services.setdefault(
        "llm", {"active_profile_id": None, "active_model_id": None, "profiles": []}
    )
    profiles = llm_service.setdefault("profiles", [])

    profile_id = "streamlit-gemini-profile"
    model_id = "streamlit-gemini-model"
    profile = next((p for p in profiles if p.get("id") == profile_id), None)
    if profile is None:
        profile = {"id": profile_id, "name": "Gemini (Streamlit)", "models": []}
        profiles.append(profile)

    profile.update(
        {
            "name": "Gemini (Streamlit)",
            "binding": "gemini",
            "api_key": api_key,
            "base_url": "",
            "api_version": "",
            "extra_headers": {},
            "api_format": "auto",
            "wire_api": "auto",
        }
    )
    models = profile.setdefault("models", [])
    model = next((m for m in models if m.get("id") == model_id), None)
    if model is None:
        model = {"id": model_id}
        models.append(model)
    model.update({"id": model_id, "name": model_name, "model": model_name})

    llm_service["active_profile_id"] = profile_id
    llm_service["active_model_id"] = model_id
    catalog_service.save(catalog)
    os.environ["GEMINI_API_KEY"] = api_key
    return str(catalog_service.path)


@st.cache_resource(show_spinner=False)
def get_background_engine(api_key_fingerprint: str):
    """Create one persistent async loop and DeepTutor app for this configured key."""
    # api_key_fingerprint is deliberately only a cache key; the secret itself
    # is read from the environment and is never stored in Streamlit's cache key.
    try:
        import deeptutor.app.container as app_container
        import deeptutor.services.session.sqlite_store as sqlite_store
        app_container._default_container = None
        if hasattr(sqlite_store, "_instances"):
            sqlite_store._instances.clear()
    except Exception:
        pass

    loop = asyncio.new_event_loop()

    def _worker():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_worker, name="deeptutor-async-loop", daemon=True)
    thread.start()

    async def _create_app():
        from deeptutor.app import DeepTutorApp
        return DeepTutorApp()

    future = asyncio.run_coroutine_threadsafe(_create_app(), loop)
    try:
        app = future.result(timeout=90)
    except Exception:
        loop.call_soon_threadsafe(loop.stop)
        raise
    return loop, app


with st.sidebar:
    st.header("⚙️ إعدادات Gemini")
    default_key = _secret("GEMINI_API_KEY")
    gemini_key = st.text_input(
        "مفتاح Gemini API",
        value=default_key,
        type="password",
        help="يمكنك وضع المفتاح في .streamlit/secrets.toml باسم GEMINI_API_KEY أو إدخاله هنا.",
    ).strip()
    model_name = st.selectbox(
        "النموذج",
        ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        index=0,
    )
    st.caption("لا تضع مفتاح API داخل ملفات المشروع أو تشاركه مع الآخرين.")
    st.markdown("---")
    capability_options = {
        "chat": "💬 محادثة وتدريس تفاعلي",
        "deep_solve": "🧠 حل مسائل وتفكير عميق",
        "deep_question": "❓ توليد أسئلة واختبارات",
        "deep_research": "🔬 بحث وتفكيك مفاهيم",
        "visualize": "📊 شرح وتوليد رسوم بيانية",
    }
    selected_cap = st.selectbox(
        "وضعية التعلم", list(capability_options), format_func=lambda x: capability_options[x]
    )
    persona_options = {
        "teacher": "👨‍🏫 المعلم",
        "peer": "🧑‍🎓 الزميل",
        "research-assistant": "🔬 المساعد البحثي",
    }
    selected_persona = st.selectbox(
        "شخصية المساعد", list(persona_options), format_func=lambda x: persona_options[x]
    )
    st.markdown("---")
    uploaded_file = st.file_uploader(
        "ارفع كتاباً أو ملفاً", type=["pdf", "txt", "md"]
    )
    if st.button("🔄 إعادة ضبط الجلسة", use_container_width=True):
        st.session_state.session_id = None
        st.session_state.messages = []
        st.rerun()

if not gemini_key:
    st.info("أدخل مفتاح Gemini API في الشريط الجانبي لبدء تشغيل المحرك.")
    st.stop()

try:
    catalog_path = configure_gemini(gemini_key, model_name)
    # Do not expose the actual API key in the cache key.
    import hashlib
    key_fingerprint = hashlib.sha256(gemini_key.encode("utf-8")).hexdigest()
    loop, app = get_background_engine(key_fingerprint)
    st.sidebar.success(f"Gemini مهيأ بنجاح · {model_name}")
except Exception as exc:
    st.error(f"تعذر تهيئة DeepTutor مع Gemini: {exc}")
    st.stop()

from deeptutor.core.turn_request import TurnRequest, OutgoingAttachment

if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("اكتب سؤالك أو الدرس الذي تريد شرحه..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    attachments = []
    if uploaded_file is not None:
        attachments.append(
            OutgoingAttachment(
                type="file",
                filename=uploaded_file.name,
                base64=base64.b64encode(uploaded_file.getvalue()).decode("utf-8"),
                mime_type=uploaded_file.type or "application/octet-stream",
            )
        )

    request = TurnRequest(
        content=prompt,
        capability=selected_cap,
        persona=selected_persona,
        session_id=st.session_state.session_id,
        attachments=attachments,
        language="ar",
    )

    with st.chat_message("assistant"):
        response_box = st.empty()
        status = st.status("🧠 جاري تشغيل DeepTutor...", expanded=True)
        events: Queue = Queue()

        async def run_turn(req: TurnRequest, queue: Queue):
            try:
                try:
                    session, turn = await app.start_turn(req)
                except Exception as exc:
                    if "not found in this workspace" in str(exc):
                        req.session_id = None
                        session, turn = await app.start_turn(req)
                    else:
                        raise
                queue.put(("session_id", session["id"]))
                async for event in app.stream_turn(turn["id"]):
                    queue.put(("event", event))
                try:
                    store = app.turns.store_provider.get()
                    db_messages = await store.get_messages(session["id"])
                    for item in reversed(db_messages):
                        if item.get("role") == "assistant" and item.get("content"):
                            queue.put(("fallback", item["content"]))
                            break
                except Exception:
                    pass
            except Exception as exc:
                queue.put(("error", str(exc)))
            finally:
                queue.put(("done", None))

        asyncio.run_coroutine_threadsafe(run_turn(request, events), loop)
        chunks: list[str] = []
        failure = None
        while True:
            kind, payload = events.get()
            if kind == "session_id":
                st.session_state.session_id = payload
            elif kind == "fallback" and not chunks:
                chunks.append(payload)
            elif kind == "event":
                event_type = payload.get("type")
                if event_type == "content":
                    content = payload.get("content", "")
                    if content:
                        chunks.append(content)
                        response_box.markdown("".join(chunks) + "▌")
                elif event_type == "thinking":
                    thought = payload.get("thinking", "")
                    if thought:
                        status.write(f"💭 {thought}")
                elif event_type == "tool_call":
                    status.write(f"🔧 استخدام أداة: `{payload.get('name', '')}`")
                elif event_type == "progress":
                    if payload.get("content"):
                        status.write(f"⏳ {payload['content']}")
                elif event_type == "error":
                    failure = payload.get("content") or payload.get("message") or str(payload)
                    break
                elif event_type == "result" and not chunks:
                    metadata = payload.get("metadata", {})
                    result = metadata.get("response") or metadata.get("answer") or payload.get("content", "")
                    if result:
                        chunks.append(result)
            elif kind == "error":
                failure = payload
                break
            elif kind == "done":
                break

        if failure:
            status.update(label="❌ حدث خطأ أثناء المعالجة", state="error")
            st.error(f"خطأ أثناء تشغيل محرك DeepTutor: {failure}")
        elif chunks:
            answer = "".join(chunks).strip()
            response_box.markdown(answer)
            status.update(label="✅ اكتملت الإجابة", state="complete", expanded=False)
            st.session_state.messages.append({"role": "assistant", "content": answer})
        else:
            status.update(label="⚠️ لم تصل إجابة", state="error")
            st.warning("انتهت المعالجة دون نص. راجع سجل تشغيل DeepTutor.")
