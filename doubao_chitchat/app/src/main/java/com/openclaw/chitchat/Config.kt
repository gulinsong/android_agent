package com.openclaw.chitchat

import com.google.gson.Gson

object Config {
    const val WS_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
    const val RESOURCE_ID = "volc.speech.dialog"
    const val APP_KEY = "PlgvMymc7f3tQnJ6"

    const val INPUT_SAMPLE_RATE = 16000
    const val OUTPUT_SAMPLE_RATE = 24000
    const val CHANNELS = 1
    const val AUDIO_CHUNK_BYTES = 640        // 20ms @ 16kHz int16
    const val SEND_INTERVAL_MS = 20L

    const val DEFAULT_SPEAKER = "zh_female_xiaohe_jupiter_bigtts"  // 小何：甜美活泼女声，台湾口音
    const val MODEL = "1.2.1.1"              // O2.0（修正：demo 用 "O"）
    const val PCM_FORMAT = "pcm_s16le"
    const val LOUDNESS_RATE = 100  // 输出音量增益[-50,100]，2.0模型，100=最大

    const val DEFAULT_SYSTEM_ROLE = "你是一个温暖、幽默、知识广博的车载语音伙伴。陪用户聊天解闷，回答简洁自然，像朋友一样。"
    const val DEFAULT_SPEAKING_STYLE = "说话简洁口语化，语气亲切自然。"
    const val DEFAULT_BOT_NAME = "小闲"

    fun headers(apiKey: String, connectId: String): Map<String, String> = mapOf(
        "X-Api-Key" to apiKey,
        "X-Api-Resource-Id" to RESOURCE_ID,
        "X-Api-App-Key" to APP_KEY,
        "X-Api-Connect-Id" to connectId
    )

    private data class AudioConfig(val channel: Int = CHANNELS, val format: String = PCM_FORMAT, val sample_rate: Int = OUTPUT_SAMPLE_RATE, val loudness_rate: Int = LOUDNESS_RATE)
    private data class TtsExtra(val enable_loudness_norm: Boolean = true)
    private data class Tts(val speaker: String, val audio_config: AudioConfig = AudioConfig(), val extra: TtsExtra = TtsExtra())
    private data class DialogExtra(val model: String = MODEL, val input_mod: String = "audio", val strict_audit: Boolean = false)
    private data class Dialog(val dialog_id: String = "", val bot_name: String = DEFAULT_BOT_NAME,
                              val system_role: String, val speaking_style: String = DEFAULT_SPEAKING_STYLE,
                              val extra: DialogExtra = DialogExtra())
    private data class Asr(val extra: Map<String, Any> = mapOf("end_smooth_window_ms" to 2000))
    private data class StartSession(val asr: Asr = Asr(), val tts: Tts, val dialog: Dialog)

    fun toStartSessionJson(systemRole: String = DEFAULT_SYSTEM_ROLE, speaker: String = DEFAULT_SPEAKER): String {
        val payload = StartSession(tts = Tts(speaker), dialog = Dialog(system_role = systemRole))
        return Gson().toJson(payload)
    }
}
