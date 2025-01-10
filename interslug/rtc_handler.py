import asyncio
from dataclasses import dataclass
import uuid
from pyee import EventEmitter
from websockets.asyncio.server import ServerConnection
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCDataChannel, MediaStreamTrack, RTCIceCandidate
from interslug.messages.message_builder import message_to_str
from logging_config import get_logger

@dataclass
class IncomingRTCIceCandidate():
    candidate: str
    sdpMid: str
    sdpMLineIndex: int
    usernameFragment: str

def component_str_to_int(component: str):
    """ WebRTC uses the strings properly. somehow, aiortc is ints?? """
    if component == "rtp":
        return 1
    if component == "rtcp":
        return 2


class RTCHandler():
    def __init__(self, ws_connection: ServerConnection):
        self.ws_connection = ws_connection
        self.id = f"rtc_{uuid.uuid4()}"
        self.ws_id = ws_connection.id
        self.logger = get_logger(f"rtc-handler-{self.id}")
        
        self.logger.debug("initialising RTCPeerConnection")
        self.pc = RTCPeerConnection()
        self.add_default_listeners()

        self.emitter = EventEmitter()

        # Flags for state
        self.ready_to_transmit = False
        self.negotiation_needed = False # LocalDescription has changed. New/Removed track, etc.
        self.watch_negotiation = False # 

    async def _watch_for_negotiation(self):
        while self.watch_negotiation: 
            if self.negotiation_needed:
                self.pc.emit("negotiationneeded")
                self.negotiation_needed = False
            await asyncio.sleep(0.1)

    async def on_track(self, track: MediaStreamTrack):
        self.logger.debug(f"Event Trigger [on_Track]. ")
        self.emitter.emit("incoming_track", track)
        # From here, add the Track to a new class that on recv 

    async def on_datachannel(self, channel: RTCDataChannel):
        self.logger.debug(f"Event Trigger [on_Channel]. ")

    async def on_icecandidate(self, candidate):
        self.logger.debug(f"Event Trigger [on_IceCandidate]. ")

    async def on_icegatheringstatechange(self):
        new_state = self.pc.iceGatheringState
        self.logger.debug(f"Event Trigger [on_IceGatheringStateChange]. iceGatheringState={new_state}")

    async def on_connectionstatechange(self):
        new_state = self.pc.connectionState
        self.watch_negotiation = False
        self.logger.debug(f"Event Trigger [on_ConnectionStateChange]. connectionState={new_state}")
        self.check_can_transmit()
        if new_state == "connecting" or new_state == "connected" or new_state == "new":
            self.logger.debug("enabling negotitation watch")
            self.watch_negotiation = True
            asyncio.create_task(self._watch_for_negotiation())

    async def on_signalingstatechange(self):
        new_state = self.pc.signalingState
        self.logger.debug(f"Event Trigger [on_SignalingStateChange]. signalingState={new_state}")
        self.check_can_transmit()

    async def on_negotiationneeded(self):
        self.logger.debug(f"Event Trigger [on_NegotiationNeeded].")
        await self.update_local_description()

    def add_default_listeners(self):
        async def on_track(track: MediaStreamTrack):
            await self.on_track(track)
        async def on_datachannel(channel: RTCDataChannel):
            await self.on_datachannel(channel)
        async def on_icecandidate(candidate):
            await self.on_icecandidate(candidate)
        async def on_icegatheringstatechange():
            await self.on_icegatheringstatechange()
        async def on_connectionstatechange():
            await self.on_connectionstatechange()
        async def on_signalingstatechange():
            await self.on_signalingstatechange()
        async def on_negotiationneeded():
            await self.on_negotiationneeded()
        self.pc.add_listener("connectionstatechange", on_connectionstatechange)
        self.pc.add_listener("signalingstatechange", on_signalingstatechange)
        self.pc.add_listener("negotiationneeded", on_negotiationneeded)
        self.pc.add_listener("datachannel", on_datachannel)
        self.pc.add_listener("track", on_track)
        self.pc.add_listener("icecandidate", on_icecandidate)
        self.pc.add_listener("icegatheringstatechange", on_icegatheringstatechange)

    
    async def process_offer_and_form_answer(self, message: dict):
        self.logger.debug("Calling setRemoteDescription()")
        await self.pc.setRemoteDescription(RTCSessionDescription(message["sdp"], "offer"))
        self.logger.debug("Calling createAnswer()")
        answer = await self.pc.createAnswer()
        self.pc.connectionState
        self.logger.debug("Calling setLocalDescription()")
        await self.pc.setLocalDescription(answer)

        return {"sdp": self.pc.localDescription.sdp, "type": "answer"}
    
    async def add_ice_candidate(self, message: dict):
        cd_dict = message["candidate"]
        cd_dict["component"] = component_str_to_int(cd_dict["component"])
        candidate = RTCIceCandidate(**cd_dict)
        self.logger.debug(f"Adding ICE Candidate. candidate={candidate}")
    
        # await self.pc.addIceCandidate(candidate)
    
    async def add_track(self, audio_track):
        self.logger.debug("Attempting to add AudioTrack")
        self.pc.addTrack(audio_track)
        self.logger.debug("Returning new offer/answer")
        await self.update_local_description()
    
    async def update_local_description(self):
        try:
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            ld = {"sdp": self.pc.localDescription.sdp, "type": "offer"}
            await self.ws_connection.send(message_to_str(ld, "RTC"))
            self.negotiation_needed = False
        except Exception as e:
            self.logger.debug(e)
    
    async def update_remote_description(self, message):
        await self.pc.setRemoteDescription(RTCSessionDescription(message["sdp"], "answer"))

    def check_can_transmit(self):
        senders = self.pc.getSenders()
        receivers = self.pc.getReceivers()
        # Check connectionState = connected
        # Check have a Sender
        # Check signalingState = stable
        active_audio_senders = [sender for sender in senders if sender.kind == "audio" and sender.track and sender.track.readyState == "live"]
        if self.pc.connectionState == "connected" and self.pc.signalingState == "stable" and len(senders) > 0 and len(active_audio_senders) > 0:
            self.ready_to_transmit = True
        else:
            self.ready_to_transmit = False
        self.logger.debug(f"check_can_transmit: ready_to_transmit={self.ready_to_transmit}, senders={len(senders)}, receivers={len(receivers)}, connectionState={self.pc.connectionState}, signalingState={self.pc.signalingState}")
    
    def kill_audio_sender(self):
        self.logger.debug("killing audio senders")
        senders = [sender for sender in self.pc.getSenders() if sender.track]
        for sender in senders:
            self.logger.debug(f"Replacing track in sender")
            sender.track.stop()
            sender.replaceTrack(None)
        # Flag for renegotiation
        self.negotiation_needed = True