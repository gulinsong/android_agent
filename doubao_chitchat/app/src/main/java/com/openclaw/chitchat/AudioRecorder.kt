package com.openclaw.chitchat

import android.Manifest
import android.annotation.SuppressLint
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
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
    private var ns: NoiseSuppressor? = null
    private var agc: AutomaticGainControl? = null
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
        ns = NoiseSuppressor.create(sid)
        if (ns != null && NoiseSuppressor.isAvailable()) ns?.enabled = true
        agc = AutomaticGainControl.create(sid)
        if (agc != null && AutomaticGainControl.isAvailable()) agc?.enabled = true
        Log.i("AR", "AEC=${aec?.enabled} NS=${ns?.enabled} AGC=${agc?.enabled}")
        running = true
        record?.startRecording()
        job = scope.launch(Dispatchers.IO) {
            val buf = ByteArray(Config.AUDIO_CHUNK_BYTES)
            var logCnt = 0
            while (isActive && running) {
                val n = record?.read(buf, 0, buf.size) ?: -1
                if (n > 0) {
                    val rms = computeRms(buf, n)
                    // 回声/噪音能量小(RMS<RMS_THRESHOLD)→上传静音包保持时序；真语音才真传
                    if (rms >= RMS_THRESHOLD) onChunk(buf.copyOf(n))
                    else onChunk(ByteArray(n))
                    if (++logCnt % 50 == 0) Log.i("AR", "rms=$rms gated=${rms < RMS_THRESHOLD}")
                }
                delay(Config.SEND_INTERVAL_MS)
            }
        }
    }

    fun stop() {
        running = false
        job?.cancel()
        aec?.release()
        aec = null
        ns?.release()
        ns = null
        agc?.release()
        agc = null
        record?.stop()
        record?.release()
        record = null
    }

    private fun computeRms(buf: ByteArray, n: Int): Double {
        var sum = 0L
        var count = 0
        var i = 0
        while (i + 1 < n) {
            val s = ((buf[i].toInt() and 0xFF) or (buf[i + 1].toInt() shl 8)).toShort().toInt()
            sum += s.toLong() * s
            count++
            i += 2
        }
        return if (count > 0) Math.sqrt(sum.toDouble() / count) else 0.0
    }

    companion object {
        // 回声/静音 RMS 门限：低于此值上传静音包(保持时序，服务端VAD不触发回声)
        // 按 AR 日志的 rms 调：回声通常 <500，正常说话 >1500
        private const val RMS_THRESHOLD = 1500.0
    }
}
