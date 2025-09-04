# ShopEZ-bot
ShopEZ Laptops is an intelligent AI-powered chatbot assistant designed to provide seamless customer service for an e-commerce laptop store. The chatbot handles product inquiries, order management, warranty claims, returns, cancellations, and general customer support.

Features
🤖 Intelligent Conversation Handling
Natural Language Understanding: Uses GPT-3.5-turbo for comprehensive intent recognition

Context Awareness: Maintains conversation context across multiple interactions

Multi-language Support: Handles both English and Japanese queries

Currency Conversion: Automatic JPY to INR conversion for product pricing

🛍️ Product Management
Smart Product Search: Semantic search using Pinecone vector database

Product Comparisons: Side-by-side comparison of laptop specifications

Budget Filtering: Intelligent price range filtering based on user constraints

Color & Feature Queries: Detailed product attribute inquiries

📦 Order Management
Order Status Tracking: Real-time order status updates

Order History: View recent orders with detailed information

Grid View Display: Visual order presentation with product images

Tracking Information: Carrier details and delivery estimates

🔄 Transaction Processing
Returns & Cancellations: Streamlined process for order modifications

Warranty Claims: Complete warranty management with policy display

Reason Mapping: Intelligent categorization of transaction reasons

Confirmation Workflow: Multi-step verification process

🎯 User Experience
Contextual Buttons: Dynamic button generation based on conversation context

Main Menu Navigation: Easy navigation between different service areas

Escalation Handling: Smooth transition to human agents when needed

Conversation History: Persistent chat history maintenance

Technology Stack
Backend
Python 3.8+: Core programming language

OpenAI GPT-3.5-turbo: Natural language processing

Pinecone: Vector database for product and order management

Custom NLU Service: Intent recognition and entity extraction

Database
Pinecone: For product catalog and order storage

SQL Database: For user sessions and conversation history

JSON Storage: For warranty policies and configuration

Services
Transaction Service: Handles returns, cancellations, and warranty claims

NLU Service: Natural language understanding

Response Generator: Dynamic response creation

Escalation Service: Human agent handoff

Installation & Setup
Prerequisites
Python 3.8 or higher

Pinecone account and API key

OpenAI API key

Database (PostgreSQL/MySQL)

Installation Steps
Clone the repository

bash
git clone <repository-url>
cd shopez-laptops
Install dependencies

bash
pip install -r requirements.txt
Configure environment variables
Create a .env file with:

env
# Pinecone Configuration
PINECONE_API_KEY= your API key
# Products Index
PINECONE_PRODUCTS_INDEX_NAME=ecommerce-products-duyfy6u
PINECONE_PRODUCTS_HOST=https://ecommerce-products-duyfy6u-duyfy6u.svc.aped-4627-b74a.pinecone.io

# Orders Index
PINECONE_ORDERS_INDEX_NAME=product-order
PINECONE_ORDERS_HOST=https://product-order-duyfy6u.svc.aped-4627-b74a.pinecone.io

# OpenAI Configuration
OPENAI_API_KEY=your API kere
DEBUG=True
HOST=0.0.0.0
PORT=8003

bash
 python -m app.main 

