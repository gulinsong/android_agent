package com.openclaw.chitchat

import android.Manifest
import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.annotation.RequiresPermission
import kotlinx.coroutines.*

class AudioRecorder(private val scope: CoroutineScope) {
    private var record: AudioRecord? = null
    private var job: Job? = null
    @Volatile private var running = false

    @SuppressLint("MissingPermission")
    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    fun start(onChunk: (ByteArray) -> Unit) {
        val minBuf = AudioRecord.getMinBufferSize(
            Config.INPUT_SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val bufSize = maxOf(minBuf, Config.AUDIO_CHUNK_BYTES * 4)
        record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            Config.INPUT_SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufSize
        )
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
        record?.stop()
        record?.release()
        record = null
    }
}
