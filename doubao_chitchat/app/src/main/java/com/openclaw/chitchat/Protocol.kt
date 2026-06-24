package com.openclaw.chitchat

import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

object Protocol {
    enum class MsgType(val bits: Int) {
        FULL_CLIENT(1), AUDIO_ONLY_CLIENT(2),
        FULL_SERVER(9), AUDIO_ONLY_SERVER(11), ERROR(15)
    }

    const val FLAG_WITH_EVENT = 0b0100
    private const val VERSION_1 = 0x10
    private const val HEADER_SIZE_4 = 0x1
    private const val SER_JSON = 0b0001 shl 4   // serialization=JSON in high nibble
    private const val SER_RAW = 0b0000           // serialization=RAW
    private const val COMPRESSION_NONE = 0

    // sessionId 写入规则：事件 1/2/50/51/52 不带
    private val NO_SESSION_EVENTS = setOf(1, 2, 50, 51, 52)

    data class Message(
        var type: MsgType = MsgType.FULL_CLIENT,
        var typeFlag: Int = 0,
        var event: Int = 0,
        var sessionId: String? = null,
        var sequence: Int = 0,
        var errorCode: Long = 0,
        var payload: ByteArray? = null
    )

    private fun header(dos: DataOutputStream, type: MsgType, typeFlag: Int, serialization: Int) {
        dos.writeByte(VERSION_1 or HEADER_SIZE_4)                       // 0x11
        dos.writeByte((type.bits shl 4) or (typeFlag and 0x0F))         // type<<4 | flag
        dos.writeByte(serialization or COMPRESSION_NONE)                // ser | comp
        dos.writeByte(0)                                                // reserved
    }

    private fun writeEvent(dos: DataOutputStream, msg: Message) {
        if ((msg.typeFlag and FLAG_WITH_EVENT) != 0) dos.writeInt(msg.event)
    }

    private fun writeSessionId(dos: DataOutputStream, msg: Message) {
        if ((msg.typeFlag and FLAG_WITH_EVENT) == 0) return
        if (msg.event in NO_SESSION_EVENTS) return
        val bytes = (msg.sessionId ?: "").toByteArray(Charsets.UTF_8)
        dos.writeInt(bytes.size)
        dos.write(bytes)
    }

    private fun writePayload(dos: DataOutputStream, msg: Message) {
        val p = msg.payload
        if (p == null) dos.writeInt(0) else { dos.writeInt(p.size); dos.write(p) }
    }

    fun marshal(msg: Message): ByteArray {
        val baos = ByteArrayOutputStream(); val dos = DataOutputStream(baos)
        header(dos, msg.type, msg.typeFlag, SER_JSON)
        writeEvent(dos, msg); writeSessionId(dos, msg); writePayload(dos, msg)
        return baos.toByteArray()
    }

    fun marshalRawAudio(msg: Message): ByteArray {
        val baos = ByteArrayOutputStream(); val dos = DataOutputStream(baos)
        header(dos, msg.type, msg.typeFlag, SER_RAW)
        writeEvent(dos, msg); writeSessionId(dos, msg); writePayload(dos, msg)
        return baos.toByteArray()
    }

    fun unmarshal(data: ByteArray): Message {
        val buf = ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN)
        buf.get() // version|headerSize (0x11)
        val typeAndFlag = buf.get().toInt() and 0xFF
        buf.get() // serialization|compression
        buf.get() // reserved
        val msg = Message()
        msg.type = enumValues<MsgType>().first { it.bits == ((typeAndFlag shr 4) and 0x0F) }
        msg.typeFlag = typeAndFlag and 0x0F
        if ((msg.typeFlag and FLAG_WITH_EVENT) != 0) msg.event = buf.int
        if ((msg.typeFlag and FLAG_WITH_EVENT) != 0 && msg.event !in NO_SESSION_EVENTS) {
            val size = buf.int
            if (size > 0) { val b = ByteArray(size); buf.get(b); msg.sessionId = String(b, Charsets.UTF_8) }
        }
        if (msg.type == MsgType.ERROR) msg.errorCode = buf.int.toLong() and 0xFFFFFFFFL
        val psize = buf.int
        if (psize > 0) { msg.payload = ByteArray(psize); buf.get(msg.payload!!) }
        return msg
    }

    fun startConnection(): ByteArray {
        val m = Message(type = MsgType.FULL_CLIENT, typeFlag = FLAG_WITH_EVENT, event = 1,
            payload = "{}".toByteArray(Charsets.UTF_8))
        return marshal(m)
    }

    fun startSession(sid: String, json: String): ByteArray {
        val m = Message(type = MsgType.FULL_CLIENT, typeFlag = FLAG_WITH_EVENT, event = 100,
            sessionId = sid, payload = json.toByteArray(Charsets.UTF_8))
        return marshal(m)
    }

    fun audioFrame(sid: String, pcm: ByteArray): ByteArray {
        val m = Message(type = MsgType.AUDIO_ONLY_CLIENT, typeFlag = FLAG_WITH_EVENT, event = 200,
            sessionId = sid, payload = pcm)
        return marshalRawAudio(m)
    }

    fun eventMessage(sid: String, json: String, event: Int): ByteArray {
        val m = Message(type = MsgType.FULL_CLIENT, typeFlag = FLAG_WITH_EVENT, event = event,
            sessionId = sid, payload = json.toByteArray(Charsets.UTF_8))
        return marshal(m)
    }

    fun generateSessionId(): String = UUID.randomUUID().toString()
}
