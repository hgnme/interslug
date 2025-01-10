from typing import TYPE_CHECKING
from interslug.state.call_manager import global_call_manager
from logging_config import get_logger

if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_account import SIPAccount
    from pjsua2 import CallInfo

# Callback provided to the SIPAccount, triggered on CallState Changes
def cs_cb_on_callstate_call_manager_update(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'CallInfo'):
    l = get_logger(f"cs_cb_on_callstate_call_manager_update[{call_info.callIdString}]")

    if call_info.callIdString not in global_call_manager.calls:
        l.debug("Call doesn't exist in global_call_manager yet, registering")
        call_state = global_call_manager.add_call(call_info.callIdString, call)
    else: 
        # Change this to a callstate updater via the manager.
        call_state = global_call_manager.calls[call_info.callIdString]
    
    call_state.update_call_info(call_info)

def cb_on_endcall_remove_from_call_manager(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'CallInfo'):
    l = get_logger(f"cb_on_endcall_remove_from_call_manager[{call_info.callIdString}]")
    l.debug("calling remove_call from global_call_manager")
    global_call_manager.remove_call(call_info.callIdString)

