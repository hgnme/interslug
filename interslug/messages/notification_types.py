from dataclasses import dataclass

@dataclass
class NotificationOnCallStatus():
    call_status: str
    call_id: str
    acc_id: str
    local_uri: str
    remote_uri: str
    type: str = "on_call_status"