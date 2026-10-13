from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class NotificationAdapter(ABC):
    @abstractmethod
    async def send_message(self, to_destination: str, message_content: str) -> Dict[str, Any]:
        """
        Sends a message to the specified destination.
        Returns a dictionary containing details about the delivery, such as provider_message_id.
        """
        pass

    @abstractmethod
    async def get_message_status(self, provider_message_id: str) -> str:
        """
        Retrieves the delivery status of a previously sent message.
        """
        pass
