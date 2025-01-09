import { sendMessage } from './ws_mgr.js'

class PhoneButtons {
    constructor(type, onAnswer = null, onDecline = null) {
        this.declineButton = null
        this.answerButton = null
        this.phoneButtons = null

        this.createPhoneButtons(type, onAnswer, onDecline)
    }
    disableButtons() {
        if(this.answerButton) {
            this.answerButton.disabled = true
        }
        if(this.declineButton) {
            this.declineButton.disabled = true
        }
    }
    createPhoneButtons(type, onAnswer, onDecline) {
        if(document.getElementById("phone_buttons") !== null) {
            document.getElementById("phone_buttons").remove()
        }
        // Create the container div
        const phoneButtons = document.createElement("div");
        phoneButtons.classList.add("phone_buttons", "phone_buttons-hidden");
        phoneButtons.id = "phone_buttons";
    
        if(type == "incoming") {
            // Create the Answer button
            const answerButton = document.createElement("button");
            answerButton.id = "answer";
            answerButton.textContent = "Answer";
            answerButton.addEventListener("click", onAnswer);
            this.answerButton = answerButton
        
            // Create the Decline button
            const declineButton = document.createElement("button");
            declineButton.id = "decline";
            declineButton.textContent = "Decline";
            declineButton.addEventListener("click", onDecline);
            this.declineButton = declineButton
            // Append buttons to the container
            phoneButtons.appendChild(answerButton);
            phoneButtons.appendChild(declineButton);
        } else if(type == "active_call") {        
            // Create the Decline button
            const declineButton = document.createElement("button");
            declineButton.id = "decline";
            declineButton.textContent = "Disconnect";
            declineButton.addEventListener("click", onDecline);
            this.declineButton = declineButton

            phoneButtons.appendChild(declineButton);
        } 
    
        // Append the container to the body (or another parent element)
        document.body.appendChild(phoneButtons);
        this.buttons = phoneButtons
    }    
    // Show or hide the buttons
    showPhoneButtons() {
        this.buttons.classList.remove("phone_buttons-hidden");
    }

    hidePhoneButtons() {
        this.buttons.classList.add("phone_buttons-hidden");
    }
    deletThis() {
        this.buttons.remove()
        this.buttons = null
    }
}
export class SIPHandler {
    constructor(ws, rtc) {
        this.socket = ws
        this.rtc = rtc
        this.current_call = null
        this.incoming_call = null
        this.calls = {}
        this.requestCallList()
        self = this
        this.callStatusElement = document.getElementById("callstatus")

        this.buttons = new PhoneButtons("incoming", () => {
            self.answerIncomingCall()
            self.buttons.disableButtons()
        }, () => {
            self.declineIncomingCall()
            self.buttons.disableButtons()
        })

        /* Check for call list every 5 seconds, stop if there's no calls 
         */
        this.intervalIdentifier = setInterval(() => {
            if (self.checkHasActiveCalls()) {
                self.requestCallList()
            }
        }, 5000)
    }
    sendSIPMessage(type, body = {}) {
        body.type = type
        sendMessage(this.socket, body, "SIP")
    }
    setIncomingCall(call) {
        this.incoming_call = call
        this.buttons.showPhoneButtons()
        // Show answer buttons
    }
    checkHasActiveCalls() {
        for (const callId in this.calls) {
            if(this.calls[callId].callStateString !== "DISCONNECTED") {
                return true
            }
        }
        return false
    }
    requestCallList() {
        this.sendSIPMessage("get_call_list")
    }
    processCallStatusMsg(msg) {
        const call = msg.call
        this.calls[call.callIdString] = call
        this.callStatusElement.textContent = call.callStateString

        switch(call.callStateString) {
            case ("INCOMING"):
                this.setIncomingCall(call);
                break;
            case ("DISCONNECTED"):
                this.onCallDisconnected(call)

        }

        console.log(call.call_status)
    }
    processCallListMsg(msg) {
        console.log("Incoming call List", msg.calls)
        this.calls = msg.calls
        for (const callId in this.calls) {
            if(this.incoming_call && this.incoming_call.callIdString == callId) {
                this.incoming_call = this.calls[callId]
            }
            if(this.current_call && this.current_call.callIdString == callId) {
                this.current_call = this.calls[callId]
                this.callStatusElement.textContent = this.current_call.callStateText
            }
        }
    }
    processCallAnswered(msg) {
        console.log("call_answered", msg.call)
        this.onCallConnectConfirmed(msg.call)
    }
    processCallDisconnected(msg) {
        this.onCallEndConfirmed()
    }
    requestConnectToCall(call_id) {
        // Send answer message to server
        this.sendSIPMessage("answer_call", {call_id: call_id})
    }
    declineCall(call_id) {
        // Send answer message to server
        this.sendSIPMessage("decline_call", {call_id: call_id})
    }
    endCall(call_id) {
        this.sendSIPMessage("end_call", {call_id: call_id})
    }
    answerIncomingCall() {
        this.requestConnectToCall(this.incoming_call.callIdString)
    }
    declineIncomingCall() {
        this.declineCall(this.incoming_call.callIdString)
    }
    endCurrentCall() {
        this.endCall(this.current_call.callIdString)
    }
    onCallConnectConfirmed(call) {
        this.current_call = call
        this.incoming_call = null
        this.buttons = new PhoneButtons("active_call", null, () => {
            self.endCurrentCall()
            self.buttons.disableButtons()
        })
        this.buttons.showPhoneButtons()
    }
    onCallEndConfirmed() {
        this.buttons.deletThis()
        this.rtc.players.forEach(player => {
            player.kill()            
        });

    }
    onCallDisconnected(call) {
        if(this.current_call && this.current_call.callIdString == call.callIdString) {
            /* TODO: HANDLE DISCONNECT CURRENT CALL */
            // this.buttons.hidePhoneButtons()
        }
        if(this.incoming_call && this.incoming_call.callIdString == call.callIdString) {
            /* TODO: HANDLE DISCONNECT CURRENT CALL */
            this.buttons.hidePhoneButtons()
        }

    }
    async handleIncomingMsg(msg) {
        console.log("SIP Message", msg.type)
        switch(msg.type) { 
            case "call_list":
                this.processCallListMsg(msg)
                break;
            case "on_call_status":
                this.processCallStatusMsg(msg)
                break;
            case "call_answered":
                this.processCallAnswered(msg)
                break;
            case "call_disconnected":
                this.processCallDisconnected(msg)
                break;
        }
    }
}
