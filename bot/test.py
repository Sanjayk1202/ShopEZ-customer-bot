import sys
import os
import json
from dotenv import load_dotenv

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

def test_pinecone():
    print("Testing Pinecone connection and data...")
    
    try:
        from managers.pinecone_manager import PineconeManager
        pinecone_manager = PineconeManager()
        
        # Test connection
        if pinecone_manager.test_connection():
            print("✅ Pinecone connection successful")
        else:
            print("❌ Pinecone connection failed")
            return
        
        # Test search with different queries
        test_queries = [
            "laptop",
            "gaming laptop", 
            "dell laptop",
            "laptop under 50000"
        ]
        
        for query in test_queries:
            print(f"\n🔍 Testing query: '{query}'")
            results = pinecone_manager.search_products(query, top_k=3, max_price=100000)
            
            if results and results.get('matches'):
                print(f"✅ Found {len(results['matches'])} products")
                for i, match in enumerate(results['matches']):
                    product = match['metadata']
                    print(f"   {i+1}. {product.get('name', 'Unknown')} - ₹{product.get('price', 'N/A')} - Score: {match['score']:.3f}")
            else:
                print("❌ No products found")
                
        # Test specific price filtering
        print(f"\n💰 Testing price filtering: under 60000")
        results = pinecone_manager.search_products("laptop", top_k=10, max_price=60000)
        
        if results and results.get('matches'):
            print(f"✅ Found {len(results['matches'])} products under ₹60000")
            for i, match in enumerate(results['matches']):
                product = match['metadata']
                price = product.get('price', 'N/A')
                print(f"   {i+1}. {product.get('name', 'Unknown')} - ₹{price} - Score: {match['score']:.3f}")
        else:
            print("❌ No products found under ₹60000")
            
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pinecone()