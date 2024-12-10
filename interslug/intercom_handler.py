from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from hgn_sip.sip_account import SIPAccount
    from hgn_sip.sip_handler import SIPHandler

from pjsua2 import CallInfo, OnInstantMessageStatusParam, SipRxData
from hgn_sip.sip_call import SIPCall
from hgn_sip.sip_handler import SIPHandler
from hgn_sip.sip_callbacks import SIPCallStateCallback, SIPInstantMessageStatusStateCallback
from logging_config import get_logger
from intercom_sender import UnlockButtonPushXML
from config import WALL_PANELS

# Set up the intercom to listen on FAKEID@IP
# Setup hooks to answer when call is answered, to send unlock message
# call, call_account, call_info

class WallPanel():
    def __init__(self, ip: str, name: str, sip_handle: str, building: int):
        self.ip = ip
        self.name = name
        self.sip_handle = sip_handle
        self.building = building
        self.sip_uri = f"sip:2{self.sip_handle}@{self.ip}:5060"
    def get_sip_name(self):
        return f"\"W-{self.sip_handle}\""

# cbf
wall_panels = WALL_PANELS

# Return the Building number for a specific wallpanel, this will determine whether doors open or not (when calling unlock)
def get_wall_panel_building(remote_uri: str):
    for panel in wall_panels:
        if panel.sip_uri == remote_uri:
            return panel.building

# Callback which is triggered when a SIPCall is Connected
# This will send a SIP MESSAGE to the RemoteURI (wallpanel prob) containing the Unlock XML
# as though you had just pressed "Unlock" on the Intercom
def cs_cb_send_unlock_on_connected(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'CallInfo'):
    logger = get_logger("cs_cb_send_unlock_on_connected")
    logger.info("Callback has been triggered")

    building = get_wall_panel_building(call_info.remoteUri)
    floor = 4 if building == 3 else 12
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
    for panel in wall_panels:
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
    SIPCallStateCallback("CONFIRMED", cs_cb_send_unlock_on_connected)
]
# Callbacks to run when an IM Delivery Status is received to SIPAccount
on_im_status_callbacks = [
    SIPInstantMessageStatusStateCallback(im_cb_check_if_message_accepted)
]


class IntercomSIPHandler():
    def __init__(self, bind_ip_address: str, bind_sip_port: int, sip_identifier: str):
        self.sip_handler = SIPHandler(bind_ip_address, bind_sip_port)
        self.sip_identifier = sip_identifier
        
    def run(self):
        self.sip_handler.create_endpoint()
        self.sip_handler.register_account(self.sip_identifier)
        self.sip_handler.account.onCallStateCallbacks = on_call_state_callbacks
        self.sip_handler.account.onInstantMessageCallbacks = on_im_status_callbacks

    def stop(self):
        self.sip_handler.stop()
