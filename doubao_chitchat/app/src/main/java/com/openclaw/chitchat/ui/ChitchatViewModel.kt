package com.openclaw.chitchat.ui

import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.openclaw.chitchat.CallState
import com.openclaw.chitchat.CallUi

class ChitchatViewModel : ViewModel(), CallUi {
    val state = MutableLiveData(CallState.IDLE)
    val subtitle = MutableLiveData("")
    val errorMsg = MutableLiveData("")

    override fun onState(s: CallState) { state.postValue(s) }
    override fun onAsrText(text: String, isFinal: Boolean) { subtitle.postValue(text) }
    override fun onError(msg: String) { errorMsg.postValue(msg) }

    fun stateText(s: CallState?): String = when (s) {
        CallState.IDLE -> "空闲"
        CallState.CONNECTING -> "连接中…"
        CallState.READY, CallState.LISTENING -> "聆听中"
        CallState.USER_SPEAKING -> "你说话中"
        CallState.ASSISTANT_SPEAKING -> "回复中"
        CallState.RECONNECTING -> "重连中…"
        CallState.FINISHING -> "结束中…"
        CallState.ERROR -> "出错"
        null -> ""
    }
}
