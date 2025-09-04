import os
from openai import OpenAI

# Load API key from environment variable
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    print("❌ OPENAI_API_KEY is not set in environment variables.")
    exit(1)

try:
    client = OpenAI(api_key=api_key)

    # Simple test request
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": "Say 'Hello, OpenAI API is working!'"}
        ]
    )

    print("✅ API key is working!")
    print("Response:", response.choices[0].message.content)

except Exception as e:
    print("❌ Something went wrong:", e)
