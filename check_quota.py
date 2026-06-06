import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

try:
    from google import genai
    from google.genai import errors
    client = genai.Client(api_key=api_key)
except ImportError:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    client = None

models_to_test = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-flash-latest"
]

print("Checking API Quota across models...\n")

for model_name in models_to_test:
    try:
        if client:
            response = client.models.generate_content(
                model=model_name,
                contents='Say "hi"'
            )
        else:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content('Say "hi"')
            
        print(f"✅ {model_name}: HAS QUOTA (Response: {response.text.strip()})")
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "Quota" in error_msg:
            print(f"❌ {model_name}: QUOTA EXHAUSTED (429)")
        else:
            print(f"⚠️ {model_name}: ERROR - {error_msg.splitlines()[0]}")
