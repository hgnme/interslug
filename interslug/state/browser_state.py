from typing import TYPE_CHECKING

from interslug.rtc_handler import RTCHandler

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

class BrowserState:
    """
        Represents a current Browser State.
        Contains:
        - The websocket
        - The Current Call ID
    """
    def __init__(self, websocket: 'ServerConnection'):
        self.websocket = websocket  # WebSocket connection object
        self.current_call_id: str = None  # Call ID if browser is in a call
        self.rtc_handler: RTCHandler = None
