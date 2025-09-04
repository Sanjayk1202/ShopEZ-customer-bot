from typing import Dict, Any
import json
from datetime import datetime

class EscalationService:
    def __init__(self):
        self.escalations_file = "data/escalations.json"
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        try:
            with open(self.escalations_file, 'r') as f:
                json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            with open(self.escalations_file, 'w') as f:
                json.dump([], f, indent=2)

    def should_escalate(self, intent: str, user_message: str, context: Dict[str, Any]) -> bool:
        message = user_message.lower()
        
        escalation_triggers = [
            "human", "agent", "representative", "manager", "supervisor",
            "speak to someone", "real person", "talk to person"
        ]
        
        if any(trigger in message for trigger in escalation_triggers):
            return True
        
        complex_intents = ["escalation", "complaint", "legal", "payment_issue"]
        if intent in complex_intents:
            return True
        
        if context.get('failed_attempts', 0) >= 3:
            return True
        
        emotional_words = ["angry", "frustrated", "upset", "disappointed", "terrible", "awful"]
        if any(word in message for word in emotional_words):
            return True
        
        return False

    def log_escalation(self, user_data: Dict[str, Any], reason: str, context: Dict[str, Any]):
        escalation_id = f"ESC-{datetime.now().strftime('%Y%m%d')}-{len(self._get_escalations()) + 1:04d}"
        
        escalation_record = {
            "escalation_id": escalation_id,
            "user_id": user_data.get("user_id"),
            "username": user_data.get("username"),
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "context": context,
            "status": "pending",
            "assigned_agent": None
        }

        self._append_to_file(escalation_record)
        return escalation_id

    def _get_escalations(self) -> list:
        try:
            with open(self.escalations_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _append_to_file(self, record: Dict[str, Any]):
        escalations = self._get_escalations()
        escalations.append(record)
        
        with open(self.escalations_file, 'w') as f:
            json.dump(escalations, f, indent=2)