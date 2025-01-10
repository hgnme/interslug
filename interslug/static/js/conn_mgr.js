import { sendMessage } from './ws_mgr.js'

class AudioPlayer {
    constructor() {
        const el = document.createElement("audio")
        // <audio id="remoteAudio" autoplay controls></audio>
        el.id = "call_audio_player"
        el.controls = true
        el.autoplay = true
        this.el = el
        document.body.appendChild(this.el)
    }
    attachStream(stream) {
        this.el.srcObject = stream
        this.el.play()
    }
    kill() {
        this.el.srcObject = null
        this.el.currentTime = 0
        this.el.remove()
    }
}
export class RTCHandler {
    constructor(socket) {
        this.socket = socket
        this.pc = new RTCPeerConnection()
        this.addDefaultListeners()
        this.players = []
    }

    addDefaultListeners() {
        this.pc.addEventListener("icecandidate", ev => {
            this.onICECandidate(ev)
        })
        this.pc.addEventListener("track", ev => {
            this.onTrack(ev)
        })
        this.pc.addEventListener("negotiationneeded", ev => {
            this.onNegotiationNeeded(ev)
        })
    }
    onICECandidate(event) {
        console.log("onIceCandidate", event)
        if (event.candidate) {
            const ip = event.candidate.address
            if(ip.indexOf("172") !== -1) {
                console.log(`Ignoring candidate based on IP ip=${ip}`)
                return
            }
            const cd = event.candidate
            const log_str = `candidate received: ${cd.protocol}://${cd.address}:${cd.port}.\nfull_candidate=${cd.candidate}`
            console.log(log_str)
            const cd_obj = {
                component: event.candidate.component,
                foundation: event.candidate.foundation,
                ip: event.candidate.address,
                port: event.candidate.port,
                priority: event.candidate.priority,
                protocol: event.candidate.protocol,
                type: event.candidate.type,
                relatedAddress: event.candidate.relatedAddress,
                relatedPort: event.candidate.relatedPort,
                sdpMid: event.candidate.sdpMid,
                sdpMLineIndex: event.candidate.sdpMLineIndex,
                tcpType: event.candidate.tcpType 
            }
            sendMessage(this.socket, {type: "icecandidate",candidate: cd_obj}, "rtc")
        }
        
    }
    onNegotiationNeeded(event) {
        console.log("onNegotiationNeeded", event)
        /* Update Local Desc then send */
        this.sendOffer()
    }
    onTrack(event) {
        console.log("onTrack", event)
        // Ensure it's an audio track
        if (event.track.kind === 'audio') {
            console.log(`Received track: ${event.track.id}, kind: ${event.track.kind}`);
            console.log(`Track details: codec: ${event.track.kind}, state: ${event.track.readyState}`);
            
            const audioPlayer = new AudioPlayer()
            audioPlayer.attachStream(event.streams[0])
            // Additional debug info
            console.log(`Track attached to <audio> element. Stream id: ${event.streams[0].id}`);
            this.players.push(audioPlayer)
        }
    }
    async initialise() {
        await this.sendOffer()
    }
    async sendOffer() {
        const offer = await this.pc.createOffer()
        await this.pc.setLocalDescription(offer)
        sendMessage(this.socket, {type: "offer", sdp: offer.sdp}, "rtc")
    }
    async updateRemoteDescription(msg) {
        const sdp = msg["sdp"]
        const type = msg["type"]
        const rd = new RTCSessionDescription({type: type, sdp: sdp})
        await this.pc.setRemoteDescription(rd)
    }
    async updateLocalDescription(offer_answer) {
        await this.pc.setLocalDescription(offer_answer);
    }
    async respondToOffer(msg) {
        await this.updateRemoteDescription(msg);
        const answer = await this.pc.createAnswer();
        await this.updateLocalDescription(answer);

        const msg_resp = {type: "answer", sdp: answer.sdp}
        console.log("Sending Offer Response")
        sendMessage(this.socket, msg_resp, "rtc")
    }
    async handleIncomingMsg(msg) {
        if (msg.type == "answer") {
            console.log("Processing answer response")
            this.updateRemoteDescription(msg)
        } else if (msg.type == "offer") {
            console.log("Responding to offer")
            this.respondToOffer(msg)
        }
    }
}