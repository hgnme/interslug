import pjsua2 as pj
from logging_config import get_logger

class SIPBuddy(pj.Buddy):
    def __init__(self, acc):
        super().__init__()
        self.logger = get_logger("buddy")
        self.acc = acc
    def createBuddy(self, param: pj.BuddyConfig):
        self.create(self.acc, param)
        bi: pj.BuddyInfo = self.getInfo()
        valid = self.isValid()
        id = self.getId()
        self.logger.info(f"Buddy created: valid={valid}, id={id}")