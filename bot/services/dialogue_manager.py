from typing import Dict, Any, List
from services.transaction_service import TransactionService
from services.nlu_service import NLUService
from services.response_generator import ResponseGenerator
from services.escalation_service import EscalationService
from managers.pinecone_order_manager import PineconeOrderManager
from managers.pinecone_manager import PineconeManager
from database.db_connector import db
import json
from datetime import datetime
import openai
import re
from config import Config
import os

class DialogueManager:
    def __init__(self):
        self.transaction_service = TransactionService()
        self.nlu_service = NLUService()
        self.response_generator = ResponseGenerator()
        self.escalation_service = EscalationService()
        self.order_manager = PineconeOrderManager()
        self.product_manager = PineconeManager()
        
        self.current_state = {}
        self.context = {}
        self.user_data = {}
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        self.conversation_history = []
        
        # Currency conversion rate (1 INR = 1.67 JPY approx, so 1 JPY = 0.60 INR)
        self.yen_to_inr_rate = 0.60
        
        # Escalation tracking
        self.response_count = 0
        self.escalation_offered = False
        self.escalation_pending = False
        
        # Load warranty policies
        self.warranty_policies = self._load_warranty_policies()

    def _load_warranty_policies(self) -> Dict[str, Any]:
        """Load warranty policies from JSON file"""
        try:
            policy_path = os.path.join('data', 'warranty_policies.json')
            with open(policy_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading warranty policies: {e}")
            # Return default policies if file not found
            return {
                "company": "ShopEZ",
                "policy_type": "Laptop Warranty",
                "policy": [
                    "All ShopEZ laptops come with a 1-year warranty from the date of purchase.",
                    "The warranty covers manufacturing defects in materials and workmanship.",
                    "It does not cover damage due to accidents, misuse, unauthorized repairs, or normal wear and tear.",
                    "Customers must provide a valid purchase invoice for warranty claims.",
                    "ShopEZ reserves the right to repair, replace, or refund the product at its discretion."
                ]
            }

    def handle_message(self, user_message: str, user_data: Dict[str, Any], session_id: str, initial_context: Dict[str, Any] = None) -> Dict[str, Any]:
    # Check for main menu command FIRST - before any context initialization
     if user_message.lower() in ['main menu', 'menu', 'home', 'ホーム', 'メインメニュー']:
        return self._handle_main_menu()

    # Initialize context and state
     self.current_state = {}
     self.context = initial_context or {}
     self.user_data = user_data
    
     if 'user_data' not in self.context:
        self.context['user_data'] = user_data

    # Add to conversation history
     self.conversation_history.append({"role": "user", "content": user_message})
    
     db.save_conversation(user_data['user_id'], user_message, "Processing...")
    
    # Check if escalation is pending
     if self.escalation_pending:
        return self._handle_escalation_response(user_message, session_id)
    
    # Check if we should offer escalation (after 4 responses)
     self.response_count += 1
     if self.response_count >= 4 and not self.escalation_offered:
        return self._offer_escalation(user_message, session_id)
    
     try:
        # Check if this is a warranty policy inquiry
        if self._is_warranty_policy_inquiry(user_message):
            return self._handle_warranty_policy_inquiry(user_message, session_id)
        
        # Check for context switching requests FIRST
        context_switch_response = self._handle_context_switching(user_message, session_id)
        if context_switch_response:
            return context_switch_response
        
        # Check if this is a multi-line comparison or complex query that should go directly to GPT
        if self._should_use_gpt_directly(user_message):
            return self._handle_with_gpt(user_message, "general_question", {}, session_id)
        
        # Use GPT for comprehensive understanding first
        gpt_understanding = self._understand_with_gpt(user_message, self.context)
        
        # Extract intent and entities from GPT understanding
        intent = gpt_understanding.get('intent', 'general_question')
        entities = gpt_understanding.get('entities', {})
        
        # Update context with extracted entities
        if entities:
            self.context.update(entities)
        
        # Handle context switching based on detected intent
        if (intent == "order_status" and self.context.get('in_purchase_flow')):
            # User is asking about order status while in purchase flow - switch context
            self.context['in_purchase_flow'] = False
            purchase_context_keys = ['current_products', 'last_search_query']
            for key in purchase_context_keys:
                self.context.pop(key, None)
        
        # Clear purchase context if we're not in purchase flow
        if (intent != "product_inquiry" and 
            not self.context.get('in_purchase_flow') and
            not any(keyword in user_message.lower() for keyword in ['laptop', 'buy', 'purchase', 'computer'])):
            # Remove purchase-related context to prevent bleed
            purchase_context_keys = ['current_products', 'last_search_query', 'in_purchase_flow']
            for key in purchase_context_keys:
                self.context.pop(key, None)
        
        # Check for comparison requests
        if any(word in user_message.lower() for word in ['compare', 'comparison', 'vs', 'versus', 'difference between']):
            response = self._handle_comparison_request(user_message, intent, entities, session_id)
        
        # Check if this is a color inquiry about existing products
        elif (self.context.get('current_products') and 
            any(word in user_message.lower() for word in ['color', 'colour', 'blue', 'red', 'black', 'silver', 'gray', 'white'])):
            response = self._handle_color_inquiry(user_message, intent, entities, session_id)
        
        # Handle purchase flow if detected by GPT
        elif (intent == "product_inquiry" or 
            self.context.get('in_purchase_flow') or
            any(keyword in user_message.lower() for keyword in ['laptop', 'buy', 'purchase', 'computer'])):
            
            self.context['in_purchase_flow'] = True
            response = self._handle_purchase_flow(user_message, intent, entities, session_id)
        
        # Handle transaction flows
        elif self.context.get('awaiting_confirmation'):
            response = self._handle_transaction_confirmation(user_message, intent, entities, session_id)
        elif self.context.get('awaiting_reason'):
            response = self._handle_reason_response(user_message, intent, entities, session_id)
        elif self.context.get('awaiting_order_id'):
            response = self._handle_order_id_response(user_message, intent, entities, session_id)
        elif self.context.get('awaiting_warranty_confirmation'):
            response = self._handle_warranty_confirmation(user_message, intent, entities, session_id)
        elif intent in ["return_request", "cancellation_request", "warranty_claim"]:
            response = self._handle_transaction_intent(intent, entities, user_message, session_id)
        elif intent == "order_status":
            response = self._handle_order_status(user_message, intent, entities, session_id)
        else:
            # Let GPT handle everything else
            response = self._handle_with_gpt(user_message, intent, entities, session_id)
        
        # Add assistant response to history
        self.conversation_history.append({"role": "assistant", "content": response["response"]})
        
     except Exception as e:
        print(f"Error in handle_message: {e}")
        response = self._handle_with_gpt_fallback(user_message)
    
     db.save_conversation(user_data['user_id'], user_message, response["response"])
     db.update_user_session(user_data['user_id'], session_id, json.dumps(self.current_state), json.dumps(self.context))
    
     return response
    
    def _handle_context_switching(self, user_message: str, session_id: str) -> Dict[str, Any]:
     """Handle context switching between different sections"""
     user_message_lower = user_message.lower()
    
    # Check for warranty policy inquiries specifically
     if self._is_warranty_policy_inquiry(user_message):
        return self._handle_warranty_policy_inquiry(user_message, session_id)
    
    # Check for warranty claims (not policy inquiries)
     warranty_queries = ['warranty claim', 'warranty request', 'file warranty', 'make warranty']
     if any(query in user_message_lower for query in warranty_queries):
        # Clear purchase context
        purchase_context_keys = ['current_products', 'last_search_query', 'in_purchase_flow']
        for key in purchase_context_keys:
            self.context.pop(key, None)
        
        # Extract order ID if provided
        order_match = re.search(r'ORD[_-]?\d+', user_message, re.IGNORECASE)
        if order_match:
            order_id = order_match.group(0).upper().replace('_', '-')
            if not order_id.startswith('ORD-'):
                order_id = order_id.replace('ORD', 'ORD-')
            
            entities = {'order_id': order_id}
            return self._handle_transaction_intent("warranty_claim", entities, user_message, session_id)
        else:
            # Ask for order ID
            self.context['awaiting_order_id'] = True
            self.context['transaction_type'] = 'warranty'
            return self._handle_with_gpt(
                "I can help with your warranty claim. Please provide your Order ID.",
                "warranty_claim", 
                {}, 
                session_id
            )
            
    
    def _is_warranty_policy_inquiry(self, user_message: str) -> bool:
     """Check if the user is asking about warranty policies (not making a claim)"""
     policy_keywords = [
        'warranty policy', 'warranty information', 'warranty terms',
        'warranty coverage', 'what is covered', 'warranty details',
        'policy', 'policies', 'terms and conditions', 'what is the warranty',
        'how does warranty work', 'warranty period'
     ]
    
     claim_keywords = [
        'warranty claim', 'file warranty', 'make warranty', 'request warranty',
        'warranty request', 'need warranty', 'want warranty'
     ]
    
     user_message_lower = user_message.lower()
    
    # It's a policy inquiry if it contains policy keywords but NOT claim keywords
     has_policy_keywords = any(keyword in user_message_lower for keyword in policy_keywords)
     has_claim_keywords = any(keyword in user_message_lower for keyword in claim_keywords)
    
     return has_policy_keywords and not has_claim_keywords
    
    def _handle_warranty_policy_inquiry(self, user_message: str, session_id: str) -> Dict[str, Any]:
     """Handle warranty policy inquiries"""
    # Format warranty policies as numbered list
     policy_text = f"{self.warranty_policies['company']} - {self.warranty_policies['policy_type']}:\n\n"
     for i, policy in enumerate(self.warranty_policies['policy'], 1):
        policy_text += f"{i}. {policy}\n"
    
     policy_text += "\nWould you like to proceed with your warranty claim?"
    
    # Set context for warranty confirmation
     self.context['awaiting_warranty_confirmation'] = True
    
     return {
        "response": policy_text,
        "buttons": ["Yes, proceed", "No, cancel"],
        "intent": "warranty_policy",
        "entities": {},
        "display_type": "policy_view"
     }
    
    def _handle_warranty_confirmation(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
     """Handle user response to warranty policy confirmation"""
     user_message_lower = user_message.lower()
    
    # Check for positive confirmation responses
     positive_responses = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'proceed', 'confirm', 'continue', 'ok', 'alright']
    
     if any(word in user_message_lower for word in positive_responses):
        # User wants to proceed with warranty claim
        self.context['awaiting_warranty_confirmation'] = False
        
        # Continue with warranty claim process by asking for reason
        self.context['awaiting_reason'] = True
        return self._ask_for_reason("warranty")
     else:
        # User doesn't want to proceed with warranty
        self.context['awaiting_warranty_confirmation'] = False
        return self._handle_with_gpt(
            "Warranty claim cancelled. Is there anything else I can help you with?",
            "general_question", 
            entities, 
            session_id
        )
    
    def _should_use_gpt_directly(self, user_message: str) -> bool:
        """Determine if the message should be handled directly by GPT"""
        # Check for multi-line messages (likely complex queries)
        if user_message.count('\n') >= 1:
            return True
            
        # Check for comparison queries
        if any(word in user_message.lower() for word in ['compare', 'comparison', 'vs', 'versus', 'difference between', 'which is better']):
            return True
            
        # Check for general chat queries that should go to GPT
        general_chat_patterns = [
            'is this.*available in', 'how do i track', 'can i return', 
            'what.*warranty', 'how.*return', 'where.*track',
            'do you have', 'when will', 'how long', 'what is',
            'tell me about', 'explain', 'help with'
        ]
        
        user_message_lower = user_message.lower()
        for pattern in general_chat_patterns:
            if pattern in user_message_lower:
                return True
        
        # Check for complex questions
        complex_indicators = [
            'what is the difference', 'how does', 'why should', 'tell me about',
            'explain', 'pros and cons', 'advantages and disadvantages'
        ]
        
        if any(indicator in user_message_lower for indicator in complex_indicators):
            return True
            
        return False
    
    def _offer_escalation(self, user_message: str, session_id: str) -> Dict[str, Any]:
        """Offer to connect with a human agent"""
        self.escalation_offered = True
        
        return {
            "response": "I've been helping you for a while. Would you like to speak with a human agent for more personalized assistance?",
            "buttons": ["Yes, connect to agent", "No, continue with chat"],
            "intent": "escalation_offer",
            "entities": {},
            "escalation_offered": True
        }
    
    def _handle_escalation_response(self, user_message: str, session_id: str) -> Dict[str, Any]:
        """Handle user response to escalation offer"""
        user_message_lower = user_message.lower()
        
        if any(word in user_message_lower for word in ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'connect', 'agent', 'human']):
            # User wants escalation
            self.escalation_pending = False
            escalation_result = self.escalation_service.escalate_to_agent(
                self.user_data, 
                self.conversation_history
            )
            
            if escalation_result.get('success'):
                return {
                    "response": "I'm connecting you with a human agent. Please wait while we connect your call...\n\n✅ Connected! An agent will be with you shortly.",
                    "buttons": ["Main Menu"],
                    "intent": "escalation_success",
                    "entities": {},
                    "escalated": True
                }
            else:
                return {
                    "response": "I apologize, but all our agents are currently busy. Please try again in a few minutes or continue chatting with me.",
                    "buttons": ["Main Menu", "Continue Chat"],
                    "intent": "escalation_failed",
                    "entities": {}
                }
        else:
            # User doesn't want escalation
            self.escalation_pending = False
            # Continue with normal processing
            return self._handle_with_gpt(user_message, "general_question", {}, session_id)

    def _handle_comparison_request(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Handle product comparison requests"""
        try:
            # Extract product names from message using GPT
            comparison_products = self._extract_comparison_products(user_message)
            
            if not comparison_products or len(comparison_products) < 2:
                return self._handle_with_gpt(
                    "I need at least two products to compare. Please specify which models you'd like to compare.",
                    intent, entities, session_id
                )
            
            # Search for each product
            products_to_compare = []
            for product_name in comparison_products:
                results = self.product_manager.search_products(query=product_name, top_k=3)
                if results and results.get('matches'):
                    for match in results['matches']:
                        if match['score'] > 0.3:  # Good match threshold
                            product_data = self._extract_product_data(match['metadata'], match)
                            if product_data:
                                products_to_compare.append(product_data)
                                break
            
            if len(products_to_compare) < 2:
                return self._handle_with_gpt(
                    "I couldn't find enough matching products to compare. Please be more specific about the models.",
                    intent, entities, session_id
                )
            
            # Generate comparison using GPT
            comparison_text = self._generate_comparison_response(products_to_compare, user_message)
            
            return {
                "response": comparison_text,
                "buttons": ["Main Menu", "Purchase Laptop", "More Details"],
                "intent": "product_comparison",
                "entities": entities,
                "products": products_to_compare,
                "display_type": "comparison_view"
            }
            
        except Exception as e:
            print(f"Comparison error: {e}")
            return self._handle_with_gpt(
                "I'm having trouble comparing those products. Could you please specify the exact model names?",
                intent, entities, session_id
            )

    def _extract_comparison_products(self, user_message: str) -> List[str]:
        """Extract product names from comparison request using GPT"""
        try:
            prompt = f"""
            Extract the laptop model names from this comparison request:
            
            User message: "{user_message}"
            
            Return ONLY a JSON array of product names, nothing else.
            Example: ["Lenovo ThinkPad X1", "Dell XPS 13", "HP Spectre x360"]
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You extract product names from comparison requests. Return only JSON arrays."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=100,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            return list(result.values())[0] if result else []
            
        except Exception as e:
            print(f"GPT comparison extraction error: {e}")
            # Fallback: simple keyword extraction
            brands = ['lenovo', 'dell', 'hp', 'apple', 'asus', 'acer', 'msi']
            words = user_message.lower().split()
            return [word for word in words if any(brand in word for brand in brands)]

    def _generate_comparison_response(self, products: List[Dict], user_message: str) -> str:
        """Generate comparison response using GPT"""
        try:
            product_info = []
            for i, product in enumerate(products):
                info = f"Product {i+1}: {product['brand']} {product['name']} - ¥{product['price']:,}"
                info += f"\n- RAM: {product['ram']}, Storage: {product['storage']}, Processor: {product['processor']}"
                info += f"\n- Rating: {product['rating']}⭐ ({product.get('reviews', 0)} reviews)"
                if product.get('colors'):
                    info += f"\n- Colors: {product['colors']}"
                product_info.append(info)
            
            prompt = f"""
            User asked: "{user_message}"
            
            Compare these laptops:
            
            {'\n\n'.join(product_info)}
            
            Create a detailed comparison highlighting:
            1. Price difference and value for money
            2. Performance differences (processor, RAM)
            3. Storage options
            4. Overall rating and user reviews
            5. Any notable features
            
            Be objective and helpful. Keep it to 5-6 sentences.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert laptop comparison assistant. Be detailed and objective."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=250
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT comparison response error: {e}")
            # Fallback comparison
            comparison = f"I found {len(products)} products for comparison:\n\n"
            for product in products:
                comparison += f"• {product['brand']} {product['name']} - ¥{product['price']:,} - {product['ram']} - {product['processor']}\n"
            return comparison
    
    def _handle_order_status(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Handle order status requests with grid view"""
        user_message_lower = user_message.lower()
        
        # Handle action requests from buttons
        if any(action in user_message_lower for action in ['track', 'warranty', 'cancel', 'return']):
            # Extract order ID from message if present
            order_match = re.search(r'ORD-\d+', user_message, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(0).upper()
                
                if 'track' in user_message_lower:
                    return self._handle_tracking_request(order_id, intent, entities, session_id)
                elif 'warranty' in user_message_lower:
                    return self._handle_transaction_intent("warranty_claim", entities, user_message, session_id)
                elif 'cancel' in user_message_lower:
                    return self._handle_transaction_intent("cancellation_request", entities, user_message, session_id)
                elif 'return' in user_message_lower:
                    return self._handle_transaction_intent("return_request", entities, user_message, session_id)
        
        # Check if this is a tracking request for a specific order
        if user_message.startswith("Track order ") or "track" in user_message_lower and "ORD-" in user_message:
            order_match = re.search(r'ORD-\d+', user_message, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(0).upper()
                return self._handle_tracking_request(order_id, intent, entities, session_id)
        
        # Check if order ID is already provided
        order_id = entities.get('order_id')
        
        if order_id:
            # Get specific order details
            order_details = self._get_order_info(order_id)
            if order_details:
                # Return single order in grid view
                orders = [order_details]
                response_text = f"Here are the details for your order {order_id}:"
                
                # Determine which buttons to show based on order status
                status = order_details.get('status', '').lower()
                if status == 'delivered':
                    buttons = ["Return", "Warranty", "Track", "Main Menu"]
                elif status in ['shipped', 'processing', 'confirmed']:
                    buttons = ["Track", "Cancel", "Main Menu"]
                else:
                    buttons = ["Track", "Main Menu"]
                
                return {
                    "response": response_text,
                    "buttons": buttons,
                    "intent": intent,
                    "entities": entities,
                    "orders": orders,
                    "display_type": "order_grid"
                }
            else:
                return self._handle_with_gpt(
                    f"Order {order_id} not found. Please check your Order ID and try again.",
                    "order_status", 
                    entities, 
                    session_id
                )
        else:
            # Get all orders for the user
            user_orders = self._get_user_orders()
            
            if user_orders:
                response_text = "Here are your recent orders:"
                
                return {
                    "response": response_text,
                    "buttons": ["Main Menu"],  # Only show main menu for order list
                    "intent": intent,
                    "entities": entities,
                    "orders": user_orders,
                    "display_type": "order_grid"
                }
            else:
                return self._handle_with_gpt(
                    "I couldn't find any orders for your account. Would you like to check with a specific Order ID?",
                    "order_status", 
                    entities, 
                    session_id
                )

    def _handle_main_menu(self) -> Dict[str, Any]:
     """Return to main menu with home buttons while preserving chat history"""
    # Clear all context and state to start fresh, but preserve user data
     self.current_state = {}
     self.context = {
        'user_data': self.user_data  # Keep only user data
     }
    
    # Reset escalation counters
     self.response_count = 0
     self.escalation_offered = False
     self.escalation_pending = False
    
    # Clear purchase-related context to prevent bleed
     purchase_context_keys = ['current_products', 'last_search_query', 'in_purchase_flow', 
                           'awaiting_confirmation', 'transaction_type', 'transaction_reason',
                           'current_order', 'current_order_id', 'awaiting_reason', 'awaiting_order_id']
     for key in purchase_context_keys:
        self.context.pop(key, None)
    
     return {
        "response": "🏠 Main Menu - How can I help you today?",
        "buttons": ["Purchase Laptop", "Order Status", "Return/Cancel", "Warranty", "Technical Support"],
        "intent": "main_menu",
        "entities": {},
        "reset_context": True  # This flag tells the frontend to reset buttons/options but keep chat history
    }

    def _handle_order_id_response(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
     """Handle order ID response for transactions with grid view"""
     order_id = entities.get('order_id')
     if not order_id:
        # Try to extract order ID from message
        order_match = re.search(r'ORD-\d+', user_message, re.IGNORECASE)
        if order_match:
            order_id = order_match.group(0).upper()
            entities['order_id'] = order_id
    
     if order_id:
        self.context['current_order_id'] = order_id
        self.context['awaiting_order_id'] = False
        
        # Get order details
        order_details = self._get_order_info(order_id)
        if order_details:
            self.context['current_order'] = order_details
            
            # Check if we have a pending transaction to process
            transaction_type = self.context.get('transaction_type')
            
            # For warranty claims, show policies first before proceeding
            if transaction_type == 'warranty':
                # Show warranty policies and ask for confirmation to proceed
                policy_text = f"{self.warranty_policies['company']} - {self.warranty_policies['policy_type']}:\n\n"
                for i, policy in enumerate(self.warranty_policies['policy'], 1):
                    policy_text += f"{i}. {policy}\n"
                
                policy_text += "\nWould you like to proceed with your warranty claim?"
                
                # Set context for warranty confirmation
                self.context['awaiting_warranty_confirmation'] = True
                
                return {
                    "response": policy_text,
                    "buttons": ["Yes, proceed", "No, cancel"],
                    "intent": "warranty_policy",
                    "entities": entities,
                    "display_type": "policy_view"
                }
            
            # If no transaction type, just show order details
            # Return order details in grid view format
            orders = [order_details]
            
            # Generate response using GPT
            response_text = self._generate_order_response(order_details)
            
            buttons = ["Return", "Cancel", "Warranty", "Main Menu"]
            
            return {
                "response": response_text,
                "buttons": buttons,
                "intent": intent,
                "entities": entities,
                "orders": orders,
                "display_type": "order_grid"
            }
        
        else:
            return self._handle_with_gpt(
                f"Order {order_id} not found. Please check your Order ID and try again.",
                "order_status", 
                entities, 
                session_id
            )
    
     else:
        return self._handle_with_gpt(
            "I couldn't find an Order ID in your message. Please provide your Order ID (e.g., ORD-1234).",
            "order_status", 
            entities, 
            session_id
        )
    
    def _handle_tracking_request(self, order_id: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Handle order tracking request with detailed information"""
        # Get order details
        order_details = self._get_order_info(order_id)
        
        if not order_details:
            return self._handle_with_gpt(
                f"Order {order_id} not found. Please check your Order ID and try again.",
                "order_status", 
                entities, 
                session_id
            )
        
        # Generate tracking response using GPT
        response_text = self._generate_tracking_response(order_details)
        
        # Create detailed tracking information for display
        tracking_info = {
            "order_id": order_details.get('order_id', 'N/A'),
            "product_name": order_details.get('product_name', 'Unknown Product'),
            "price": f"¥{order_details.get('price', 0):,}",
            "carrier": order_details.get('carrier', 'Not specified'),
            "tracking_number": order_details.get('tracking_number', 'Not available'),
            "estimated_delivery": order_details.get('delivery_date', 'Not specified'),
            "order_date": order_details.get('order_date', 'Not specified'),
            "status": order_details.get('status', 'Unknown')
        }
        
        return {
            "response": response_text,
            "buttons": ["Order Status", "Main Menu", "Contact Support"],
            "intent": "order_tracking",
            "entities": entities,
            "tracking_info": tracking_info,
            "display_type": "tracking_details"
        }
    
    def _generate_tracking_response(self, order_details: Dict[str, Any]) -> str:
        """Generate tracking response using GPT"""
        try:
            prompt = f"""
            Order Tracking Details:
            - Order ID: {order_details.get('order_id', 'N/A')}
            - Product: {order_details.get('product_name', 'Unknown')}
            - Status: {order_details.get('status', 'Unknown')}
            - Carrier: {order_details.get('carrier', 'Not specified')}
            - Tracking Number: {order_details.get('tracking_number', 'Not available')}
            - Estimated Delivery: {order_details.get('delivery_date', 'Not specified')}
            - Order Date: {order_details.get('order_date', 'Not specified')}
            
            Create a friendly, informative response showing the tracking details to the user.
            Be clear and concise about the current status and next steps.
            If the order is not yet delivered, provide reassurance about the delivery timeline.
            Keep it to 3-4 sentences.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful customer service assistant. Be clear, informative, and reassuring about order status."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT tracking response error: {e}")
            # Fallback response
            status = order_details.get('status', 'Unknown')
            carrier = order_details.get('carrier', 'Not specified')
            tracking_num = order_details.get('tracking_number', 'Not available')
            delivery_date = order_details.get('delivery_date', 'Not specified')
            
            return f"Here are your tracking details for order {order_details.get('order_id', 'N/A')}:\n\nStatus: {status}\nCarrier: {carrier}\nTracking #: {tracking_num}\nEstimated Delivery: {delivery_date}"
    
    def _get_user_orders(self) -> List[Dict[str, Any]]:
        """Get all orders for the current user from Pinecone"""
        try:
            # Get customer ID from user data
            customer_id = self.user_data.get('customer_id') or f"CUST-{self.user_data.get('user_id', '0000')}"
            
            # Get orders from Pinecone
            results = self.order_manager.get_customer_orders(customer_id)
            
            orders = []
            if results and results.get('matches'):
                for match in results['matches']:
                    order_data = match['metadata']
                    
                    # Extract and format order information
                    order = {
                        "order_id": order_data.get('order_id', 'N/A'),
                        "product_name": order_data.get('product_name', 'Unknown Laptop'),
                        "price": self._safe_float(order_data.get('price'), 0),
                        "status": order_data.get('status', 'Unknown').lower().capitalize(),
                        "order_date": order_data.get('order_date', 'Unknown'),
                        "delivery_date": order_data.get('actual_delivery') or order_data.get('estimated_delivery', 'Unknown'),
                        "image_url": order_data.get('img_link', '')
                    }
                    
                    # Convert price to JPY
                    if order['price'] > 0:
                        order['price'] = round(order['price'] / self.yen_to_inr_rate)
                        order['currency'] = 'JPY'
                        order['currency_symbol'] = '¥'
                    
                    orders.append(order)
            
            # If no orders found in Pinecone, return some sample data
            if not orders:
                return self._get_sample_orders()
            
            return orders
            
        except Exception as e:
            print(f"Error getting user orders from Pinecone: {e}")
            # Fallback to sample data
            return self._get_sample_orders()
        
    def _get_sample_orders(self) -> List[Dict[str, Any]]:
        """Get sample orders for demonstration"""
        orders = [
            {
                "order_id": "ORD-1001",
                "product_name": "HP Pavilion Gaming Laptop",
                "price": 89900,
                "status": "Delivered",
                "order_date": "2023-10-15",
                "delivery_date": "2023-10-20",
                "image_url": "https://images.unsplash.com/photo-1587614382346-4ec70e388b28?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80"
            },
            {
                "order_id": "ORD-1002",
                "product_name": "Dell XPS 13",
                "price": 124900,
                "status": "Processing",
                "order_date": "2023-11-05",
                "delivery_date": "2023-11-12",
                "image_url": "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80"
            }
        ]
        
        # Convert prices to JPY
        for order in orders:
            if 'price' in order:
                order['price'] = round(order['price'] / self.yen_to_inr_rate)
                order['currency'] = 'JPY'
                order['currency_symbol'] = '¥'
        
        return orders

    def _handle_color_inquiry(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Handle color inquiries about currently displayed products"""
        current_products = self.context.get('current_products', [])
        
        if not current_products:
            return self._handle_with_gpt(user_message, intent, entities, session_id)
        
        # Extract color from message
        color_entities = self._extract_color_from_message(user_message)
        
        # Check each product for color information
        products_with_colors = []
        products_without_colors = []
        
        for product in current_products:
            colors = product.get('colors', 'Not specified')
            if colors and colors != 'Not specified' and colors != 'N/A':
                products_with_colors.append(product)
            else:
                products_without_colors.append(product)
        
        # Generate response based on available color information
        if products_with_colors:
            response_text = self._generate_color_response(products_with_colors, color_entities, user_message)
        else:
            response_text = self._generate_no_color_response(current_products, user_message)
        
        buttons = self._generate_context_buttons("color inquiry", current_products)
        
        # Add main menu button
        buttons.append("Main Menu")
        
        return {
            "response": response_text,
            "buttons": buttons,
            "intent": intent,
            "entities": entities,
            "products": current_products,
            "display_type": "product_grid"
        }

    def _extract_color_from_message(self, message: str) -> List[str]:
        """Extract color mentions from user message"""
        colors = ['blue', 'red', 'black', 'silver', 'gray', 'white', 'gold', 'pink', 'green']
        found_colors = []
        
        message_lower = message.lower()
        for color in colors:
            if color in message_lower:
                found_colors.append(color)
        
        return found_colors

    def _generate_color_response(self, products: List[Dict], requested_colors: List[str], user_message: str) -> str:
        """Generate response about product colors using GPT"""
        try:
            product_info = []
            for product in products:
                colors = product.get('colors', 'Not specified')
                product_info.append(f"{product['brand']} {product['name']} - Available colors: {colors}")
            
            product_list = "\n".join(product_info)
            
            prompt = f"""
            User asked: "{user_message}"
            They are asking about color availability for these products:
            
            {product_list}
            
            Requested colors: {', '.join(requested_colors) if requested_colors else 'Any colors'}
            
            Create a helpful response that:
            1. Tells them what colors are available for each product
            2. Is specific about the color options
            3. Helps them make a decision
            4. Is friendly and conversational
            
            Keep it to 3-4 sentences maximum.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful shopping assistant. Be specific about product colors and help users make informed decisions."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT color response error: {e}")
            # Fallback response
            response_lines = []
            for product in products:
                colors = product.get('colors', 'Not specified')
                response_lines.append(f"{product['brand']} {product['name']}: {colors}")
            
            return f"Here are the available colors:\n" + "\n".join(response_lines)

    def _generate_no_color_response(self, products: List[Dict], user_message: str) -> str:
        """Generate response when no color information is available"""
        try:
            product_names = [f"{p['brand']} {p['name']}" for p in products]
            
            prompt = f"""
            User asked: "{user_message}"
            They are asking about color availability for these products: {', '.join(product_names)}
            
            Unfortunately, color information is not available for these specific models.
            
            Create a helpful, empathetic response that:
            1. Explains that color information isn't available
            2. Suggests they check the product details page for more information
            3. Offers to help with other questions about the products
            4. Is friendly and understanding
            
            Keep it to 2-3 sentences.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful shopping assistant. Be empathetic when information isn't available."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=120
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT no color response error: {e}")
            return "I don't have specific color information for these models. You might want to check the product details page for available color options."

    
    def _understand_with_gpt(self, user_message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Use GPT to comprehensively understand user message with context"""
        try:
            # Check for order ID pattern first (fast, rule-based detection)
            order_match = re.search(r'ORD[_-]?\d+', user_message, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(0).upper().replace('_', '-')
                # Ensure proper ORD- format
                if not order_id.startswith('ORD-'):
                    order_id = order_id.replace('ORD', 'ORD-')
                
                return {
                    "intent": "order_status",
                    "entities": {"order_id": order_id}
                }
            
            # Improved brand detection - check for brands in natural language
            brands = ['acer', 'hp', 'lenovo', 'dell', 'apple', 'asus', 'infinix', 'msi', 'realme', 'redmi', 'gigabyte', 'samsung', 'avita', 'redmibook']
            user_message_lower = user_message.lower()
            
            print(f"🔍 Checking message for brands: '{user_message_lower}'")
            print(f"🔍 Brands to check: {brands}")
            
            # Check if any brand is mentioned in the message
            detected_brand = None
            for brand in brands:
                if brand in user_message_lower:
                    detected_brand = brand
                    print(f"✅ Brand detected: {detected_brand}")
                    break
            
            # If brand detected, return product inquiry intent
            if detected_brand:
                print(f"🎯 Returning product_inquiry for brand: {detected_brand}")
                return {
                    "intent": "product_inquiry",
                    "entities": {"brand": detected_brand}
                }
            else:
                print("❌ No brand detected in message")
            
            # If no brand found, use GPT for comprehensive understanding
            prompt = f"""
            Analyze this user message in the context of an e-commerce laptop store conversation:
            
            Current Context: {json.dumps(context, default=str) if context else 'No context'}
            User Message: "{user_message}"
            
            Your task is to understand the user's intent and extract relevant information.
            
            IMPORTANT: The user is speaking in Japanese Yen (¥). Extract any price amounts and 
            note that they are in JPY. Also look for yen symbols (¥) or words like 'yen'.
            
            Also detect the type of budget constraint:
            - "under 50000", "below 50000", "less than 50000" → below
            - "over 50000", "above 50000", "more than 50000" → above  
            - "around 50000", "about 50000", "50000" → around
            
            Possible Intents:
            - product_inquiry: Looking for laptops, asking about products, searching
            - specific_product: Asking about specific brand/model (Dell, HP, etc.)
            - product_comparison: Comparing products, asking which is better
            - order_status: Asking about order tracking, status, delivery
            - return_request: Wanting to return a product
            - cancellation_request: Wanting to cancel an order
            - warranty_claim: Warranty issues, repairs
            - technical_support: Technical problems, setup help
            - color_inquiry: Asking about available colors
            - budget_inquiry: Asking about prices, budget options
            - feature_inquiry: Asking about specific features (RAM, storage, etc.)
            - greeting: Hello, hi, etc.
            - goodbye: Bye, thanks, etc.
            - general_question: Other questions
            
            Entities to extract:
            - brand: dell, hp, lenovo, apple, etc.
            - max_price: budget amount (in JPY - look for ¥, yen, 円)
            - ram: 8gb, 16gb, etc.
            - storage: 256gb, 1tb, ssd, hdd
            - color: blue, red, black, silver, etc.
            - order_id: ORD-1234 format
            - reason: reason for return/cancellation
            - product_model: specific model names
            
            Return JSON format: {{"intent": "detected_intent", "entities": {{"entity1": "value1", "entity2": "value2"}}}}
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert at understanding e-commerce conversations. Be accurate and extract all relevant information. Note that prices are in JPY."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            
            # Ensure proper format
            if 'intent' not in result:
                result['intent'] = 'general_question'
            if 'entities' not in result:
                result['entities'] = {}
                
            # Convert JPY budget to INR max_price for Pinecone search
            if 'max_price' in result['entities']:
                jpy_price = result['entities']['max_price']
                # Convert JPY to INR for Pinecone search
                inr_price = float(jpy_price) * self.yen_to_inr_rate
                result['entities']['max_price_inr'] = inr_price
                print(f"💰 Currency conversion: ¥{jpy_price} JPY → ₹{inr_price:.2f} INR")
                
            print(f"🤖 GPT Understanding - Intent: {result['intent']}, Entities: {result['entities']}")
            return result
            
        except Exception as e:
            print(f"GPT understanding error: {e}")
            return {"intent": "general_question", "entities": {}}

    def _parse_budget_constraints(self, budget_text: str) -> Dict[str, Any]:
        """Parse budget text and return constraints with type - IMPROVED"""
        if not budget_text:
            return None
            
        budget_text = str(budget_text).lower()
        
        constraints = {
            'min_price': None,
            'max_price': None,
            'constraint_type': 'around',
            'max_price_jpy': float('inf'),
            'min_price_jpy': 0,
            'target_price_jpy': 0
        }
        
        # Extract numbers with proper handling for "k" (thousands)
        numbers = re.findall(r'(\d+\.?\d*)\s*k', budget_text)
        if numbers:
            # Handle "k" suffix (e.g., 80k = 80,000)
            amount = float(numbers[0]) * 1000
        else:
            # Extract regular numbers
            numbers = re.findall(r'\d+', budget_text)
            if not numbers:
                return constraints
            amount = float(numbers[0])
        
        # Convert JPY to INR for Pinecone search
        inr_amount = amount * self.yen_to_inr_rate
        
        # Determine constraint type with more precise matching
        if any(word in budget_text for word in ['under', 'below', 'less than', 'upto', 'max', 'maximum', 'at most']):
            constraints['max_price'] = inr_amount
            constraints['max_price_jpy'] = amount
            constraints['constraint_type'] = 'below'
            print(f"💰 Strict budget: UNDER ¥{amount:,} JPY (₹{inr_amount:.0f} INR)")
            
        elif any(word in budget_text for word in ['over', 'above', 'more than', 'minimum', 'at least']):
            constraints['min_price'] = inr_amount
            constraints['min_price_jpy'] = amount
            constraints['constraint_type'] = 'above'
            print(f"💰 Strict budget: OVER ¥{amount:,} JPY (₹{inr_amount:.0f} INR)")
            
        elif any(word in budget_text for word in ['around', 'about', 'approximately', '~', 'avg', 'average']):
            # Create a range around the amount (±20%)
            constraints['min_price'] = inr_amount * 0.8
            constraints['max_price'] = inr_amount * 1.2
            constraints['min_price_jpy'] = amount * 0.8
            constraints['max_price_jpy'] = amount * 1.2
            constraints['target_price_jpy'] = amount
            constraints['constraint_type'] = 'around'
            print(f"💰 Flexible budget: AROUND ¥{amount:,} JPY (₹{inr_amount:.0f} INR ±20%)")
            
        else:
            # Default to "below" if no specific constraint words but numbers present
            constraints['max_price'] = inr_amount
            constraints['max_price_jpy'] = amount
            constraints['constraint_type'] = 'below'
            print(f"💰 Default budget: UNDER ¥{amount:,} JPY (₹{inr_amount:.0f} INR)")
        
        return constraints

    def _handle_purchase_flow(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Handle purchase flow with proper budget constraints"""
        # Use GPT to create the best search query
        search_query = self._create_search_query_with_gpt(user_message, self.context)
        print(f"🔍 GPT-generated search query: '{search_query}'")
        
        # Store the search context
        self.context['last_search_query'] = search_query
        
        # Extract budget constraints
        budget_constraints = None
        if 'max_price' in entities:
            budget_text = entities.get('max_price', '')
            budget_constraints = self._parse_budget_constraints(budget_text)
        
        # Get product recommendations with proper price filtering
        recommendations = self._get_product_recommendations(search_query, budget_constraints)
        
        if recommendations and recommendations.get('products'):
            products = recommendations['products']
            self.context['current_products'] = products
            
            # Convert product prices to JPY for display (they should already be in JPY)
            jpy_products = products  # Already in JPY
            
            # Generate natural response using GPT
            response_text = self._generate_product_response(jpy_products, search_query, user_message)
            
            # Context-aware buttons
            buttons = self._generate_context_buttons(search_query, jpy_products)
            
            # Add main menu button
            buttons.append("Main Menu")
            
            return {
                "response": response_text,
                "buttons": buttons,
                "intent": intent,
                "entities": entities,
                "products": jpy_products,
                "display_type": "product_grid"
            }
        else:
            # Let GPT handle the no products found scenario
            return self._handle_no_products_with_gpt(search_query, user_message, intent, entities)

    def _convert_prices_to_jpy(self, products: List[Dict]) -> List[Dict]:
        """Convert product prices from INR to JPY for display"""
        jpy_products = []
        for product in products:
            jpy_product = product.copy()
            if 'price' in jpy_product:
                # Convert INR to JPY (1 INR = 1.67 JPY approx)
                inr_price = jpy_product['price']
                jpy_price = inr_price / self.yen_to_inr_rate
                jpy_product['price'] = round(jpy_price)
                jpy_product['original_price_inr'] = inr_price  # Keep original for reference
            jpy_products.append(jpy_product)
        return jpy_products

    def _create_search_query_with_gpt(self, user_message: str, context: Dict[str, Any]) -> str:
        """Use GPT to create the best search query from user message"""
        try:
            prompt = f"""
            Analyze this user message about laptop purchase and extract ONLY the key search terms:
            
            User Message: "{user_message}"
            
            IMPORTANT: The user is speaking in Japanese Yen (¥). If they mention prices, 
            extract the numerical value but remove currency symbols and words.
            
            Extract the most important 2-4 keywords for product search. Focus on:
            - Brand names (HP, Dell, Lenovo, Apple, Asus, Acer, Infinix, MSI, Realme, Redmi, Gigabyte, Samsung, Avita, RedmiBook, etc.)
            - Processor types (Intel, AMD Ryzen, Core i5, etc.)
            - Budget hints (under 40000, around 50000, etc.) - remove ¥ and yen
            - Usage types (gaming, business, student)
            - Color preferences (blue, black, silver, etc.)
            
            Return ONLY the keywords separated by spaces, no additional text.
            
            Examples:
            - "hp amd ryzen" for "I want HP laptop with AMD Ryzen for ¥50000"
            - "dell intel i5 40000" for "Dell with Intel i5 under ¥40000"
            - "gaming laptop" for "I need a gaming laptop for 60000 yen"
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an expert at extracting search keywords from user queries. Remove currency symbols and return only the keywords without any additional text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=30
            )
            
            search_query = response.choices[0].message.content.strip()
            
            # Remove any quotes and clean up
            search_query = search_query.replace('"', '').replace("'", "").replace(".", "").strip()
            
            print(f"🤖 GPT extracted keywords: '{search_query}'")
            return search_query
            
        except Exception as e:
            print(f"GPT query generation error: {e}")
            # Fallback: use the original message but remove common words and currency symbols
            common_words = ['i', 'want', 'a', 'laptop', 'with', 'for', 'under', 'around', 'about', 'color', 'colour', '¥', 'yen', '円']
            words = [word for word in user_message.lower().split() if word not in common_words and not word.isdigit()]
            return ' '.join(words) or "laptop"

    def _get_product_recommendations(self, search_query: str, budget_constraints: Dict[str, Any] = None) -> Dict[str, Any]:
        """Get product recommendations with proper price filtering"""
        try:
            print(f"🔍 Search for: '{search_query}' with constraints: {budget_constraints}")
            
            # First try: Semantic search (without price filters since Pinecone doesn't support min_price)
            results = self.product_manager.search_products(
                query=search_query,
                top_k=50,
                max_price=None  # Don't use max_price here, we'll filter manually
            )
            
            products = []
            
            if results and results.get('matches'):
                print(f"📊 Found {len(results['matches'])} potential matches")
                
                for i, match in enumerate(results['matches']):
                    if match['score'] > 0.1:  # Reasonable threshold
                        product = match['metadata']
                        
                        try:
                            product_data = self._extract_product_data(product, match)
                            
                            if product_data and product_data['price'] > 0:
                                # Apply STRICT manual price filtering based on constraint type
                                jpy_price = product_data['price']  # Already in JPY
                                
                                if budget_constraints:
                                    constraint_type = budget_constraints.get('constraint_type', 'around')
                                    max_jpy = budget_constraints.get('max_price_jpy', float('inf'))
                                    min_jpy = budget_constraints.get('min_price_jpy', 0)
                                    
                                    # STRICT filtering based on constraint type
                                    if constraint_type == 'below' and jpy_price > max_jpy:
                                        print(f"❌ Filtered out: {product_data['name']} - ¥{jpy_price:,} (above max ¥{max_jpy:,})")
                                        continue
                                    elif constraint_type == 'above' and jpy_price < min_jpy:
                                        print(f"❌ Filtered out: {product_data['name']} - ¥{jpy_price:,} (below min ¥{min_jpy:,})")
                                        continue
                                    elif constraint_type == 'around':
                                        # For "around", allow ±20% range
                                        lower_bound = min_jpy * 0.8
                                        upper_bound = max_jpy * 1.2
                                        if jpy_price < lower_bound or jpy_price > upper_bound:
                                            print(f"❌ Filtered out: {product_data['name']} - ¥{jpy_price:,} (outside range ¥{lower_bound:.0f}-{upper_bound:.0f})")
                                            continue
                                
                                products.append(product_data)
                                print(f"✅ Product {i+1}: {product_data['brand']} {product_data['name']} - ¥{jpy_price:,}")
                                
                        except Exception as e:
                            print(f"⚠️ Error processing product {i+1}: {e}")
                            continue
                
                # If semantic search found good results, use them
                if products:
                    # Sort based on constraint type
                    if budget_constraints:
                        constraint_type = budget_constraints.get('constraint_type', 'around')
                        if constraint_type == 'below':
                            products.sort(key=lambda x: (-x['price'], -x['rating']))  # Highest first within budget
                        elif constraint_type == 'above':
                            products.sort(key=lambda x: (x['price'], -x['rating']))  # Lowest first above threshold
                        else:  # around
                            target_price = budget_constraints.get('target_price_jpy', 0)
                            products.sort(key=lambda x: (abs(x['price'] - target_price), -x['rating']))  # Closest to target
                    else:
                        products.sort(key=lambda x: (-x['score'], -x['rating']))
                    
                    top_products = products[:6]
                    print(f"🎯 Returning {len(top_products)} products with proper price filtering")
                    return {
                        'type': 'product_recommendations',
                        'products': top_products,
                        'count': len(products)
                    }
            
            # If no products found with strict filtering, try metadata-based search
            print("🔄 Trying metadata-based search with strict price filtering...")
            return self._metadata_based_search(search_query, budget_constraints)
                
        except Exception as e:
            print(f"❌ Product recommendation error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _metadata_based_search(self, search_query: str, budget_constraints: Dict[str, Any] = None) -> Dict[str, Any]:
        """Fallback search using metadata filtering with proper price constraints"""
        try:
            # Extract keywords from query
            query_lower = search_query.lower()
            
            # Build filter based on query keywords
            filter_dict = {}
            
            # Brand detection - FIXED: Handle all capitalization variations
            brands = ['dell', 'hp', 'lenovo', 'apple', 'asus', 'acer', 
                     'infinix', 'msi', 'realme', 'redmi','gigabyte', 'samsung',
                      'avita', 'redmibook']
            detected_brand = None
            for brand in brands:
                if brand in query_lower:
                    detected_brand = brand
                    break
            
            if detected_brand:
                # Handle ALL capitalization variations in Pinecone
                # Create OR filter for all possible capitalizations
                brand_variations = [
                    detected_brand.upper(),      # APPLE, HP, LENOVO
                    detected_brand.capitalize(), # Apple, Hp, Lenovo  
                    detected_brand.lower(),      # apple, hp, lenovo
                ]
                
                # Remove duplicates
                brand_variations = list(set(brand_variations))
                
                print(f"🏷️  Brand variations to search: {brand_variations}")
                
                # Create OR filter for all variations
                filter_dict = {
                    "$or": [
                        {"brand": {"$eq": variation}} for variation in brand_variations
                    ]
                }
                print(f"🔍 Using metadata filter: {filter_dict}")
            
            # If no filters detected, return None
            if not filter_dict:
                print("❌ No metadata filters could be applied")
                return None
            
            print(f"🔍 Using metadata filter: {filter_dict}")
            
            # Execute metadata-based search
            results = self.product_manager.index.query(
                vector=[0.0] * 1536,  # Zero vector for metadata-only search
                top_k=20,
                include_metadata=True,
                filter=filter_dict
            )
            
            if results and results.get('matches'):
                products = []
                for match in results['matches']:
                    product = match['metadata']
                    try:
                        product_data = self._extract_product_data(product, match)
                        if product_data and product_data['price'] > 0:
                            # Manual price filtering based on constraint type
                            jpy_price = product_data['price']  # Already in JPY
                            
                            if budget_constraints:
                                constraint_type = budget_constraints.get('constraint_type')
                                max_jpy = budget_constraints.get('max_price_jpy', float('inf'))
                                min_jpy = budget_constraints.get('min_price_jpy', 0)
                                
                                # STRICT filtering based on constraint type
                                if constraint_type == 'below' and jpy_price > max_jpy:
                                    print(f"❌ Filtered out: {product_data['name']} - ¥{jpy_price:,} (above max ¥{max_jpy:,})")
                                    continue
                                elif constraint_type == 'above' and jpy_price < min_jpy:
                                    print(f"❌ Filtered out: {product_data['name']} - ¥{jpy_price:,} (below min ¥{min_jpy:,})")
                                    continue
                                elif constraint_type == 'around':
                                    # For "around", allow ±20% range
                                    lower_bound = min_jpy * 0.8
                                    upper_bound = max_jpy * 1.2
                                    if jpy_price < lower_bound or jpy_price > upper_bound:
                                        print(f"❌ Filtered out: {product_data['name']} - ¥{jpy_price:,} (outside range ¥{lower_bound:.0f}-{upper_bound:.0f})")
                                        continue
                                    
                            products.append(product_data)
                            print(f"✅ Metadata product: {product_data['brand']} {product_data['name']} - ¥{jpy_price:,}")
                    except Exception as e:
                        continue
                
                if products:
                    # Sort based on constraint type
                    if budget_constraints:
                        constraint_type = budget_constraints.get('constraint_type', 'around')
                        if constraint_type == 'below':
                            products.sort(key=lambda x: (-x['price'], -x['rating']))  # Highest first within budget
                        elif constraint_type == 'above':
                            products.sort(key=lambda x: (x['price'], -x['rating']))  # Lowest first above threshold
                        else:  # around
                            target_price = budget_constraints.get('target_price_jpy', 0)
                            products.sort(key=lambda x: (abs(x['price'] - target_price), -x['rating']))  # Closest to target
                    else:
                        products.sort(key=lambda x: (-x['rating'], x['price']))
                        
                    print(f"🎯 Returning {min(6, len(products))} products from metadata search")
                    return {
                        'type': 'product_recommendations',
                        'products': products[:6],
                        'count': len(products),
                        'metadata_search': True
                    }
            
            return None
            
        except Exception as e:
            print(f"❌ Metadata search error: {e}")
            return None

    def _extract_product_data(self, product: Dict[str, Any], match: Dict[str, Any]) -> Dict[str, Any]:
        """Extract product data including color information"""
        try:
            # Extract colors from metadata - handle different possible field names
            colors = product.get('colors') or product.get('color') or product.get('available_colors') or 'Not specified'
            
            # Clean up color data
            if colors and colors != 'Not specified':
                # Remove any unwanted characters and standardize
                colors = colors.replace('"', '').replace("'", "").replace("[", "").replace("]", "").strip()
            
            # Convert price to Yen for display
            inr_price = self.product_manager._safe_float(product.get('price'))
            jpy_price = round(inr_price / self.yen_to_inr_rate) if inr_price else 0
            
            product_data = {
                'id': product.get('product_id') or product.get('id') or f"prod-{match['id']}",
                'name': product.get('name', 'Unknown Laptop'),
                'price': jpy_price,  # Store in JPY for display
                'original_price_inr': inr_price,  # Keep original for reference
                'ram': product.get('ram', 'Not specified'),
                'processor': product.get('processor', 'Not specified'),
                'storage': product.get('storage', 'Not specified'),
                'rating': self.product_manager._safe_float(product.get('rating'), 4.0),
                'reviews': self.product_manager._safe_int(product.get('no_of_reviews') or product.get('no_of_ratings')),
                'image_url': product.get('img_link', ''),
                'brand': product.get('brand', 'Unknown'),
                'colors': colors,
                'description': f"{product.get('processor', '')} • {product.get('ram', '')} • {product.get('storage', '')}",
                'score': match.get('score', 0),
                'currency': 'JPY',  # Add currency indicator
                'currency_symbol': '¥'  # Add currency symbol
            }
            
            # Add OS information if available
            if product.get('os'):
                product_data['description'] += f" • {product.get('os')}"
            
            # Ensure we have valid data
            if product_data['price'] <= 0:
                return None
                
            return product_data
            
        except Exception as e:
            print(f"❌ Error extracting product data: {e}")
            return None

    def _generate_product_response(self, products: List[Dict], search_query: str, user_message: str) -> str:
        """Generate natural product response using GPT"""
        try:
            product_info = []
            for product in products[:6]:
                color_info = f" - Colors: {product['colors']}" if product.get('colors') and product['colors'] != 'Not specified' else ""
                product_info.append(f"{product['brand']} {product['name']} - ¥{product['price']:,}{color_info}")
            
            product_list = "\n".join(product_info)
            
            prompt = f"""
            User asked: "{user_message}"
            Search query used: "{search_query}"
            Products found: {product_list}
            
            Create a friendly, helpful response showing these products to the user.
            Be natural and conversational. Mention you found these based on their request.
            If color information is available, include it in the response.
            Display prices in Japanese Yen (¥) format.
            Keep it to 2-3 sentences maximum.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful shopping assistant. Be friendly, concise, and include color information when available. Display prices in Japanese Yen with ¥ symbol."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=120
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT product response error: {e}")
            return f"I found {len(products)} laptops matching your search. Here are the best options:"

    def _generate_context_buttons(self, search_query: str, products: List[Dict]) -> List[str]:
        """Generate context-aware buttons based on search query"""
        query_lower = search_query.lower()
        buttons = []
        
        # Brand-specific buttons
        brands = ['dell', 'hp', 'lenovo', 'apple', 'asus', 'acer']
        for brand in brands:
            if brand in query_lower:
                buttons.extend([f"{brand.upper()} Colors", f"{brand.upper()} Under ¥50000", f"{brand.upper()} 16GB RAM"])
                break
        
        # Feature buttons
        if 'ram' in query_lower:
            buttons.extend(["8GB RAM", "16GB RAM", "32GB RAM"])
        if 'ssd' in query_lower or 'storage' in query_lower:
            buttons.extend(["256GB SSD", "512GB SSD", "1TB SSD"])
        if any(word in query_lower for word in ['price', 'budget', 'under', '¥', 'yen']):
            buttons.extend(["Under ¥50000", "Under ¥80000", "Under ¥100000"])
        
        # Color buttons if color was mentioned
        colors = ['blue', 'red', 'black', 'silver', 'gray', 'white']
        for color in colors:
            if color in query_lower:
                buttons.extend([f"{color.title()} Laptops", f"{color.title()} Options"])
                break
        
        # Default buttons
        default_buttons = ["Gaming Laptops", "Business Laptops", "Student Laptops", "All Brands"]
        buttons.extend(default_buttons)
        
        return list(set(buttons))[:8]  # Remove duplicates and limit

    def _handle_no_products_with_gpt(self, search_query: str, user_message: str, intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Handle no products found with more specific, positive responses"""
        
        # Analyze the search query to provide more targeted suggestions
        query_lower = search_query.lower()
        
        if any(word in query_lower for word in ['gaming', 'game', 'gamer']):
            response_text = "Looking for a gaming laptop? Great choice! Could you tell me your budget range and any specific features you'd like, like graphics card or screen size?"
            buttons = ["Under ¥80000", "Under ¥120000", "RTX Graphics", "16GB RAM", "ASUS ROG", "MSI Gaming"]
        
        elif any(word in query_lower for word in ['business', 'work', 'office']):
            response_text = "For business use, I recommend looking at reliable brands with good battery life. What's your budget and do you need specific features like lightweight design or long battery life?"
            buttons = ["Under ¥60000", "Lightweight", "Long Battery", "Dell Latitude", "HP EliteBook", "Lenovo ThinkPad"]
        
        elif any(word in query_lower for word in ['student', 'school', 'college']):
            response_text = "Perfect for student life! What's your budget range? Student laptops usually offer great value with good performance for studying and entertainment."
            buttons = ["Under ¥50000", "Under ¥40000", "Portable", "Good Battery", "Chromebooks", "2-in-1 Laptops"]
        
        elif any(word in query_lower for word in ['budget', 'cheap', 'affordable', 'price']):
            response_text = "Looking for a great value laptop? I can help! What's your maximum budget and what will you mainly use it for?"
            buttons = ["Under ¥40000", "Under ¥50000", "Basic Use", "Web Browsing", "Study", "Entertainment"]
        
        else:
            # Generic positive response for other cases
            response_text = "I'd love to help you find the perfect laptop! Could you tell me more about what you're looking for? For example:\n• Your budget range\n• Preferred brand\n• What you'll use it for\n• Any specific features you need"
            buttons = ["Gaming", "Business", "Student", "Under ¥50000", "Dell", "HP", "Apple"]
        
        return {
            "response": response_text,
            "buttons": buttons,
            "intent": intent,
            "entities": entities
        }
    
    def _handle_transaction_intent(self, intent: str, entities: Dict[str, Any], message: str, session_id: str) -> Dict[str, Any]:
     """Handle return, cancellation, or warranty intent"""
    # Check if order ID is already provided
     order_id = entities.get('order_id') or self.context.get('current_order_id')
    
    # Set transaction type based on intent
     if intent == "cancellation_request":
        transaction_type = 'cancellation'
     elif intent == "return_request":
        transaction_type = 'return'
     elif intent == "warranty_claim":
        transaction_type = 'warranty'
     else:
        transaction_type = None
    
     if transaction_type:
        self.context['transaction_type'] = transaction_type
    
     if order_id:
        # Get order details
        order_details = self._get_order_info(order_id)
        if order_details:
            self.context['current_order'] = order_details
            self.context['current_order_id'] = order_id
            
            # Check if order can be processed based on status
            status = order_details.get('status', '').lower()
            
            if transaction_type == 'cancellation':
                if status == 'delivered':
                    return self.response_generator.generate_response(
                        "cancellation_request", entities, self.context,
                        {"message": "This order has already been delivered. Cancellation is not possible for delivered orders. Would you like to initiate a return instead?"}
                    )
                else:
                    # Show order details first, then ask for reason
                    return self._show_order_and_ask_for_reason(order_details, "cancellation", entities, session_id)
            
            elif transaction_type == 'return':
                if status != 'delivered':
                    return self.response_generator.generate_response(
                        intent, entities, self.context,
                        {"message": f"This order has status: {status}. Returns are only possible for delivered items."}
                    )
                else:
                    # Show order details first, then ask for reason
                    return self._show_order_and_ask_for_reason(order_details, "return", entities, session_id)
            
            elif transaction_type == 'warranty':
                if status != 'delivered':
                    return self.response_generator.generate_response(
                        intent, entities, self.context,
                        {"message": f"This order has status: {status}. Warranty claims are only possible for delivered items."}
                    )
                else:
                    # For warranty, show order details first, then ask for reason
                    return self._show_order_and_ask_for_reason(order_details, "warranty", entities, session_id)
        
        else:
            # Order not found - let GPT handle this response
            return self._handle_with_gpt(
                f"Order {order_id} not found. Please check your Order ID and try again.",
                "order_status", 
                entities, 
                session_id
            )
    
     else:
        # Ask for order ID
        self.context['awaiting_order_id'] = True
        
        # Let GPT generate the order ID request message
        prompt = f"""
        The user wants to initiate a {transaction_type} but hasn't provided an order ID.
        
        Create a friendly, helpful message asking for their order ID.
        Be clear about what information you need and why.
        Keep it to 1-2 sentences.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful customer service assistant. Be clear and friendly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=80
            )
            
            message_text = response.choices[0].message.content.strip()
            
            return self.response_generator.generate_response(
                intent, entities, self.context,
                {"message": message_text}
            )
            
        except Exception as e:
            print(f"GPT order ID request error: {e}")
            return self.response_generator.generate_response(
                intent, entities, self.context,
                {"message": f"I can help with your {transaction_type}. Please provide your Order ID."}
            )
        
    def _show_order_and_ask_for_reason(self, order_details: Dict[str, Any], transaction_type: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
     """Show order details and ask for reason"""
    # Return order details in grid view format
     orders = [order_details]
    
    # Generate response using GPT
     response_text = self._generate_order_response(order_details)
    
    # Set context to ask for reason
     self.context['awaiting_reason'] = True
    
     buttons = ["Battery issues", "Screen problems", "Performance issues", "Hardware failure", "Software problems", "Other"]
    
     return {
        "response": response_text,
        "buttons": buttons,
        "intent": f"{transaction_type}_request",
        "entities": entities,
        "orders": orders,
        "display_type": "order_grid"
    }
    
    def _ask_for_confirmation(self, transaction_type: str, order_details: Dict[str, Any], reason: str) -> Dict[str, Any]:
     """Ask for confirmation of transaction"""
     product_name = order_details.get('product_name', 'the product')
     price = order_details.get('price', 0)
     currency_symbol = order_details.get('currency_symbol', '¥')
    
     prompt = f"""
     The user wants to {transaction_type} their product: {product_name}
     Reason: {reason}
     Refund amount: {currency_symbol}{price:,} (if applicable)
    
     Create a clear confirmation message asking them to confirm the {transaction_type}.
     Be specific about what they're confirming.
     Include the reason and refund amount if applicable.
     Ask them to confirm with 'yes' or 'no'.
     """
    
     try:
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful customer service assistant. Be clear and specific."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=100
        )
        
        message_text = response.choices[0].message.content.strip()
        
        return self.response_generator.generate_response(
            f"{transaction_type}_request", {}, self.context,
            {
                "message": message_text,
                "requires_confirmation": True
            }
        )
        
     except Exception as e:
        print(f"GPT confirmation request error: {e}")
        
        if transaction_type == 'cancellation':
            message = f"Confirm cancellation for {product_name}?\nReason: {reason}\nRefund amount: {currency_symbol}{price:,}\n\nPlease confirm with 'yes' or 'no'."
        elif transaction_type == 'return':
            message = f"Confirm return for {product_name}?\nReason: {reason}\nRefund amount: {currency_symbol}{price:,}\n\nPlease confirm with 'yes' or 'no'."
        else:  # warranty
            message = f"Confirm warranty claim for {product_name}?\nReason: {reason}\n\nPlease confirm with 'yes' or 'no'."
        
        return self.response_generator.generate_response(
            f"{transaction_type}_request", {}, self.context,
            {
                "message": message,
                "requires_confirmation": True
            }
        )

    def _generate_order_response(self, order_details: Dict[str, Any]) -> str:
        """Generate order response using GPT"""
        try:
            prompt = f"""
            Order Details:
            - Order ID: {order_details.get('order_id', 'N/A')}
            - Product: {order_details.get('product_name', 'Unknown')}
            - Status: {order_details.get('status', 'Unknown')}
            - Price: ¥{order_details.get('price', 0):,}
            - Order Date: {order_details.get('order_date', 'Unknown')}
            
            Create a friendly response showing the order details to the user.
            Be clear and concise.
            Display the price in Japanese Yen with ¥ symbol.
            Keep it to 2-3 sentences.
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful customer service assistant. Be clear and friendly."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=100
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT order response error: {e}")
            return f"Here are your order details for {order_details.get('order_id', 'the order')}:"

    def _ask_for_reason(self, transaction_type: str) -> Dict[str, Any]:
        """Ask user for reason for transaction"""
        reasons = self.transaction_service.get_reasons(transaction_type)
        
        # Let GPT generate the reason request message
        prompt = f"""
        The user wants to initiate a {transaction_type} and you need to ask for the reason.
        
        Available reasons: {', '.join(reasons)}
        
        Create a friendly, clear message asking them to select a reason from the list.
        Present the reasons in a helpful way.
        Keep it to 2-3 sentences.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful customer service assistant. Be clear and organized."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=100
            )
            
            message_text = response.choices[0].message.content.strip()
            
            return self.response_generator.generate_response(
                f"{transaction_type}_request", {}, self.context,
                {
                    "message": message_text,
                    "reasons": reasons
                }
            )
            
        except Exception as e:
            print(f"GPT reason request error: {e}")
            reason_text = "\n".join([f"{i+1}. {reason}" for i, reason in enumerate(reasons)])
            
            return self.response_generator.generate_response(
                f"{transaction_type}_request", {}, self.context,
                {
                    "message": f"Please select the reason for {transaction_type}:\n\n{reason_text}",
                    "reasons": reasons
                }
            )

    def _handle_reason_response(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
     """Handle reason response for transactions"""
     transaction_type = self.context.get('transaction_type')
     order_details = self.context.get('current_order')
    
     if not order_details:
        return self._handle_with_gpt(
            "I'm not sure which order you're referring to. Please provide your Order ID again.",
            "unknown", 
            entities, 
            session_id
        )
    
    # Get the reason and map it to valid reasons using the new mapping function
     user_reason = entities.get('reason') or user_message.strip()
     valid_reasons = self.transaction_service.get_reasons(transaction_type)
     reason = self._map_reason_response(user_reason, valid_reasons)
    
     self.context['transaction_reason'] = reason
     self.context['awaiting_reason'] = False
    
    # For all transaction types, go to confirmation
     self.context['awaiting_confirmation'] = True
     return self._ask_for_confirmation(transaction_type, order_details, reason)

    def _handle_transaction_confirmation(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        """Handle transaction confirmation with Yen prices"""
        transaction_type = self.context.get('transaction_type')
        order_details = self.context.get('current_order')
        reason = self.context.get('transaction_reason')
        
        if not order_details or not reason:
            # Reset context if missing information
            self._reset_transaction_context()
            return self._handle_with_gpt(
                "I'm having trouble processing your request. Please start over.",
                "unknown", 
                entities, 
                session_id
            )
        
        # Check if user confirms
        confirmation_words = ['yes', 'confirm', 'proceed', 'ok', 'okay', 'yeah', 'yep', 'sure']
        if any(word in user_message.lower() for word in confirmation_words):
            # Process the transaction
            price = order_details.get('price', 0)
            currency_symbol = order_details.get('currency_symbol', '¥')
            
            print(f"🔄 Processing {transaction_type} for order {order_details.get('order_id')} with reason: {reason}")
            
            # Prepare complete order data for transaction
            complete_order_data = self._prepare_order_data_for_transaction(order_details)
            
            if transaction_type == 'cancellation':
                transaction_id = self.transaction_service.log_cancellation(
                    self.user_data, complete_order_data, reason
                )
                message = f"✅ Cancellation processed! Refund of {currency_symbol}{price:,} will be processed within 5-7 business days. Reference: {transaction_id}"
            
            elif transaction_type == 'return':
                transaction_id = self.transaction_service.log_refund(
                    self.user_data, complete_order_data, reason
                )
                message = f"✅ Return approved! Refund of {currency_symbol}{price:,} will be processed after we receive the item. Reference: {transaction_id}"
            
            elif transaction_type == 'warranty':
                transaction_id = self.transaction_service.log_warranty_claim(
                    self.user_data, complete_order_data, reason
                )
                message = f"✅ Warranty claim submitted! Our team will contact you within 24 hours. Reference: {transaction_id}"
            
            print(f"✅ {transaction_type.capitalize()} completed with ID: {transaction_id}")
            
            # Clean up context
            self._reset_transaction_context()
            
            return self.response_generator.generate_response(
                f"{transaction_type}_request", entities, self.context,
                {"message": message, "transaction_id": transaction_id}
            )
        
        else:
            # User declined or said something else
            self._reset_transaction_context()
            return self._handle_with_gpt(
                f"{transaction_type.capitalize()} cancelled. Is there anything else I can help you with?",
                f"{transaction_type}_request", 
                entities, 
                session_id
            )
    
    def _prepare_order_data_for_transaction(self, order_details: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare order data for transaction processing with all required fields"""
        # Ensure all required fields are present with defaults
        return {
            "order_id": order_details.get('order_id', 'N/A'),
            "product_id": order_details.get('product_id', 'N/A'),
            "product_name": order_details.get('product_name', 'Unknown Product'),
            "price": order_details.get('price', 0),
            "currency": order_details.get('currency', 'JPY'),
            "status": order_details.get('status', 'unknown'),
            "order_date": order_details.get('order_date', 'Unknown')
        }

    def _reset_transaction_context(self):
        """Reset transaction-related context"""
        keys_to_remove = [
            'awaiting_confirmation', 'transaction_type', 'transaction_reason',
            'current_order', 'current_order_id', 'awaiting_reason', 'awaiting_order_id',
            'awaiting_warranty_confirmation'
        ]
        for key in keys_to_remove:
            self.context.pop(key, None)

    def _get_order_info(self, order_id: str) -> Dict[str, Any]:
        """Get real order information from Pinecone with prices in Yen"""
        try:
            # Get order from Pinecone
            order_data = self.order_manager.get_order_by_id(order_id)
            
            if order_data:
                # Format order information
                order_info = {
                    "order_id": order_data.get('order_id', 'N/A'),
                    "product_name": order_data.get('product_name', 'Unknown Laptop'),
                    "price": self._safe_float(order_data.get('price'), 0),
                    "status": order_data.get('status', 'Unknown').lower().capitalize(),
                    "order_date": order_data.get('order_date', 'Unknown'),
                    "delivery_date": order_data.get('actual_delivery') or order_data.get('estimated_delivery', 'Unknown'),
                    "image_url": order_data.get('img_link', ''),
                    "carrier": order_data.get('carrier', ''),
                    "tracking_number": order_data.get('tracking_number', ''),
                    "return_deadline": order_data.get('return_deadline', '')
                }
                
                # Convert price to JPY
                if order_info['price'] > 0:
                    order_info['price'] = round(order_info['price'] / self.yen_to_inr_rate)
                    order_info['currency'] = 'JPY'
                    order_info['currency_symbol'] = '¥'
                
                return order_info
            
            # If order not found in Pinecone, try sample data
            return self._get_sample_order_info(order_id)
            
        except Exception as e:
            print(f"Error getting order info from Pinecone: {e}")
            # Fallback to sample data
            return self._get_sample_order_info(order_id)
    
    def _get_sample_order_info(self, order_id: str) -> Dict[str, Any]:
        """Get sample order information for demonstration"""
        order_data = {
            "ORD-1001": {
                "order_id": "ORD-1001",
                "product_name": "HP Pavilion Gaming Laptop",
                "price": 89900,
                "status": "Delivered",
                "order_date": "2023-10-15",
                "delivery_date": "2023-10-20",
                "image_url": "https://images.unsplash.com/photo-1587614382346-4ec70e388b28?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80",
                "carrier": "BlueDart",
                "tracking_number": "700000000001",
                "return_deadline": "2023-10-27"
            },
            "ORD-1002": {
                "order_id": "ORD-1002",
                "product_name": "ASUS TUF Gaming F15 Core i5 10th Gen",
                "price": 49990,
                "status": "Delivered",
                "order_date": "2025-09-01",
                "delivery_date": "2025-09-05",
                "image_url": "https://rukminim1.flixcart.com/image/312/312/l3rmzrk0/computer/s/z/r/-original-imagetgzg4pgszmt.jpeg?q=70",
                "carrier": "BlueDart",
                "tracking_number": "700000000002",
                "return_deadline": "2025-09-15"
            },
            "ORD-1005": {
                "order_id": "ORD-1005",
                "product_name": "APPLE 2020 Macbook Air M1",
                "price": 144983,
                "status": "Confirmed",
                "order_date": "2025-09-04",
                "delivery_date": "2025-09-11",
                "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?ixlib=rb-4.0.3&auto=format&fit=crop&w=500&q=80",
                "carrier": "FedEx",
                "tracking_number": "700000000005",
                "return_deadline": "2025-09-18"
            }
        }
        
        order_info = order_data.get(order_id.upper())
        if order_info and 'price' in order_info:
            # Convert price to JPY
            order_info['price'] = round(order_info['price'] / self.yen_to_inr_rate)
            order_info['currency'] = 'JPY'
            order_info['currency_symbol'] = '¥'
        
        return order_info
    
    def _safe_float(self, value, default=0.0):
        """Safely convert value to float"""
        try:
            if value is None:
                return default
            return float(value)
        except (ValueError, TypeError):
            return default
        
    def _map_reason_response(self, user_reason: str, valid_reasons: List[str]) -> str:
        """Map user's reason response to a valid reason"""
        user_reason_lower = user_reason.lower().strip()
        
        # Map common responses to valid reasons
        reason_mapping = {
            'fault': 'Faulty/Defective',
            'faulty': 'Faulty/Defective',
            'defective': 'Faulty/Defective',
            'broken': 'Faulty/Defective',
            'not working': 'Faulty/Defective',
            'damaged': 'Faulty/Defective',
            'wrong': 'Wrong item received',
            'incorrect': 'Wrong item received',
            'different': 'Wrong item received',
            'not as described': 'Item not as described',
            'description': 'Item not as described',
            'changed mind': 'No longer needed',
            'dont need': 'No longer needed',
            'no need': 'No longer needed',
            'other': 'Other'
        }
        
        # Check for exact matches first
        for keyword, mapped_reason in reason_mapping.items():
            if keyword in user_reason_lower:
                if mapped_reason in valid_reasons:
                    return mapped_reason
        
        # Check for partial matches in valid reasons
        for valid_reason in valid_reasons:
            if any(word in user_reason_lower for word in valid_reason.lower().split()):
                return valid_reason
        
        # Default to "Other" if no match found
        return "Other"
    
    def _handle_with_gpt(self, user_message: str, intent: str, entities: Dict[str, Any], session_id: str) -> Dict[str, Any]:
     """Let GPT handle all non-product inquiries with context"""
    # Clear purchase context if we're not specifically in a purchase flow
     if not self.context.get('in_purchase_flow'):
        purchase_context_keys = ['current_products', 'last_search_query']
        for key in purchase_context_keys:
            self.context.pop(key, None)
    
     user_name = self.user_data.get('first_name', self.user_data.get('username', 'User'))
    
    # Prepare context for GPT with additional data sources
     enhanced_context = self._enhance_gpt_context(self.context)
    
    # Get conversation history for context
     recent_history = self._get_recent_conversation_history(5)
    
     prompt = f"""
     You are EZ-Agent, an AI assistant for ShopEZ Laptops.
    
     User: {user_name}
     Current Context: {json.dumps(enhanced_context, default=str)}
     Recent Conversation: {recent_history}
     Current Message: "{user_message}"
     Intent: {intent}
     Entities: {json.dumps(entities)}
    
     Provide a helpful, concise, and natural response based on the available information.
     Be conversational and address the user's needs directly.
    
     Available information:
     - Warranty Policies: {json.dumps(self.warranty_policies)}
     - Product Catalog: Various laptops from brands like Dell, HP, Lenovo, Apple, etc.
     - Order Management: Track orders, process returns, handle warranty claims
    
     If the user is asking about order tracking, returns, or warranty while in a different context,
     smoothly transition to the appropriate section without repeating generic messages.
    
     Important: Avoid generic responses like "I'd love to help you find the perfect laptop!"
     when the user is clearly asking about something else like order tracking.
     """
    
     try:
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant for ShopEZ Laptops. Be specific, helpful, and conversational. Use the available information to provide accurate responses. Ignore irrelevant context from previous conversations. Avoid generic responses when the user has a specific request."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=300
        )
        
        response_text = response.choices[0].message.content.strip()
        
        buttons = self.response_generator._get_buttons_for_intent(intent, self.context)
        
        # Add main menu button to all responses
        buttons.append("Main Menu")
        
        return {
            "response": response_text,
            "buttons": buttons,
            "intent": intent,
            "entities": entities
        }
        
     except Exception as e:
        print(f"GPT conversation error: {e}")
        return self._handle_with_gpt_fallback(user_message)
     
    def _get_recent_conversation_history(self, max_messages: int = 5) -> str:
     """Get recent conversation history for context"""
     recent_messages = []
     count = 0
    
    # Go through conversation history in reverse (most recent first)
     for message in reversed(self.conversation_history):
        if count >= max_messages * 2:  # *2 because we have both user and assistant messages
            break
        
        role = "User" if message["role"] == "user" else "Assistant"
        recent_messages.append(f"{role}: {message['content']}")
        count += 1
    
    # Reverse to get chronological order
     return "\n".join(reversed(recent_messages))
    
    def _enhance_gpt_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
     """Enhance GPT context with additional relevant information"""
     enhanced_context = context.copy()
    
    # Add warranty policy information
     enhanced_context['warranty_policies'] = self.warranty_policies
    
    # Add available brands
     enhanced_context['available_brands'] = ['Dell', 'HP', 'Lenovo', 'Apple', 'Asus', 'Acer', 'MSI', 'Infinix', 'Realme', 'Redmi']
    
    # Add sample order information for context
     enhanced_context['sample_orders'] = self._get_sample_orders()
    
    # Add common query patterns
     enhanced_context['common_queries'] = {
        'color_availability': "You can ask about color availability for specific models",
        'order_tracking': "Provide your Order ID (e.g., ORD-1234) to track your order",
        'return_policy': "Returns are accepted within 30 days of delivery for unused products",
        'warranty_claims': "Warranty claims require valid purchase proof and are processed within 24 hours"
     }
    
     return enhanced_context

    def _handle_with_gpt_fallback(self, user_message: str) -> Dict[str, Any]:
        """Fallback when everything fails"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful AI assistant. Respond naturally to the user's message."},
                    {"role": "user", "content": f"User said: {user_message}"}
                ],
                temperature=0.7,
                max_tokens=150
            )
            
            response_text = response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT fallback also failed: {e}")
            response_text = "I apologize, I'm having trouble processing your request. How can I help you with ShopEZ Laptops today?"
        
        return {
            "response": response_text,
            "buttons": ["Main Menu", "Purchase Laptop", "Order Status", "Return/Cancel"]
        }