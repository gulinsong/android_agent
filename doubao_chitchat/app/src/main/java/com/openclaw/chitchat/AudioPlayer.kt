package com.openclaw.chitchat

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel

class AudioPlayer(private val scope: CoroutineScope) {
    private var track: AudioTrack? = null
    private var job: Job? = null
    @Volatile private var channel: Channel<ByteArray>? = null
    @Volatile private var running = false

    fun start() {
        val sampleRate = Config.OUTPUT_SAMPLE_RATE
        val bufSize = AudioTrack.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        track = AudioTrack(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build(),
            AudioFormat.Builder().setSampleRate(sampleRate)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build(),
            maxOf(bufSize, 8192),
            AudioTrack.MODE_STREAM,
            AudioManager.AUDIO_SESSION_ID_GENERATE
        )
        channel = Channel(capacity = 64)
        running = true
        track?.play()
        Log.i("AP", "AudioTrack state=${track?.state} playState=${track?.playState} sr=$sampleRate")
        // 单一播放协程，全程不重启（避免多协程并发 write 导致 native SIGSEGV）
        job = scope.launch(Dispatchers.IO) {
            val ch = channel ?: return@launch
            var wrote = 0L
            try {
                for (pcm in ch) {
                    if (!running) break
                    if (pcm.size % 2 == 0) {
                        track?.write(pcm, 0, pcm.size)
                        wrote += pcm.size
                        if (wrote % 48000 < pcm.size) Log.i("AP", "wrote=$wrote playState=${track?.playState}")
                    }
                }
            } catch (_: CancellationException) {}
        }
    }

    fun feed(pcm: ByteArray) {
        channel?.trySend(pcm)
    }

    /** 打断：排空已排队音频 + flush AudioTrack buffer 立即静音。
     *  不重启协程（单一 job 串行 write，避免并发 write 的 native 崩溃）。
     *  后续 feed 的新音频由同一 job 继续消费。ASRInfo(450) 时调用。 */
    fun interrupt() {
        val ch = channel ?: return
        var drained = 0
        while (ch.tryReceive().isSuccess) { drained++ }
        track?.pause()
        track?.flush()
        track?.play()
        Log.i("AP", "interrupted, drained=$drained")
    }

    /** suspend：先停播放协程(join)再 release track，避免 release 后 write 的 SIGSEGV。 */
    suspend fun stop() {
        running = false
        channel?.close()
        job?.join()
        track?.stop()
        track?.flush()
        track?.release()
        track = null
        channel = null
        Log.i("AP", "stopped")
    }
}
