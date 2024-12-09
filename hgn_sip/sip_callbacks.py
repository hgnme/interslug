from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import pjsua2 as pj
    from .sip_call import SIPCall
    from .sip_account import SIPAccount

# A callback object which will be executed when a target call state is achieved, with the provided parameters.

# Target use is that a call has been answered, so I'm going to then callback the Account's SendMessage thing to send the unlock
class SIPCallStateCallback(): 
    def __init__(self, on_state_text: str, cb_fn):
        self.on_state_text = on_state_text
        self.callback_fn = cb_fn
    def execute(self, call: 'SIPCall', call_info: 'pj.CallInfo'):
        call_account: 'SIPAccount' = call.acc
        self.callback_fn(call, call_account, call_info)


# Really I'll just use this to validate that the IM i send has been accepted in its response
class SIPInstantMessageStatusStateCallback():
    def __init__(self, cb_fn):
        self.callback_fn = cb_fn
    def execute(self, im_status_param: 'pj.OnInstantMessageStatusParam', sip_account: 'SIPAccount'):
        self.callback_fn(im_status_param, sip_account)