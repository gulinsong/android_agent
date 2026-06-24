package com.openclaw.chitchat

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class AudioPlayer(private val scope: CoroutineScope) {
    private var track: AudioTrack? = null
    private var job: Job? = null
    private val mutex = Mutex()
    @Volatile private var channel: Channel<ByteArray>? = null
    @Volatile private var running = false

    fun start() {
        val sampleRate = Config.OUTPUT_SAMPLE_RATE
        val bufSize = AudioTrack.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        track = AudioTrack(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
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
        job = scope.launch(Dispatchers.IO) {
            val ch = channel!!
            try {
                for (pcm in ch) {
                    if (!running) break
                    if (pcm.size % 2 == 0) track?.write(pcm, 0, pcm.size)
                }
            } catch (_: CancellationException) {}
        }
    }

    fun feed(pcm: ByteArray) {
        channel?.trySend(pcm)
    }

    /** 打断：清空排队音频 + 立即静音。ASRInfo(450) 时调用。 */
    fun interrupt() = runBlocking {
        mutex.withLock {
            val old = channel
            old?.close()
            channel = Channel(capacity = 64)
            track?.pause()
            track?.flush()
            track?.play()
        }
    }

    fun stop() {
        running = false
        channel?.close()
        job?.cancel()
        track?.stop()
        track?.flush()
        track?.release()
        track = null
    }
}
