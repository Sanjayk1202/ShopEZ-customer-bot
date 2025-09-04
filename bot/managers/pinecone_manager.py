import os
import math
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
import pinecone
import time
import re
load_dotenv()

class PineconeManager:
    def __init__(self):
        from config import Config
        
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=Config.OPENAI_API_KEY
        )

        try:
            self.pc = pinecone.Pinecone(api_key=Config.PINECONE_API_KEY)
            
            self.index = self.pc.Index(
                Config.PINECONE_PRODUCTS_INDEX_NAME,
                host=Config.PINECONE_PRODUCTS_HOST
            )
            print(f"✅ Connected to Pinecone PRODUCTS index: {Config.PINECONE_PRODUCTS_INDEX_NAME}")
            
        except Exception as e:
            print(f"❌ Pinecone products initialization failed: {e}")
            raise

    def search_products(self, query, top_k=100, max_price=None):
     """Search entire Pinecone index without any filters"""
     try:
        # Clean the query
        query = str(query).replace('"', '').replace("'", "").strip()
        
        query_embedding = self.embeddings.embed_query(query)
        
        print(f"🔍 Semantic search for: '{query}'")
        print(f"📈 Getting top {top_k} matches from entire index")
        
        # Pure semantic search - NO FILTERS
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True
        )

        print(f"📊 Search returned {len(results['matches']) if results and 'matches' in results else 0} matches")
        
        return results
        
     except Exception as e:
        print(f"❌ Product search failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    def get_product_by_id(self, product_id: str):
        try:
            results = self.index.query(
                vector=[0.0] * 1536,
                top_k=1,
                include_metadata=True,
                filter={"product_id": {"$eq": product_id}}
            )
            if results and results['matches']:
                return results['matches'][0]['metadata']
            return None
        except Exception as e:
            print(f"❌ Failed to get product: {e}")
            return None

    def get_index_stats(self):
        try:
            return self.index.describe_index_stats()
        except Exception as e:
            print(f"❌ Failed to fetch stats: {e}")
            return None

    def test_connection(self):
        try:
            stats = self.get_index_stats()
            if stats:
                print("✅ Pinecone products connection test passed")
                print(f"Index dimensions: {stats.dimension}")
                print(f"Total vectors: {stats.total_vector_count}")
                return True
            return False
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False

    def _safe_float(self, value, default=0.0):
     """Safely convert value to float"""
     try:
        if value is None:
            return default
        if isinstance(value, str):
            # Remove currency symbols and commas
            value = re.sub(r'[^\d.]', '', value)
        return float(value) if value else default
     except (ValueError, TypeError):
        return default

    def _safe_int(self, value, default=0):
     """Safely convert value to integer"""
     try:
        if value is None:
            return default
        if isinstance(value, str):
            value = re.sub(r'[^\d]', '', value)
        return int(float(value)) if value else default
     except (ValueError, TypeError):
        return default

    def _safe_str(self, value, default=""):
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return default
            return str(value)
        except (ValueError, TypeError):
            return default
