import pdfplumber
import json
from backend.config import settings


def extract_text_from_pdf(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_resume(resume_text: str) -> dict:
    prompt = f"""Extract the following from this resume and return as JSON:
- name
- email
- skills (list, max 10)
- experience_years (number)
- education (list of degrees)
- domains (e.g. web dev, ML, mobile, data science)
- current_role

Resume:
{resume_text}

Return only valid JSON, no markdown."""

    raw = ""

    # Try Groq first
    if settings.groq_api_key:
        try:
            from groq import Groq
            client = Groq(api_key=settings.groq_api_key)
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            raw = r.choices[0].message.content.strip()
        except Exception:
            pass

    # Fall back to the router's best model (Gemini, or OpenRouter once exhausted)
    if not raw and (settings.google_api_key or settings.openrouter_api_key):
        from backend.tools.model_selector import get_working_model
        from backend.tools.llm_client import complete_text
        raw = complete_text(get_working_model(), prompt)

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def parse_resume_from_file(pdf_path: str) -> dict:
    text = extract_text_from_pdf(pdf_path)
    return parse_resume(text)
