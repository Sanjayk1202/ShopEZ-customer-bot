import openai
from typing import Dict, Any
from config import Config
import json

class ResponseGenerator:
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)
        self.system_prompt = """
        You are EZ-Agent, a friendly AI customer service agent for ShopEZ Laptops.
        Keep responses concise, helpful, and conversational.
        Use the user's name when available.
        Be professional but friendly.
        Provide complete information without unnecessary follow-up questions.
        """

    def generate_response(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any], data: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            # If custom data is provided, use it
            if data and 'message' in data:
                response_text = data['message']
            else:
                # Use GPT for natural responses
                response_text = self._generate_gpt_response(intent, entities, context, data)
            
            # Get appropriate buttons
            buttons = self._get_buttons_for_intent(intent, context)
            
            return {
                "response": response_text,
                "buttons": buttons,
                "intent": intent,
                "entities": entities
            }
            
        except Exception as e:
            print(f"Response generation error: {e}")
            return {
                "response": "I apologize, I'm having trouble processing your request. Please try again.",
                "buttons": self._get_all_buttons()
            }

    def _generate_gpt_response(self, intent: str, entities: Dict[str, Any], context: Dict[str, Any], data: Dict[str, Any]) -> str:
        """Generate responses using GPT"""
        
        user_data = context.get('user_data', {})
        user_name = user_data.get('first_name') or user_data.get('username', 'there')
        
        prompt = f"""
        Intent: {intent}
        User: {user_name}
        Context: {json.dumps(context, default=str)}
        Entities: {json.dumps(entities)}
        
        Generate a helpful, natural response for this intent.
        For product inquiries, provide specific recommendations.
        Don't ask unnecessary follow-up questions.
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=200
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"GPT generation error: {e}")
            return self._generate_fallback_response(intent, user_name)

    def _generate_fallback_response(self, intent: str, user_name: str) -> str:
        """Fallback responses"""
        responses = {
            "greeting": f"Hello {user_name}! Welcome to ShopEZ Laptops. How can I help you today?",
            "product_inquiry": "I'd be happy to help you find the perfect laptop!",
            "specific_product_request": "Let me get information about that product for you.",
            "order_status": "I can help you track your order.",
            "return_request": "I can assist with your return request.",
            "cancellation_request": "I can help you cancel your order.",
            "warranty_claim": "I can assist with your warranty claim.",
            "comparison": "I can help you compare different laptops.",
            "technical_support": "I'm here to help with any technical issues.",
            "general_question": "I'd be happy to answer your question.",
            "goodbye": f"Goodbye {user_name}! Thank you for visiting ShopEZ Laptops.",
            "unknown": "How can I help you with ShopEZ Laptops today?"
        }
        return responses.get(intent, "How can I help you today?")

    def _get_buttons_for_intent(self, intent: str, context: Dict[str, Any]) -> list:
        """Get appropriate quick reply buttons"""
        base_buttons = ["Purchase Laptop", "Order Status", "Return/Cancel", "Warranty"]
        
        # Add context-specific buttons
        if intent == "product_inquiry":
            return base_buttons + ["Gaming", "Business", "Student", "Budget"]
        elif intent == "order_status":
            return base_buttons + ["Track Another", "Help"]
        elif intent in ["return_request", "cancellation_request"]:
            return base_buttons + ["Confirm", "Help"]
        else:
            return base_buttons

    def _get_all_buttons(self) -> list:
        """Return ALL main buttons always"""
        return ["Purchase Laptop", "Order Status", "Return/Cancel", "Warranty"]