from enum import Enum
from pyee.asyncio import AsyncIOEventEmitter
from pyee import EventEmitter

from typing import TYPE_CHECKING

from interslug.misc_garbage.run_async_as_sync import run_async_as_sync
from logging_config import get_logger
from interslug.messages.message_builder import message_to_str

if TYPE_CHECKING:
    from interslug.state.browser_state import BrowserState
    from interslug.state.call_manager import CallManager
    from websockets.asyncio.server import ServerConnection

class MessageChannel(Enum):
    SIP = "SIP"
    RTC = "RTC"
    SYS = "SYS"

class SocketMessenger():
    def __init__(self, call_manager: 'CallManager'):
        self.logger = get_logger("SocketMessenger")
        self.cm = call_manager
        self.emitter = EventEmitter()
        self.emitter.on("queue_message", self.sendMessage)
    
    def queueMessage(self, msg_dest: 'BrowserState', channel:str, msg_data):
        self.emitter.emit("queue_message", msg_dest.websocket, channel, msg_data)

    def queueMessageAll(self, channel:str, msg_data):
        for browser_id in self.cm.browsers:
            browser = self.cm.browsers[browser_id]
            self.emitter.emit("queue_message", browser.websocket, channel, msg_data)

    def sendMessage(self, msg_dest: 'ServerConnection', channel:MessageChannel, msg_data):
        msg_body = message_to_str(msg_data, channel.value)
        self.logger.debug(f"SendMessage. channel={channel} msg_data={msg_body}")
        if not msg_dest:
            self.logger.error(f"Error: Message destination invalid")
            return
        run_async_as_sync(msg_dest.send(msg_body))
