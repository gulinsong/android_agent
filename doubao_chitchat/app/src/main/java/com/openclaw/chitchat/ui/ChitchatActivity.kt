package com.openclaw.chitchat.ui

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Bundle
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.openclaw.chitchat.BuildConfig
import com.openclaw.chitchat.CallManager
import com.openclaw.chitchat.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class ChitchatActivity : AppCompatActivity() {
    private val vm = ChitchatViewModel()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var manager: CallManager? = null
    private lateinit var audioManager: AudioManager
    private var focusRequest: AudioFocusRequest? = null

    private val requestMic = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) beginSession() else vm.onError("需要麦克风权限") }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_chitchat)
        audioManager = getSystemService(AUDIO_SERVICE) as AudioManager

        findViewById<TextView>(R.id.stateText).apply {
            vm.state.observe(this@ChitchatActivity) { text = vm.stateText(it) }
        }
        vm.subtitle.observe(this@ChitchatActivity) {
            findViewById<TextView>(R.id.subtitleText).text = it
        }
        vm.errorMsg.observe(this@ChitchatActivity) {
            findViewById<TextView>(R.id.errorText).text = it
        }
    }

    override fun onResume() {
        super.onResume()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED
        ) beginSession() else requestMic.launch(Manifest.permission.RECORD_AUDIO)
    }

    override fun onPause() {
        super.onPause()
        scope.launch { manager?.finish() }
        abandonFocus()
    }

    private fun beginSession() {
        if (manager != null) return
        if (BuildConfig.DOUBAO_API_KEY.isBlank()) {
            vm.onError("未配置 DOUBAO_API_KEY（~/.gradle/gradle.properties）"); return
        }
        requestFocus()
        manager = CallManager(scope, BuildConfig.DOUBAO_API_KEY, vm)
        scope.launch { manager?.start() }
    }

    private fun requestFocus() {
        val attrs = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).build()
        focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attrs).build()
        audioManager.requestAudioFocus(focusRequest!!)
    }

    private fun abandonFocus() {
        focusRequest?.let { audioManager.abandonAudioFocusRequest(it) }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }
}
