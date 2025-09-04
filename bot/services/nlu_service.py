import openai
import json
import re
from typing import Dict, Any
from config import Config

class NLUService:
    def __init__(self):
        self.client = openai.OpenAI(api_key=Config.OPENAI_API_KEY)

    def extract_intent_and_entities(self, user_message: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """More accurate intent detection with context awareness"""
        try:
            prompt = f"""
            Analyze this user message in the context of the conversation:
            
            Current Context: {json.dumps(context, default=str) if context else 'No context'}
            User Message: "{user_message}"
            
            Extract the MOST SPECIFIC intent and entities:
            
            INTENTS (choose the most specific one):
            - greeting: hello, hi, hey, how are you
            - product_inquiry: laptop, computer, buy, purchase, under [price], budget
            - specific_product: asking about specific model/brand (HP, Dell, etc.)
            - product_comparison: compare, vs, which is better, difference
            - order_status: order, status, track, where is my order
            - return_request: return, refund, send back
            - cancellation_request: cancel, stop order, don't want
            - warranty_claim: warranty, broken, not working
            - technical_support: help, problem, issue, support
            - color_inquiry: color, available colors, what colors
            - general_question: what, how, when, where, why questions
            - goodbye: bye, goodbye, thanks
            
            ENTITIES to extract:
            - order_id: ORD- followed by numbers
            - budget: under 60k, 60000, ₹60000
            - max_price: numeric value (60000)
            - ram: 8gb, 16gb, memory
            - brand: hp, dell, lenovo, etc.
            - product_model: specific model numbers/names
            - color: black, silver, etc.
            
            Return JSON: {{"intent": "specific_intent", "entities": {{"entity": "value"}}}}
            """
            
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are an accurate intent classifier. Be specific and context-aware."},
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
                
            # Convert budget to numeric max_price
            entities = result['entities']
            if 'budget' in entities:
                entities['max_price'] = self._parse_budget_to_max_price(entities.get('budget', ''))
                
            return result
            
        except Exception as e:
            print(f"NLU Error: {e}")
            return self._fallback_extraction(user_message, context)

    def _parse_budget_to_max_price(self, budget_text: str) -> int:
        """Convert budget text to numeric max price"""
        try:
            budget_text = str(budget_text).lower()
            
            # Extract numbers
            numbers = re.findall(r'\d+', budget_text)
            if numbers:
                number = int(numbers[0])
                if 'k' in budget_text:
                    number *= 1000
                return number
        except:
            pass
        return None

    def _fallback_extraction(self, user_message: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Context-aware fallback extraction"""
        message = user_message.lower()
        
        # Check for order IDs first
        order_match = re.search(r'ORD-\d+', message, re.IGNORECASE)
        if order_match:
            return {
                "intent": "order_status",
                "entities": {"order_id": order_match.group(0).upper()}
            }
        
        # Check context for ongoing conversations
        if context and context.get('awaiting_order_id'):
            if re.search(r'\d+', message):
                return {
                    "intent": "order_status",
                    "entities": {"order_id": f"ORD-{re.search(r'\d+', message).group(0)}"}
                }
        
        # Basic intent detection
        intent_map = [
            (["hello", "hi", "hey", "howdy"], "greeting"),
            (["laptop", "computer", "buy", "purchase"], "product_inquiry"),
            (["order", "status", "track", "where is"], "order_status"),
            (["return", "refund", "send back"], "return_request"),
            (["cancel", "stop order"], "cancellation_request"),
            (["warranty", "broken"], "warranty_claim"),
            (["compare", "vs", "which is better"], "product_comparison"),
            (["color", "colors", "available colors"], "color_inquiry"),
            (["bye", "goodbye", "thanks"], "goodbye"),
            (["help", "problem", "issue"], "technical_support")
        ]
        
        for keywords, intent in intent_map:
            if any(keyword in message for keyword in keywords):
                return {"intent": intent, "entities": {}}
        
        return {"intent": "general_question", "entities": {}}