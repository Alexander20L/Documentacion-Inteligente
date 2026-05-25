import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)