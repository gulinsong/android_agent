package com.openclaw.chitchat

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.*

enum class CallState { IDLE, CONNECTING, READY, LISTENING, USER_SPEAKING, ASSISTANT_SPEAKING, FINISHING, RECONNECTING, ERROR }

interface CallUi {
    fun onState(s: CallState)
    fun onAsrText(text: String, isFinal: Boolean)
    fun onError(msg: String)
}

class CallManager(
    private val scope: CoroutineScope,
    private val apiKey: String,
    private val ui: CallUi
) : RealtimeListener {
    private val gson = Gson()
    private var client: RealtimeClient? = null
    private var recorder: AudioRecorder? = null
    private var player: AudioPlayer? = null
    private var sessionId: String = Protocol.generateSessionId()
    private var dialogId: String = ""

    @Volatile private var connected = false
    @Volatile private var sessionReady = false
    @Volatile private var finishing = false
    private var reconnectAttempts = 0

    private var sessionReadySignal: CompletableDeferred<Unit>? = null

    suspend fun start() {
        setState(CallState.CONNECTING)
        player = AudioPlayer(scope).also { it.start() }
        client = RealtimeClient(apiKey, sessionId, this)
        client?.connect()
    }

    override fun onOpen() {
        connected = true
        scope.launch { handshake() }
    }

    private suspend fun handshake() {
        client?.send(Protocol.startConnection())
        val payload = Config.toStartSessionJson()
        sessionReadySignal = CompletableDeferred()
        client?.send(Protocol.startSession(sessionId, payload))
        try {
            withTimeout(30_000) { sessionReadySignal?.await() }
        } catch (e: Exception) {
            ui.onError("会话启动超时"); setState(CallState.ERROR); return
        }
        client?.send(Protocol.eventMessage(
            sessionId, gson.toJson(mapOf("content" to "你好，我是小闲，有什么想聊的吗？")), 300))
        recorder = AudioRecorder(scope)
        recorder?.start { chunk -> client?.send(Protocol.audioFrame(sessionId, chunk)) }
        setState(CallState.LISTENING)
    }

    override fun onEvent(event: Int, sessionId: String?, payload: ByteArray?) {
        Log.i("CM", "event=$event sid=$sessionId payload=${payload?.toString(Charsets.UTF_8)?.take(80)}")
        scope.launch {
            when (event) {
                150 -> { // SessionStarted
                    payload?.toString(Charsets.UTF_8)?.let {
                        runCatching {
                            dialogId = gson.fromJson(it, JsonObject::class.java)
                                .get("dialog_id")?.asString ?: ""
                        }
                    }
                    sessionReadySignal?.complete(Unit)
                }
                450 -> { player?.interrupt(); setState(CallState.USER_SPEAKING) } // ASRInfo 打断
                451 -> { // ASRResponse 识别文本
                    payload?.toString(Charsets.UTF_8)?.let { raw ->
                        runCatching {
                            val obj = gson.fromJson(raw, JsonObject::class.java)
                            val arr = obj.getAsJsonArray("results")
                            arr?.forEach { r ->
                                val ro = r.asJsonObject
                                ui.onAsrText(
                                    ro.get("text")?.asString ?: "",
                                    !(ro.get("is_interim")?.asBoolean ?: true)
                                )
                            }
                        }
                    }
                }
                459 -> setState(CallState.LISTENING)          // ASREnded
                350 -> setState(CallState.ASSISTANT_SPEAKING) // TTSSentenceStart
                359 -> setState(CallState.LISTENING)          // TTSEnded
                51, 153 -> reconnect("连接/会话失败 event=$event")
                599 -> payload?.toString(Charsets.UTF_8)?.let { ui.onError("服务端错误: $it") }
            }
        }
    }

    override fun onAudio(payload: ByteArray) {
        val head = payload.take(8).joinToString(",") { "%02X".format(it.toInt() and 0xFF) }
        Log.i("CM", "onAudio size=${payload.size} head=$head")
        player?.feed(payload)
    }

    override fun onError(code: Int, msg: String) {
        ui.onError("错误[$code]: $msg")
        if (code.toString().startsWith("5") || code == -1) reconnect("onError $code")
    }

    override fun onClose(code: Int, reason: String) {
        if (finishing) return
        reconnect("连接关闭: $reason")
    }

    private fun reconnect(reason: String) {
        if (finishing) return
        if (reconnectAttempts >= 3) {
            setState(CallState.ERROR); ui.onError("重连失败：$reason"); return
        }
        reconnectAttempts++
        setState(CallState.RECONNECTING)
        scope.launch {
            delay(1000L shl (reconnectAttempts - 1)) // 1s, 2s, 4s
            recorder?.stop(); player?.stop(); client?.close()
            connected = false; sessionReady = false
            sessionId = Protocol.generateSessionId()
            start()
        }
    }

    suspend fun finish() {
        finishing = true
        setState(CallState.FINISHING)
        recorder?.stop()
        runCatching { client?.send(Protocol.eventMessage(sessionId, "{}", 102)) } // FinishSession
        delay(200)
        client?.close()
        player?.stop()
        setState(CallState.IDLE)
    }

    private fun setState(s: CallState) { ui.onState(s) }
}
