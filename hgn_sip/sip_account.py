import pjsua2 as pj
from logging_config import get_logger
from .sip_buddy import SIPBuddy
from .sip_call import SIPCall, get_call_param
from .sip_callbacks import SIPCallStateCallback, SIPInstantMessageStatusStateCallback

def dumb_cb(call_info: pj.CallInfo):
    logger = get_logger("call-callback")
    logger.debug(f"Callback triggered. callIdString={call_info.callIdString}, stateText={call_info.stateText}, uri={call_info.remoteUri}")

class SIPAccount(pj.Account):
    def __init__(self, ep):
        super().__init__()
        self.logger = get_logger("sip_account")
        self.calls:list[SIPCall] = []
        self.buddies:list[SIPBuddy] = []
        self.ep = ep
        self.onCallStateCallbacks: list[SIPCallStateCallback] = []
        self.onInstantMessageCallbacks: list[SIPInstantMessageStatusStateCallback] = []
        
    # Delete call from stored list based on call_id.
    # Called after the call hangs up...
    def delete_call(self, call_id):
        for call in self.calls:
            if call.call_id == call_id:
                self.calls.remove(call)
    
    # Find active call for a given URI (Buddy)
    def find_call(self, remote_uri):
        self.logger.info(f"searching for call. remote_uri={remote_uri}")
        for call in self.calls:
            ci: pj.CallInfo = call.getInfo()
            self.logger.debug(f"Checking call for match. call_id={ci.callIdString}, remote_uri={ci.remoteUri}")
            if ci.remoteUri == remote_uri:
                self.logger.info(f"call match. call_id={ci.callIdString}, remote_uri={ci.remoteUri}")
                return call
        self.logger.info(f"no buddy match. remote_uri={remote_uri}")
        return None
    
    # Register buddy for a given URI. This will then allow us to send it an IM during a call, etc.
    def create_buddy(self, remote_uri):
        self.logger.info(f"creating buddy. remote_uri={remote_uri}")
        buddy_cfg = pj.BuddyConfig()
        buddy_cfg.uri = remote_uri
        buddy = SIPBuddy(self)
        buddy.createBuddy(buddy_cfg)
        self.buddies.append(buddy)
        return buddy

    # Get a buddy if exists
    def find_buddy(self, remote_uri):
        self.logger.info(f"searching for buddy. remote_uri={remote_uri}")
        for buddy in self.buddies:
            bi: pj.BuddyInfo = buddy.getInfo()
            if bi.uri == remote_uri:
                self.logger.info(f"buddy found. remote_uri={remote_uri}")
                return buddy
        self.logger.info(f"no buddy match. remote_uri={remote_uri}")
        return None
    
    def find_or_create_buddy(self, remote_uri) -> SIPBuddy:
        buddy: SIPBuddy = self.find_buddy(remote_uri)
        if buddy is None:
            buddy = self.create_buddy(remote_uri)
        return buddy
    
    def destroy(self):
        ai: pj.AccountInfo = self.getInfo()
        self.logger.info(f"Destroying SIPAccount. uri={ai.uri}")
        self.logger.info("Ending active calls")
        for call in self.calls:
            # Check if call's not hungup and then hangup
            ci: pj.CallInfo = call.getInfo()
            if ci.stateText != "DISCONNECTED":
                self.logger.info(f"Ending call. id={ci.callIdString}")
                call.hangup(get_call_param(pj.PJSIP_SC_REQUEST_TERMINATED))
            if call in self.calls:
                self.calls.remove(call)
        self.logger.info("Unregistering Buddies")
        for buddy in self.buddies:
            bi: pj.BuddyInfo = buddy.getInfo()
            pj.Buddy
            self.logger.info(f"Unregistering Buddy. uri={bi.uri}")
            self.buddies.remove(buddy)
        self.logger.info("Shutting down SIPAccount")
        self.shutdown()
    
    # Function to send an IM to a target RemoteURI with specified message content
    def send_im_to_remote_uri(self, remote_uri: str, message_body: str, content_type: str = "text/plain"):
        # Find or create buddy
        dest_buddy = self.find_or_create_buddy(remote_uri)
        # Send message to buddy
        mp = pj.SendInstantMessageParam()
        mp.content = message_body
        mp.contentType = content_type
        try: 
            self.logger.info(f"Attempting to send buddy IM. remote_uri={remote_uri}")
            dest_buddy.sendInstantMessage(mp)
            self.logger.info(f"Message sent")
        except pj.Error as e:
            self.logger.error(f"Failed to send message: {e}")

    # PJSUA2's onInstantMessage event. When an Instant Message is RECEIVED
    def onInstantMessage(self, param: pj.OnInstantMessageParam):
        contactUri = param.contactUri
        contentType = param.contentType
        fromUri = param.fromUri
        msgBody = param.msgBody
        toUri = param.toUri
        self.logger.info(f"onInstantMessageAccount: contactUri={contactUri}, contentType={contentType}, fromUri={fromUri}, toUri={toUri}, msgBody={msgBody}")

    # PJSUA2's onInstantMessageStatus event. Updated status on the DELIVERY of a SENT Instant Message
    def onInstantMessageStatus(self, param: pj.OnInstantMessageStatusParam):
        for cb in self.onInstantMessageCallbacks:
            cb.execute(im_status_param = param, sip_account = self)

        self.logger.info(f"onInstantMessageStatus: code={param.code}, reason={param.reason} rdata.info={param.rdata.info} toUri={param.toUri} userData={param.userData}")

    # PJSUA2's OnIncomingCall event. This will create the Buddy and create the new Call object.
    def onIncomingCall(self, param: pj.OnIncomingCallParam):
        self.logger.info(f"Account receiving incoming call. callid={param.callId}")
        call = SIPCall(self, call_id = param.callId, callbacks = self.onCallStateCallbacks)
        ci: pj.CallInfo = call.getInfo()
        buddy = self.find_or_create_buddy(ci.remoteUri)
        self.logger.info(f"Incoming call detected and created. callId={param.callId}, remoteUri={ci.remoteUri}, accId={ci.accId}, callIdString={ci.callIdString}")
        self.calls.append(call)