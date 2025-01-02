# Set up the intercom to listen on FAKEID@IP
# Setup hooks to answer when call is answered, to send unlock message
# call, call_account, call_info

class WallPanel():
    def __init__(self, ip: str, name: str, sip_handle: str, building: int, label: str):
        self.ip = ip
        self.name = name
        self.label = label
        self.sip_handle = sip_handle
        self.building = building
        self.sip_uri = f"sip:2{self.sip_handle}@{self.ip}:5060"
    def get_sip_name(self):
        return f"\"W-{self.sip_handle}\""

# Return the Building number for a specific wallpanel, this will determine whether doors open or not (when calling unlock)
def get_wall_panel_building(remote_uri: str, wall_panels: list[WallPanel]):
    for panel in wall_panels:
        if panel.sip_uri == remote_uri:
            return panel.building