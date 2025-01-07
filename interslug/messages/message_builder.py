
import json


def message_to_str(body, channel, callId:str = None):
    obj = {
        "channel": channel,
        "message": body
    }
    if callId is not None:
        obj["callId"] = callId
    json_str = json.dumps(obj)
    return json_str