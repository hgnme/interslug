import asyncio
import fractions
import json
import os
import ssl
import time
import numpy as np
import pjsua2 as pj
from av.audio.frame import AudioFrame

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack, AudioStreamTrack, RTCConfiguration
from logging_config import get_logger
from config import HGN_SSL_CONTEXT


from typing import TYPE_CHECKING
from hgn_sip.sip_media import get_audio_format
if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_account import SIPAccount

# PJSIP Call State
active_call = None  # Tracks the current active call
AUDIO_TRACK_CONFIRMED = False
websocket_clients = set()  # Tracks connected WebSocket clients
rtcpc_clients = []
# Queues for audio frame passing
class Q():
    id_str: 'str'
    queue: 'asyncio.Queue'

q_list_sip_to_browser: list[Q] = []

def get_or_create_queue_by_id(id_str: str, q_list: list[Q]):
    for q in q_list:
        if q.id_str == id_str:
            return q
    new_q = Q()
    new_q.id_str = id_str
    new_q.queue = asyncio.Queue(maxsize=5)

    q_list.append(new_q)
    return new_q

def get_pc_for_wsid(wsid):
    """ Return RPC for websocket UUID
    """
    for pc in rtcpc_clients:
        if pc["uuid"] == wsid:
            return pc["pc"]


def add_frame_to_queue(frame, queue: asyncio.Queue):
    obj = {
        "frame": frame,
        "ts": time.time()
    }
    queue.put_nowait(obj)

async def get_from_queue(queue: asyncio.Queue, max_age: float, expected_sample_size: int):
    logger = get_logger("get_from_queue")
    logger.info("get_from_queue")
    now = time.time()
    while not queue.empty():
        frame_obj = await queue.get()
        frame = frame_obj["frame"]
        frame_ts = frame_obj["ts"]
        frame_age_in_sec = now - frame_ts
        if frame_age_in_sec <= max_age:
            return frame
        else: 
            logger.debug(f"Dropping frame due to excessive age. cutoff={max_age}s, actual={frame_age_in_sec}s")
    
    logger.debug(f"Returning zero frame due to empty queue")
    return np.zeros(expected_sample_size, dtype=np.int16)


class SIPToBrowserAudioTrack(AudioStreamTrack): 
    """
        AudioStreamTrack for use with WebRTC. Takes frames from the queue and outputs them
        Timing must be maintained to maintain realtimeness.
        INPUT: Frames from SIP->Browser Queue
        OUTPUT: Frames to WebRTC
    """
    def __init__(self, call_id: str):
        super().__init__()
        self.call_id = call_id
        self.logger = get_logger(f'dummy-AudioStreamTrack[{self.id}]')
        self.format = get_audio_format()
        self.frametime_sec = self.format.frameTimeUsec * 0.000001
        self.queue = get_or_create_queue_by_id(self.call_id, q_list_sip_to_browser).queue
    async def recv(self):
        """
            Receive a frame from the Sip-> Browser Queue (and remove it)
            then return it back after timing and transformation.
        """
        self.logger.debug(f"RECV: items in queue={self.queue.qsize()}")
        expected_samples = int(self.frametime_sec * self.format.clockRate)
        
        if hasattr(self, "_timestamp"):
            self._timestamp += expected_samples
            wait = self._start + (self._timestamp / self.format.clockRate) - time.time()
            await asyncio.sleep(wait)
        else:
            self._start = time.time()
            self._timestamp = 0
        # audio_data = await self.queue.get()
        audio_data = await get_from_queue(self.queue, self.frametime_sec * 5, expected_samples)
        if len(audio_data) != expected_samples:
            raise Exception({"e": "Length of frame not matching expected sample count", "audio_data":audio_data, "expected_samples": expected_samples})

        frame = AudioFrame(format="s16", layout="mono", samples=expected_samples)
        for p in frame.planes:
            p.update(audio_data)
        frame.pts = self._timestamp # Presentation Timestamp in time_base units
        frame.sample_rate = self.format.clockRate 
        frame.time_base = fractions.Fraction(1, self.format.clockRate) # Time base is 1/samplerathed of a second. e.g. 1/8000 = 0.000125s
        return frame

class SIPAudioBridge(pj.AudioMediaPort):
    """ 
        Audio Bridge to connect to SIP audio stream. This will receive frames from it and add them to the relevant queue for consumption
        INPUT: Frame from direct SIP Audio Stream
        OUTPUT: Frame to SIP->Browser Queue
    """
    global AUDIO_TRACK_CONFIRMED
    def __init__(self, call_id: str):
        super().__init__()
        self.logger = get_logger("sip-audio-bridge")
        self.name: str
        self.call_id = call_id
        self.format: pj.MediaFormatAudio
        self.queue = get_or_create_queue_by_id(self.call_id, q_list_sip_to_browser).queue

    def createPort(self, port_name, audio_format: pj.MediaFormatAudio):
        self.logger.debug(f"Registering port name={port_name}")
        self.port_name = port_name
        self.format = audio_format
        super().createPort(port_name, audio_format)

    def onFrameReceived(self, frame: pj.MediaFrame):
        """Forward SIP audio to the browser."""
        if AUDIO_TRACK_CONFIRMED:
            audio_data = np.frombuffer(bytes(frame.buf), dtype=np.int16) # Convert PJSIP Buffer object to an NP array of signed 16b ints
            try:
                add_frame_to_queue(audio_data, self.queue)
                # self.queue.put_nowait(audio_data) # add to the queue
            except asyncio.QueueFull:
                pass

def attach_bridge_to_sip_call(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'pj.CallInfo'):
    """ 
        Attach the SIPAudioBridge as a listening port to the SIP Call, this will then receive the frames of audio to share downstream.
    """ 
    logger = get_logger("attach_bridge_to_sip_call")
    # Get call audio media
    # Attach this SIPAudioBridge to it 
    logger.debug("Creating SIPAudioBridge")
    audio_port = SIPAudioBridge(call_id=call_info.callIdString) # This gets audio FROM sip and adds to queue for RTC
    logger.debug("Registering port with pre-defined PCM format")
    audio_port.createPort("WebsocketAudioPort", get_audio_format()) # Audio Format is set once
    call_audio_media = call.get_call_audio_media() # This is the incoming SIP audio stream
    logger.debug("Triggering Transmit on existing call's audiomedia")
    call_audio_media.startTransmit(audio_port)

    call.ports.append(audio_port) # Store the AudioPort for future use
    

async def notify_clients(event, data=None):
    """
        Notify all connected WebSocket clients about an event.
    """
    logger = get_logger("ws_notify_clients")
    message = {"event": event}
    logger.debug(f"called to notify clients count={len(websocket_clients)}")
    if data:
        message.update(data)
    for client in websocket_clients:
        logger.debug(f"Sending notification to client remote_addr={client.remote_address}")
        try:
            await client.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Error notifying client: {e}")

def sip_call_cb_notify_ws(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'pj.CallInfo'):
    """ 
        Callback triggered on call statuses from hgnsip.sip_call
        Notifies the WS clients of the state
    """
    global active_call
    logger = get_logger("sip_call_cb_notify_ws")

    if (call_info.stateText == "CONFIRMED" and call.connected):
        active_call = call
    if call_info.stateText == "DISCONNECTED":
        active_call = None
        queue = get_or_create_queue_by_id(call_info.callIdString, q_list_sip_to_browser)
        q_list_sip_to_browser.remove(queue)
    data = {
        "callId": call_info.callIdString,
        "accId": call_info.accId,
        "localUri": call_info.localUri,
        "remoteUri": call_info.remoteUri,
    }
    logger.debug(f"Sending WS event with data={data}")
    logger.debug(f"Current connected clients: {len(websocket_clients)}")
    asyncio.run(notify_clients(call_info.stateText, data))

async def offer_rtc(websocket: ServerConnection, data):
    global AUDIO_TRACK_CONFIRMED
    lid = f"rtcpc-offer_rtc[ws-{websocket.id}]"
    logger = get_logger(lid)
    target_sip_call_id = data["callId"]
    remote_sd = RTCSessionDescription(data["sdp"], data["type"])
    configuration = RTCConfiguration()
    pc = RTCPeerConnection(configuration=configuration)
    # pc = RTCPeerConnection()

    
    logger.debug("Attaching Bindings")
    @pc.on("track")
    async def on_track(track: MediaStreamTrack):
        logger = get_logger(lid)
        if track.kind == "audio":
            logger.debug("Audio track received")

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        logger.debug(f"ICE candidate: {candidate}")

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        global AUDIO_TRACK_CONFIRMED
        logger.debug(f"ICE gathering state changed: {pc.iceGatheringState}")
        if pc.iceGatheringState == "complete":
            AUDIO_TRACK_CONFIRMED = True

    audio_track = SIPToBrowserAudioTrack(target_sip_call_id)
    pc.addTrack(audio_track)
    logger.debug("Audio track added to peer connection")
    
    # set RD
    logger.debug("set RD")
    await pc.setRemoteDescription(remote_sd)
    # Answer to offer (LD)
    logger.debug("createAnswer")
    answer = await pc.createAnswer()
    logger.debug("set LD")
    await pc.setLocalDescription(answer)

    # Store the Connection
    logger.debug("Storing connection")
    rtcpc_clients.append({"uuid": websocket.id, "pc": pc})

    # Send the connection answer back
    logger.debug("Sending RTCPC Answer")
    await websocket.send(json.dumps({"type": "answer", "sdp": pc.localDescription.sdp}))
    logger.debug("Sent")


async def handle_signaling(websocket: ServerConnection):
    global websocket_clients
    websocket_clients.add(websocket)
    logger = get_logger(f"ws-handle-signalling[{websocket.id}]")
    logger.debug(f"New websocket client remote_address={websocket.remote_address}")

    try:
        should_run = True
        while should_run:
            try:
                # Wait for messages from the browser
                message = await asyncio.wait_for(websocket.recv(), timeout=10)
                data = json.loads(message)

                # Handle WebRTC signaling or custom messages
                if data["type"] == "offer":
                    logger.debug(f"Received RTC Offer")
                    await offer_rtc(websocket, data)

            except asyncio.TimeoutError:
                # Send a ping to the browser to keep the connection alive
                await websocket.send(json.dumps({"type": "ping"}))
            except ConnectionClosedOK as e:
                should_run = False
                logger.debug("Connection closed (ok)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.debug(f"Connection from {websocket.remote_address} closed")
        pc = get_pc_for_wsid(websocket.id)
        if pc is not None:
            await pc.close()
        websocket_clients.remove(websocket)

async def run_main():
    logger = get_logger("ws_server_main")
    # Start WebSocket server with WSS
    async with serve(
        handle_signaling, "192.168.1.185", 8765, ssl=HGN_SSL_CONTEXT
    ):
        logger.info("WebRTC signaling server running on wss://192.168.1.185:8765")
        await asyncio.Future()  # Run forever


# if __name__ == "__main__":
#     asyncio.run(main())
