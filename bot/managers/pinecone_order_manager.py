import os
import math
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
import pinecone
import time

load_dotenv()

class PineconeOrderManager:
    def __init__(self):
        from config import Config
        
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=Config.OPENAI_API_KEY
        )

        try:
            self.pc = pinecone.Pinecone(api_key=Config.PINECONE_API_KEY)
            
            self.index = self.pc.Index(
                Config.PINECONE_ORDERS_INDEX_NAME,
                host=Config.PINECONE_ORDERS_HOST
            )
            print(f"✅ Connected to Pinecone ORDERS index: {Config.PINECONE_ORDERS_INDEX_NAME}")
            
        except Exception as e:
            print(f"❌ Pinecone orders initialization failed: {e}")
            raise

    def _safe_float(self, value, default=0.0):
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    def _safe_int(self, value, default=0):
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return default
            return int(float(value))
        except (ValueError, TypeError):
            return default

    def _safe_str(self, value, default=""):
        try:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return default
            return str(value)
        except (ValueError, TypeError):
            return default

    def search_orders(self, query, customer_id=None, top_k=5):
        try:
            query_embedding = self.embeddings.embed_query(query)

            filter_dict = {"type": {"$eq": "order"}}
            if customer_id:
                filter_dict["customer_id"] = {"$eq": str(customer_id)}

            results = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True,
                filter=filter_dict
            )

            return results
        except Exception as e:
            print(f"❌ Order search failed: {e}")
            return None

    def get_customer_orders(self, customer_id, top_k=10):
        try:
            results = self.index.query(
                vector=[0.0] * 1536,
                top_k=top_k,
                include_metadata=True,
                filter={
                    "type": {"$eq": "order"},
                    "customer_id": {"$eq": str(customer_id)}
                }
            )
            return results
        except Exception as e:
            print(f"❌ Failed to get customer orders: {e}")
            return None

    def get_order_by_id(self, order_id):
        try:
            results = self.index.query(
                vector=[0.0] * 1536,
                top_k=1,
                include_metadata=True,
                filter={
                    "type": {"$eq": "order"},
                    "order_id": {"$eq": order_id}
                }
            )
            if results and results['matches']:
                return results['matches'][0]['metadata']
            return None
        except Exception as e:
            print(f"❌ Failed to get order: {e}")
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
                print("✅ Pinecone orders connection test passed")
                print(f"Index dimensions: {stats.dimension}")
                print(f"Total vectors: {stats.total_vector_count}")
                return True
            return False
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False