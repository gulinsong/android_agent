package com.openclaw.chitchat

import okhttp3.*
import okio.ByteString

interface RealtimeListener {
    fun onOpen()
    fun onEvent(event: Int, sessionId: String?, payload: ByteArray?)
    fun onAudio(payload: ByteArray)
    fun onError(code: Int, msg: String)
    fun onClose(code: Int, reason: String)
}

class RealtimeClient(
    private val apiKey: String,
    private val connectId: String,
    private val listener: RealtimeListener
) {
    private val client = OkHttpClient()
    private var ws: WebSocket? = null

    fun connect() {
        val request = Request.Builder().url(Config.WS_URL).apply {
            Config.headers(apiKey, connectId).forEach { (k, v) -> header(k, v) }
        }.build()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = listener.onOpen()
            override fun onMessage(webSocket: WebSocket, text: String) {
                // 服务端主要走二进制，文本兜底忽略
            }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val data = bytes.toByteArray()
                try {
                    val msg = Protocol.unmarshal(data)
                    when (msg.type) {
                        Protocol.MsgType.FULL_SERVER -> listener.onEvent(msg.event, msg.sessionId, msg.payload)
                        Protocol.MsgType.AUDIO_ONLY_SERVER -> {
                            val p = msg.payload
                            if (p != null) listener.onAudio(p)
                        }
                        Protocol.MsgType.ERROR -> listener.onError(msg.event, msg.payload?.toString(Charsets.UTF_8) ?: "")
                        else -> {}
                    }
                } catch (e: Exception) {
                    listener.onError(-1, "unmarshal failed: ${e.message}")
                }
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
                listener.onClose(-1, "failure: ${t.message}")
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = listener.onClose(code, reason)
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(1000, null) }
        })
    }

    fun send(bytes: ByteArray): Boolean = ws?.send(ByteString.of(*bytes)) ?: false
    fun close() { ws?.close(1000, null); ws = null }
}
