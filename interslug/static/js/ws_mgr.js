import { RTCHandler } from "./conn_mgr.js";
import { SIPHandler } from "./sip_mgr.js";

export function sendMessage(socket, msg_body, msg_channel, attempts=0) {
    if (socket.readyState !== WebSocket.OPEN) {
        attempts++
        if(attempts <= 10) {
            console.log(`WS not open, scheduling for resend. attempts=${attempts}`)
            const delay_ms = 100 * attempts
            setTimeout(() => {
                sendMessage(socket, msg_body, msg_channel, attempts)
            }, delay_ms)
            return
        } else {
            console.error(`WS not open. failed ${attempts}, not retrying`)
            return
        }
    }
    const msg_obj = {
        channel: msg_channel,
        message: msg_body
    }
    console.log(`Sending message. channel=${msg_channel}`, msg_obj)
    socket.send(JSON.stringify(msg_obj))
}


export class SocketHandler {
    constructor() {
        this.ws = new WebSocket("wss://pi4b.localhost.direct:8765");
        this.rtc = new RTCHandler(this.ws);
        this.sip = new SIPHandler(this.ws, this.rtc);
        this.addDefaultListeners();
    }
    addDefaultListeners() {

        this.ws.addEventListener("message", (ev) => {
            console.log("on-message", ev);
            console.log("this", this)
            this.processIncomingMessage(ev);
        });
        this.ws.addEventListener("open", (ev) => {
            console.log("on-open", ev);
            console.log("this", this)
            this.processOnOpen(ev);
        });
    }

    processOnOpen() {
        this.rtc.initialise()
    }

    async processIncomingMessage(ev) {
        const socket = this.ws
        const msgBody = JSON.parse(ev.data);
        console.log(`incoming message channel=${msgBody.channel}`, msgBody.message);
        switch (msgBody.channel) {
            case ("rtc"):
                await this.rtc.handleIncomingMsg(msgBody.message);
                break;
            case ("sip"):
                await this.sip.handleIncomingMsg(msgBody.message);
                break;
            case ("sys"):
                sendMessage(socket, "pong", "sys")
                break;
        }
    }
}