import streamlit as st
import os
from pypdf import PdfReader
from google import genai

# إعداد الصفحة
st.set_page_config(page_title="DeepTutor - المدرس الذكي", page_icon="🎓", layout="wide")

st.title("🎓 DeepTutor - المعلم الذكي التفاعلي")
st.markdown("ارفع كتابك أو ملخصك بصيغة **PDF**، وسيقوم المدرس الذكي بشرحه واختبارك فيه!")

# 1. إعداد مفتاح الـ API
api_key = os.getenv("GEMINI_API_KEY")
with st.sidebar:
    st.header("⚙️ إعدادات المدرس")
    if not api_key:
        api_key = st.text_input("أدخل مفتاح Gemini API:", type="password")
        if not api_key:
            st.warning("الرجاء إدخال مفتاح API للمتابعة.")
            st.stop()
    
    st.success("المدرس متصل وجاهز! 🟢")
    mode = st.radio("اختر أسلوب التدريس:", [
        "👨‍🏫 تدريس وشرح مبسط خطوة بخطوة",
        "📝 تلخيص أهم المفاهيم",
        "❓ اختبار تفاعلي وأسئلة (Quiz)"
    ])
    
    uploaded_file = st.file_uploader("📚 ارفع كتاب أو ملف PDF:", type=["pdf"])

# 2. قراءة واستخراج نص الكتاب
pdf_text = ""
if uploaded_file:
    with st.spinner("جاري قراءة وفهرسة صفحات الكتاب..."):
        reader = PdfReader(uploaded_file)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pdf_text += text + "\n"
        st.sidebar.success(f"تم تحميل الكتاب بنجاح ({len(reader.pages)} صفحة)")

# 3. إدارة جلسة المحادثة
if "messages" not in st.session_state:
    st.session_state.messages = []

# عرض المحادثات السابقة
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. استقبال أسئلة الطالب والرد عليها
if prompt := st.chat_input("اسأل المدرس أي سؤال حول الكتاب..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # بناء سياق التعليمات
    system_instruction = f"""
    أنت DeepTutor، معلم خصوصي ذكي، صبور، ومشجع.
    أسلوبك الحالي هو: {mode}.
    {"محتوى الكتاب المرفوع للدراسة منه:" + pdf_text[:80000] if pdf_text else "لم يتم رفع ملف بعد، أجب بناءً على سؤال الطالب."}
    اشرح بأسلوب تفاعلي، باللغة العربية، ونسق إجاباتك بنقاط واضحة.
    """

    with st.chat_message("assistant"):
        with st.spinner("المعلم يفكر ويجهز الشرح..."):
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[system_instruction, f"سؤال الطالب: {prompt}"]
                )
                st.markdown(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"حدث خطأ أثناء الاتصال: {e}")
