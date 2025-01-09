from typing import TYPE_CHECKING

from interslug.state.call_backs import cb_on_endcall_remove_from_call_manager, cs_cb_on_callstate_call_manager_update
if TYPE_CHECKING:
    from hgn_sip.sip_account import SIPAccount
    from hgn_sip.sip_handler import SIPHandler

from pjsua2 import CallInfo, OnInstantMessageStatusParam, SipRxData
from logging_config import get_logger
from hgn_sip.sip_call import SIPCall
from hgn_sip.sip_handler import SIPHandler
from hgn_sip.sip_callbacks import SIPCallStateCallback, SIPInstantMessageStatusStateCallback, SIPCallCallback
from intercom_sender import UnlockButtonPushXML
from interslug.wall_panel import WallPanel, get_wall_panel_building
from config import WALL_PANELS
from service_helper import stop_event

from .web_sip_bridge_rtc import sip_call_cb_notify_ws, attach_bridge_to_sip_call
import time 

# Callback which is triggered when a SIPCall is Connected
# This will send a SIP MESSAGE to the RemoteURI (wallpanel prob) containing the Unlock XML
# as though you had just pressed "Unlock" on the Intercom
def cs_cb_send_unlock_on_connected(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'CallInfo'):
    logger = get_logger("cs_cb_send_unlock_on_connected")
    logger.info("Callback has been triggered")

    building = get_wall_panel_building(call_info.remoteUri, WALL_PANELS)
    floor = 4
    logger.info(f"RemoteURI={call_info.remoteUri}, building={building}, floor={floor}")
    message_content = UnlockButtonPushXML(building, floor).to_string()
    logger.debug(message_content)
    call_account.send_im_to_remote_uri(call_info.remoteUri, message_content)

# When an IM is received by the RemoteURI, it'll return an acknowledgement, this runs when that is received
# It doesn't matter though because the dumb panels say "200 OK" even if I send them garbage
# The call ends as soon as response is received.
def im_cb_check_if_message_accepted(im_status_param: 'OnInstantMessageStatusParam', sip_account: 'SIPAccount'):
    logger = get_logger("im_cb_check_if_message_accepted")
    resp_data: 'SipRxData' = im_status_param.rdata
    resp_parts = resp_data.wholeMsg.split("\r\n\r\n", 1)

    if len(resp_parts) > 1:
        resp_body = resp_parts[1]
        logger.info(f"onInstantMessageStatus: Response included body text. body={resp_body}")
        origin_call = sip_account.find_call(im_status_param.toUri)
        if origin_call is not None:
            logger.info(f"match call found, hanging up.")
            origin_call.end_call()

# Web Interface triggered event to unlock a specific panel. 
# This will call the panel (auto answer), on answer the above unlock callback is ran, then the call is ended.
def trigger_send_unlock_to_wallpanel(target_panel, sip_account: 'SIPAccount'):
    logger = get_logger("trigger_send_unlock_to_wallpanel")
    dest_wall_panel: 'WallPanel' = None
    for panel in WALL_PANELS:
        if panel.name == target_panel:
            logger.info(f"Destination panel found. ip={panel.ip}, name={panel.name}, sip_handle={panel.sip_handle}, sip_uri={panel.sip_uri}")
            dest_wall_panel = panel
    
    sip_account.ep.libRegisterThread("web-thread") # ThreadSaFeTy

    new_call = SIPCall(acc=sip_account, callbacks=sip_account.onCallStateCallbacks)
    new_call.make_call(dest_wall_panel.sip_uri)
    sip_account.calls.append(new_call)

# List of Callback methods to run, and their call State to run on.
# These are attached to every call - incoming and outgoing.
on_call_state_callbacks = [
    # SIPCallStateCallback("CONFIRMED", cs_cb_send_unlock_on_connected)
    # SIPCallStateCallback("CONFIRMED", attach_bridge_to_sip_call),
    # SIPCallStateCallback("CONFIRMED", sip_call_cb_notify_ws),
    # SIPCallStateCallback("INCOMING", sip_call_cb_notify_ws),
    # SIPCallStateCallback("DISCONNECTED", sip_call_cb_notify_ws),
    SIPCallStateCallback("ANY", cs_cb_on_callstate_call_manager_update)
]

# Callbacks to run when an IM Delivery Status is received to SIPAccount
on_im_status_callbacks = [
    # SIPInstantMessageStatusStateCallback(im_cb_check_if_message_accepted)
]
call_callbacks = [
    SIPCallCallback("call_state", cs_cb_on_callstate_call_manager_update, on_state_text="ANY"),
    SIPCallCallback("call_state", sip_call_cb_notify_ws, "ANY"),
    SIPCallCallback("call_state", cb_on_endcall_remove_from_call_manager, on_state_text="DISCONNECTED"),
    SIPCallCallback("end_call", cb_on_endcall_remove_from_call_manager)

]

class IntercomSIPHandler():
    def __init__(self, bind_ip_address: str, bind_sip_port: int, sip_identifier: str):
        self.sip_handler = SIPHandler(bind_ip_address, bind_sip_port)
        self.sip_identifier = sip_identifier
        
    def run(self):
        self.sip_handler.create_endpoint()
        self.sip_handler.register_account(self.sip_identifier)
        self.sip_handler.account.onCallCallbacks = call_callbacks
        while not stop_event.is_set():
            time.sleep(1)
        self.stop()

    def stop(self):
        self.sip_handler.stop()
