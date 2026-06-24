package com.openclaw.chitchat

import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ConfigPayloadTest {
    @Test fun start_session_json_has_model_1_2_1_1_and_pcm_s16le() {
        val json = Config.toStartSessionJson(systemRole = "你是车载伙伴", speaker = Config.DEFAULT_SPEAKER)
        val root = JsonParser.parseString(json).asJsonObject
        assertEquals("1.2.1.1", root.getAsJsonObject("dialog").getAsJsonObject("extra").get("model").asString)
        assertEquals("audio", root.getAsJsonObject("dialog").getAsJsonObject("extra").get("input_mod").asString)
        val ac = root.getAsJsonObject("tts").getAsJsonObject("audio_config")
        assertEquals("pcm_s16le", ac.get("format").asString)
        assertEquals(24000, ac.get("sample_rate").asInt)
        assertEquals(Config.DEFAULT_SPEAKER, root.getAsJsonObject("tts").get("speaker").asString)
    }

    @Test fun headers_use_apikey_no_appid() {
        val h = Config.headers("KEY456", "cid")
        assertEquals("KEY456", h["X-Api-Key"])
        assertEquals("volc.speech.dialog", h["X-Api-Resource-Id"])
        assertEquals("PlgvMymc7f3tQnJ6", h["X-Api-App-Key"])
        assertEquals("cid", h["X-Api-Connect-Id"])
        assertNull(h["X-Api-App-ID"]) // 新版鉴权不用 App ID（实测确认）
    }
}
