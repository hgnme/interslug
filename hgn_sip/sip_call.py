import pjsua2 as pj
from logging_config import get_logger
from .sip_buddy import SIPBuddy
from .sip_callbacks import SIPCallStateCallback

def get_call_param(code:int) -> pj.CallOpParam:
    ret = pj.CallOpParam()
    ret.statusCode = code
    return ret
    
class SIPCall(pj.Call):
    def __init__(self, acc, call_id = pj.PJSUA_INVALID_ID, callbacks: list[SIPCallStateCallback] = []):
        # Init logger
        self.logger = get_logger("new-call")
        self.logger.info(f"Initialising new call. call_id={call_id}")
        # Init the PJSUA2 Call with the Account and Call ID provided from SIPAccount
        pj.Call.__init__(self, acc, call_id)
        self.acc = acc
        self.connected = False
        self.msg_sent = False
        self.call_id = call_id
        self.onCallStateCallBacks = callbacks
        self.is_outgoing = True if call_id == pj.PJSUA_INVALID_ID else False
    
    def end_call(self):
        self.logger.info("Hanging up call")
        self.hangup(get_call_param(pj.PJSIP_SC_REQUEST_TERMINATED))
    
    def make_call(self, remote_uri):
        cs = pj.CallSetting(True)
        cs.audioCount = 1
        cs.videoCount = 0
        params = pj.CallOpParam(True)
        params.opt = cs
        self.makeCall(remote_uri, params)

    def onCallState(self, param: pj.OnCallStateParam):
        # When call state changes, this runs. Depending on the state, do different things.
        # param has nothing useful, so just get info straight away.
        ci: pj.CallInfo = self.getInfo()
        self.logger.debug(f"Call state change. state={ci.state} stateText={ci.stateText} lastReason={ci.lastReason} accId={ci.accId} callIdString={ci.callIdString} localUri={ci.localUri} remoteUri={ci.remoteUri} lastReason={ci.lastReason}")
        if ci.stateText == "INCOMING":
            # Incoming call, mark it as as Ringing
            self.logger.debug("Call incoming, marking as Ringing")
            self.answer(get_call_param(pj.PJSIP_SC_RINGING))
        elif ci.stateText == "EARLY" and ci.lastReason == "Ringing" and not self.is_outgoing:
            # Call changed to Early, answering ("accepting") (only if it's not Incoming)
            self.logger.debug("Call ringing, marking as Accepted")
            self.answer(get_call_param(pj.PJSIP_SC_ACCEPTED))
        elif ci.stateText == "CONFIRMED" and ci.lastReason == "Accepted":
            # Call is connected and live.
            self.logger.debug("Call is now live.")
            self.connected = True    
        elif ci.stateText == "DISCONNECTED":
            self.logger.debug("Call disconnected")
            self.acc.delete_call(self.call_id)
        
        # Execute all callbacks based on their StateText
        for cb in self.onCallStateCallBacks:
            if ci.stateText == cb.on_state_text:
                cb.execute(call = self, call_info = ci)
        
    # How the fk does Media Work in this
    def onCallMediaState(self, prm: pj.OnCallMediaStateParam):
        self.logger.info("on call media state")
        ci: pj.CallInfo = self.getInfo()
        mi: pj.CallMediaInfo = ci.media

    # Dont think sending IMs in calls is even a thing?
    def onInstantMessageStatus(self, param: pj.OnInstantMessageStatusParam):
        self.logger.info(f"onInstantMessageStatusCall: code={param.code}, reason={param.reason}")

    # Same here. Can delete
    def onInstantMessage(self, param: pj.OnInstantMessageParam):
        contactUri = param.contactUri
        contentType = param.contentType
        fromUri = param.fromUri
        msgBody = param.msgBody
        toUri = param.toUri
        self.logger.info(f"onInstantMessageCall: contactUri={contactUri}, contentType={contentType}, fromUri={fromUri}, toUri={toUri}, msgBody={msgBody}")
