import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List
import os
import pinecone
from langchain_openai import OpenAIEmbeddings
from config import Config

class TransactionService:
    def __init__(self):
        # Initialize Pinecone
        try:
            self.pc = pinecone.Pinecone(api_key=Config.PINECONE_API_KEY)
            
            # Initialize indexes for different transaction types
            self.cancel_index = self.pc.Index(
                "cancel-orders",
                host="https://cancel-orders-duyfy6u.svc.aped-4627-b74a.pinecone.io"
            )
            
            self.return_index = self.pc.Index(
                "return-orders", 
                host="https://return-orders-duyfy6u.svc.aped-4627-b74a.pinecone.io"
            )
            
            self.warranty_index = self.pc.Index(
                "warranty-claims",
                host="https://warranty-claims-duyfy6u.svc.aped-4627-b74a.pinecone.io"
            )
            
            self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            print("✅ Connected to Pinecone transaction indexes")
            
        except Exception as e:
            print(f"❌ Pinecone transaction initialization failed: {e}")
            # Fallback to JSON files if Pinecone fails
            self._init_json_fallback()
        
        # Keep the same reason lists for compatibility
        self.cancellation_reasons = [
            "Found better price elsewhere",
            "Changed my mind",
            "Ordered by mistake",
            "Delivery too long",
            "Other"
        ]
        
        self.return_reasons = [
            "Faulty/Defective",
            "Wrong item received",
            "Item not as described",
            "No longer needed",
            "Other"
        ]
        
        self.warranty_reasons = [
            "Battery issues",
            "Screen problems",
            "Performance issues",
            "Hardware failure",
            "Software problems",
            "Other"
        ]

    def _init_json_fallback(self):
        """Fallback to JSON files if Pinecone fails"""
        print("🔄 Falling back to JSON storage")
        os.makedirs("data", exist_ok=True)
        
        self.cancellations_file = "data/cancellations.json"
        self.refunds_file = "data/refunds.json"
        self.warranty_file = "data/warranty_claims.json"
        self._ensure_files_exist()
        self.use_pinecone = False

    def _ensure_files_exist(self):
        """Ensure JSON files exist (for fallback)"""
        for file_path in [self.cancellations_file, self.refunds_file, self.warranty_file]:
            try:
                with open(file_path, 'r') as f:
                    json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                with open(file_path, 'w') as f:
                    json.dump([], f, indent=2)

    def _generate_transaction_id(self, prefix: str) -> str:
        """Generate transaction ID (same as before)"""
        return f"{prefix}-{str(uuid.uuid4())[:8].upper()}"

    def get_reasons(self, transaction_type: str) -> List[str]:
        """Get reasons for transaction type (same as before)"""
        if transaction_type == "cancellation":
            return self.cancellation_reasons
        elif transaction_type == "return":
            return self.return_reasons
        elif transaction_type == "warranty":
            return self.warranty_reasons
        return []

    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Clean metadata by converting None values to appropriate defaults"""
        cleaned = {}
        for key, value in metadata.items():
            if value is None:
                # Convert None to appropriate default values
                if key in ['product_id', 'tracking_number', 'username', 'email']:
                    cleaned[key] = "N/A"
                elif key in ['refund_amount', 'price', 'amount']:
                    cleaned[key] = 0
                elif key == 'status':
                    cleaned[key] = "unknown"
                else:
                    cleaned[key] = ""
            else:
                cleaned[key] = value
        return cleaned

    def log_cancellation(self, user_data: Dict[str, Any], order_data: Dict[str, Any], reason: str) -> str:
        """Log cancellation to Pinecone (with JSON fallback)"""
        transaction_id = self._generate_transaction_id("CXL")
        
        cancellation_record = {
            "transaction_id": transaction_id,
            "user_id": user_data.get("user_id", "N/A"),
            "username": user_data.get("username", "N/A"),
            "order_id": order_data.get("order_id", "N/A"),
            "product_id": order_data.get("product_id", "N/A"),
            "product_name": order_data.get("product_name", "Unknown Product"),
            "cancellation_reason": reason,
            "cancellation_date": datetime.now().strftime("%Y-%m-%d"),
            "refund_amount": order_data.get("price", 0),
            "refund_status": "processing",
            "refund_expected_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "currency": order_data.get("currency", "JPY")
        }

        # Clean the metadata
        cancellation_record = self._clean_metadata(cancellation_record)

        try:
            # Try to store in Pinecone
            embedding_text = f"""
            Cancellation: {transaction_id}
            User: {user_data.get('user_id')}
            Order: {order_data.get('order_id')}
            Product: {order_data.get('product_name')}
            Reason: {reason}
            Amount: {order_data.get('price')}
            """
            
            embedding = self.embeddings.embed_query(embedding_text)
            
            self.cancel_index.upsert(
                vectors=[{
                    "id": transaction_id,
                    "values": embedding,
                    "metadata": cancellation_record
                }]
            )
            print(f"✅ Cancellation logged to Pinecone: {transaction_id}")
            
        except Exception as e:
            print(f"❌ Pinecone error, falling back to JSON: {e}")
            # Fallback to JSON
            self._append_to_file(self.cancellations_file, cancellation_record)
        
        return transaction_id

    def log_refund(self, user_data: Dict[str, Any], order_data: Dict[str, Any], reason: str) -> str:
        """Log return/refund to Pinecone (with JSON fallback)"""
        transaction_id = self._generate_transaction_id("REF")
        
        refund_record = {
            "transaction_id": transaction_id,
            "user_id": user_data.get("user_id", "N/A"),
            "username": user_data.get("username", "N/A"),
            "order_id": order_data.get("order_id", "N/A"),
            "product_id": order_data.get("product_id", "N/A"),
            "product_name": order_data.get("product_name", "Unknown Product"),
            "return_reason": reason,
            "return_request_date": datetime.now().strftime("%Y-%m-%d"),
            "return_approval_date": datetime.now().strftime("%Y-%m-%d"),
            "refund_amount": order_data.get("price", 0),
            "refund_status": "initiated",
            "refund_expected_date": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
            "currency": order_data.get("currency", "JPY")
        }

        # Clean the metadata
        refund_record = self._clean_metadata(refund_record)

        try:
            # Try to store in Pinecone
            embedding_text = f"""
            Return: {transaction_id}
            User: {user_data.get('user_id')}
            Order: {order_data.get('order_id')}
            Product: {order_data.get('product_name')}
            Reason: {reason}
            Amount: {order_data.get('price')}
            """
            
            embedding = self.embeddings.embed_query(embedding_text)
            
            self.return_index.upsert(
                vectors=[{
                    "id": transaction_id,
                    "values": embedding,
                    "metadata": refund_record
                }]
            )
            print(f"✅ Return logged to Pinecone: {transaction_id}")
            
        except Exception as e:
            print(f"❌ Pinecone error, falling back to JSON: {e}")
            # Fallback to JSON
            self._append_to_file(self.refunds_file, refund_record)
        
        return transaction_id

    def log_warranty_claim(self, user_data: Dict[str, Any], order_data: Dict[str, Any], reason: str) -> str:
        """Log warranty claim to Pinecone (with JSON fallback)"""
        transaction_id = self._generate_transaction_id("WAR")
        
        warranty_record = {
            "transaction_id": transaction_id,
            "user_id": user_data.get("user_id", "N/A"),
            "username": user_data.get("username", "N/A"),
            "order_id": order_data.get("order_id", "N/A"),
            "product_id": order_data.get("product_id", "N/A"),
            "product_name": order_data.get("product_name", "Unknown Product"),
            "claim_reason": reason,
            "claim_date": datetime.now().strftime("%Y-%m-%d"),
            "status": "under_review",
            "resolution": "Pending assessment",
            "tracking_number": "N/A"
        }

        # Clean the metadata
        warranty_record = self._clean_metadata(warranty_record)

        try:
            # Try to store in Pinecone
            embedding_text = f"""
            Warranty: {transaction_id}
            User: {user_data.get('user_id')}
            Order: {order_data.get('order_id')}
            Product: {order_data.get('product_name')}
            Reason: {reason}
            """
            
            embedding = self.embeddings.embed_query(embedding_text)
            
            self.warranty_index.upsert(
                vectors=[{
                    "id": transaction_id,
                    "values": embedding,
                    "metadata": warranty_record
                }]
            )
            print(f"✅ Warranty claim logged to Pinecone: {transaction_id}")
            
        except Exception as e:
            print(f"❌ Pinecone error, falling back to JSON: {e}")
            # Fallback to JSON
            self._append_to_file(self.warranty_file, warranty_record)
        
        return transaction_id

    def _append_to_file(self, file_path: str, record: Dict[str, Any]):
        """Append to JSON file (fallback method)"""
        with open(file_path, 'r+') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
            data.append(record)
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()

    def get_transaction_history(self, user_id: str) -> Dict[str, List]:
        """Get transaction history from Pinecone (with JSON fallback)"""
        history = {"cancellations": [], "refunds": [], "warranty_claims": []}
        
        try:
            # Try to get from Pinecone first
            for index_name, index in [
                ("cancellations", self.cancel_index),
                ("refunds", self.return_index),
                ("warranty_claims", self.warranty_index)
            ]:
                try:
                    results = index.query(
                        vector=[0.0] * 1536,
                        top_k=50,
                        include_metadata=True,
                        filter={"user_id": {"$eq": user_id}}
                    )
                    
                    if results and results.get('matches'):
                        for match in results['matches']:
                            history[index_name].append(match['metadata'])
                except Exception as e:
                    print(f"❌ Error querying {index_name} from Pinecone: {e}")
                    # Fallback to JSON for this transaction type
                    self._get_from_json_fallback(history, index_name, user_id)
                    
        except Exception as e:
            print(f"❌ Pinecone query failed, falling back to JSON: {e}")
            # Complete fallback to JSON
            for file_type in ["cancellations", "refunds", "warranty_claims"]:
                self._get_from_json_fallback(history, file_type, user_id)
        
        return history

    def _get_from_json_fallback(self, history: Dict[str, List], file_type: str, user_id: str):
        """Fallback method to get transactions from JSON files"""
        file_mapping = {
            "cancellations": "data/cancellations.json",
            "refunds": "data/refunds.json",
            "warranty_claims": "data/warranty_claims.json"
        }
        
        file_path = file_mapping.get(file_type)
        if not file_path:
            return
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                user_transactions = [t for t in data if t.get('user_id') == user_id]
                history[file_type] = user_transactions
        except (FileNotFoundError, json.JSONDecodeError):
            history[file_type] = []