package com.openclaw.chitchat

import android.Manifest
import android.annotation.SuppressLint
import android.media.audiofx.AcousticEchoCanceler
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.annotation.RequiresPermission
import kotlinx.coroutines.*

class AudioRecorder(private val scope: CoroutineScope) {
    private var record: AudioRecord? = null
    private var job: Job? = null
    private var aec: AcousticEchoCanceler? = null
    @Volatile private var running = false

    @SuppressLint("MissingPermission")
    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    fun start(onChunk: (ByteArray) -> Unit) {
        val minBuf = AudioRecord.getMinBufferSize(
            Config.INPUT_SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val bufSize = maxOf(minBuf, Config.AUDIO_CHUNK_BYTES * 4)
        record = AudioRecord(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            Config.INPUT_SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufSize
        )
        // 启用硬件回声消除，避免播放声被录回触发误 ASR/自我打断
        val sid = record?.audioSessionId ?: 0
        aec = AcousticEchoCanceler.create(sid)
        if (aec != null && AcousticEchoCanceler.isAvailable()) aec?.enabled = true
        Log.i("AR", "AEC available=${AcousticEchoCanceler.isAvailable()} enabled=${aec?.enabled}")
        running = true
        record?.startRecording()
        job = scope.launch(Dispatchers.IO) {
            val buf = ByteArray(Config.AUDIO_CHUNK_BYTES)
            while (isActive && running) {
                val n = record?.read(buf, 0, buf.size) ?: -1
                if (n > 0) onChunk(buf.copyOf(n))
                delay(Config.SEND_INTERVAL_MS)
            }
        }
    }

    fun stop() {
        running = false
        job?.cancel()
        aec?.release()
        aec = null
        record?.stop()
        record?.release()
        record = null
    }
}
