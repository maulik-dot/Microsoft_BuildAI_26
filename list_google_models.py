import os
from dotenv import load_dotenv

# Try importing the older google.generativeai first, then the new google.genai
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

try:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    print("Models available (via google.generativeai):")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f" - {m.name}")
except ImportError:
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        print("Models available (via google.genai):")
        for model in client.models.list():
            print(f" - {model.name}")
    except Exception as e:
        print(f"Error checking models: {e}")
