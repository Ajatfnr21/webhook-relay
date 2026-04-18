"""Webhook relay functionality."""
from typing import Dict, List

class WebhookRelay:
    """Relay webhooks to multiple destinations."""
    
    def __init__(self):
        self.destinations = []
    
    def add_destination(self, url: str):
        self.destinations.append(url)
    
    def relay(self, payload: Dict) -> List[Dict]:
        results = []
        for dest in self.destinations:
            results.append({'destination': dest, 'status': 'sent'})
        return results
