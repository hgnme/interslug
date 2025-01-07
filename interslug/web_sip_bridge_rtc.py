import asyncio
from dataclasses import asdict, dataclass
import json
import pjsua2 as pj

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK

from .rtc_handler import RTCHandler
from interslug.media_cookery.bridges import SIPAudioBridge, SIPToBrowserAudioTrack
from interslug.media_cookery.queuing import Q_LIST_TYPE_SIP_TO_BROWSER, Q_LIST_TYPE_BROWSER_TO_SIP, get_queue_list_by_type, get_queue_by_id
from interslug.messages.message_builder import message_to_str
from interslug.messages.notification_types import NotificationOnCallStatus
from logging_config import get_logger
from config import HGN_SSL_CONTEXT

from typing import TYPE_CHECKING
from hgn_sip.sip_media import get_audio_format
if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_account import SIPAccount

# PJSIP Call State
websocket_clients = set()  # Tracks connected WebSocket clients
rtcpc_clients = []

rtc_connections: list[RTCHandler] = []

get_queue_list_by_type(Q_LIST_TYPE_SIP_TO_BROWSER)
get_queue_list_by_type(Q_LIST_TYPE_BROWSER_TO_SIP)


def get_pc_for_wsid(wsid):
    """ Return RPC for websocket UUID
    """
    for pc in rtcpc_clients:
        if pc["uuid"] == wsid:
            return pc["pc"]

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

async def send_sip_notification(body: NotificationOnCallStatus):
    dict_obj = asdict(body)
    logger = get_logger("send_sip_notification")
    message = message_to_str(dict_obj, "sip")
    logger.debug(f"Sending notification to clients. count={len(websocket_clients)}")
    for client in websocket_clients:
        logger.debug(f"Sending notification to client remote_addr={client.remote_address}")
        try:
            await client.send(message)
            logger.debug(f"sent")
        except Exception as e:
            logger.error(f"Error notifying client: {e}")

def sip_call_cb_notify_ws(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'pj.CallInfo'):
    """ 
        Callback triggered on call statuses from hgnsip.sip_call
        Notifies the WS clients of the state
    """
    logger = get_logger("sip_call_cb_notify_ws")
    call_id = call_info.callIdString
    data = NotificationOnCallStatus(call_info.stateText, call_info.callIdString, call_info.accId, call_info.localUri, call_info.remoteUri)
    logger.debug(f"call_id={call_id}, state={call_info.stateText}")
    if (call_info.stateText == "CONFIRMED" and call.connected):
        pass
    if call_info.stateText == "DISCONNECTED":
        queue_list = get_queue_list_by_type(Q_LIST_TYPE_SIP_TO_BROWSER)
        queue = get_queue_by_id(queue_list, call_id)
        queue_list.queues.remove(queue)
        # Get RTCConn using CallID
        conns_using_call = [rp for rp in rtc_connections if rp.active_call_id == call_id]
        for conn in conns_using_call:
            logger.debug("killing audio sender for RTConn")
            asyncio.run(conn.kill_audio_sender())

    asyncio.run(send_sip_notification(data))

def get_rtc_connection_by_ws_id(ws_id):
    for conn in rtc_connections:
        if conn.ws_id == ws_id:
            return conn

async def process_rtc_msg(websocket: ServerConnection, message): 
    logger = get_logger(f"process-rtc-message[{websocket.id}]")
    rtc_conn = get_rtc_connection_by_ws_id(websocket.id)
    if rtc_conn is None:
        logger.debug("No connection found, creating...")
        rtc_conn = RTCHandler(websocket)
        rtc_connections.append(rtc_conn)

    msg_type = message["type"]
    # logger.debug(f"type={msg_type}")

    if msg_type == "offer":
        answer = await rtc_conn.process_offer_and_form_answer(message)
        logger.debug("Responding with answer")
        await websocket.send(message_to_str(answer, "rtc"))
    if msg_type == "answer":
        logger.debug("Processing new Answer")
        await rtc_conn.update_remote_description(message)

    if msg_type == "icecandidate":
        await rtc_conn.add_ice_candidate(message)

async def process_sip_msg(websocket: ServerConnection, message):
    logger = get_logger(f"process-sip-message[{websocket.id}]")

    msg_type = message["type"]
    logger.debug(f"type={msg_type}")
    
    if msg_type == "answer_call":
        # Browser wants to join the current call. Should advertise the audio track to it.
        target_call_id: str = message["call_id"]
        logger.debug(f"Wants to answer call. callid={target_call_id}")
        rtc_conn = get_rtc_connection_by_ws_id(websocket.id)
        if rtc_conn is None:
            logger.error("rtc_conn is missing for client")
            return
        
        # Create AudioPort to attach to SIP Call
        # Get call by ID?

        # Add audio track to the rtc_conn
        audio_track = SIPToBrowserAudioTrack(target_call_id)
        rtc_conn.active_call_id = target_call_id
        await rtc_conn.add_track(audio_track)
    elif msg_type == "end_call":
        target_call_id = message["call_id"]
        logger.debug(f"Wants to disconnect from call. callid={target_call_id}")
        rtc_conn = get_rtc_connection_by_ws_id(websocket.id)
        if rtc_conn is None:
            logger.error("rtc_conn is missing for client")
            return
        success = await rtc_conn.kill_audio_sender()

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
                msg_channel = data["channel"]

                if msg_channel == "rtc":
                    logger.debug(f"Received message for RTC Channel, triggering process_rtc_msg")
                    await process_rtc_msg(websocket, data["message"])
                elif msg_channel == "sip":
                    logger.debug(f"Received message for SIP Channel, triggering process_sip_msg")
                    await process_sip_msg(websocket, data["message"])
            except asyncio.TimeoutError:
                # Send a ping to the browser to keep the connection alive
                await websocket.send(json.dumps({"type": "ping"}))
            except ConnectionClosedOK as e:
                should_run = False
                logger.debug("Connection closed (ok)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        raise
    finally:
        if websocket is not None:
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
