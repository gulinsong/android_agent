package com.openclaw.chitchat

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class ProtocolTest {
    // 文档示例：StartConnection 帧，payload "{}" = [123,125]
    private val startConnExpected = byteArrayOf(
        17, 20, 16, 0,            // header: 0x11, 0x14, 0x10, 0x00
        0, 0, 0, 1,               // event=1
        0, 0, 0, 2,               // payload size=2
        123, 125                  // "{}"
    )

    @Test fun startConnection_bytes_match_doc() {
        assertArrayEquals(startConnExpected, Protocol.startConnection())
    }

    @Test fun unmarshal_startConnection_reads_event() {
        val msg = Protocol.unmarshal(startConnExpected)
        assertEquals(Protocol.MsgType.FULL_CLIENT, msg.type)
        assertEquals(1, msg.event)
        assertArrayEquals("{}".toByteArray(Charsets.UTF_8), msg.payload)
    }

    @Test fun audio_frame_uses_raw_serialization_and_event_200() {
        val pcm = ByteArray(640) { (it and 0xFF).toByte() }
        val frame = Protocol.audioFrame("sess-id", pcm)
        val msg = Protocol.unmarshal(frame)
        assertEquals(Protocol.MsgType.AUDIO_ONLY_CLIENT, msg.type)
        assertEquals(200, msg.event)
        assertEquals("sess-id", msg.sessionId)
        assertArrayEquals(pcm, msg.payload)
    }

    @Test fun startSession_includes_session_id_and_event_100() {
        val frame = Protocol.startSession("abc", "{}")
        val msg = Protocol.unmarshal(frame)
        assertEquals(Protocol.MsgType.FULL_CLIENT, msg.type)
        assertEquals(100, msg.event)
        assertEquals("abc", msg.sessionId)
    }

    @Test fun round_trip_generic_event_message() {
        val frame = Protocol.eventMessage("sid", "{\"content\":\"hi\"}", 300)
        val msg = Protocol.unmarshal(frame)
        assertEquals(300, msg.event)
        assertEquals("sid", msg.sessionId)
        assertEquals("{\"content\":\"hi\"}", String(msg.payload!!, Charsets.UTF_8))
    }
}
