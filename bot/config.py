import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Server configuration
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8003))
    
    # OpenAI API configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Pinecone configuration
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_PRODUCTS_INDEX_NAME = os.getenv("PINECONE_PRODUCTS_INDEX_NAME")
    PINECONE_PRODUCTS_HOST = os.getenv("PINECONE_PRODUCTS_HOST")
    PINECONE_ORDERS_INDEX_NAME = os.getenv("PINECONE_ORDERS_INDEX_NAME")
    PINECONE_ORDERS_HOST = os.getenv("PINECONE_ORDERS_HOST")
    
    # Database configuration
    DATABASE_PATH = os.getenv("DATABASE_PATH", "data/shopez.db")