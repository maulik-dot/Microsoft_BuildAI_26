import pdfplumber
from google import genai
import json
from backend.config import settings


def extract_text_from_pdf(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_resume(resume_text: str) -> dict:
    client = genai.Client(api_key=settings.google_api_key)

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"""Extract the following from this resume and return as JSON:
- name
- email
- skills (list, max 10)
- experience_years (number)
- education (list of degrees)
- domains (e.g. web dev, ML, mobile, data science)
- current_role

Resume:
{resume_text}

Return only valid JSON, no markdown.""",
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def parse_resume_from_file(pdf_path: str) -> dict:
    text = extract_text_from_pdf(pdf_path)
    return parse_resume(text)
