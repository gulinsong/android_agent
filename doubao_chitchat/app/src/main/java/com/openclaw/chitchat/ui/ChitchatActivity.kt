package com.openclaw.chitchat.ui

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Bundle
import android.widget.Button
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
    private lateinit var toggleBtn: Button

    private val requestMic = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> if (!granted) vm.onError("需要麦克风权限") }

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
        toggleBtn = findViewById(R.id.toggleBtn)
        toggleBtn.setOnClickListener { toggle() }
    }

    override fun onResume() {
        super.onResume()
        // 不自动开始会话，等用户点"开始"按钮
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) requestMic.launch(Manifest.permission.RECORD_AUDIO)
    }

    override fun onPause() {
        super.onPause()
        val m = manager
        manager = null
        toggleBtn.text = "开始"
        scope.launch { m?.finish() }
        abandonFocus()
    }

    /** 开始/暂停 切换 */
    private fun toggle() {
        if (manager != null) {
            // 暂停
            val m = manager
            manager = null
            toggleBtn.text = "开始"
            scope.launch { m?.finish() }
            abandonFocus()
        } else {
            // 开始
            beginSession()
        }
    }

    private fun beginSession() {
        if (manager != null) return
        if (BuildConfig.DOUBAO_API_KEY.isBlank()) {
            vm.onError("未配置 DOUBAO_API_KEY（~/.gradle/gradle.properties）"); return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) { requestMic.launch(Manifest.permission.RECORD_AUDIO); return }
        requestFocus()
        manager = CallManager(scope, BuildConfig.DOUBAO_API_KEY, vm)
        toggleBtn.text = "暂停"
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
