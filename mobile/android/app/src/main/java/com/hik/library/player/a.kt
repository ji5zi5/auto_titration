package com.hik.library.player

import android.os.CountDownTimer
import android.view.SurfaceHolder
import java.util.concurrent.CopyOnWriteArrayList

/** Official BasePlayer listener/lifecycle contract. */
abstract class a(private val holder: SurfaceHolder?, private val timeoutInMillis: Long) : c {
    open val currentPosition: Long = 0L
    open val currentUri: String = ""
    open val totalDuration: Long = 0L
    protected val playListeners = CopyOnWriteArrayList<b>()
    protected var countDownTimer: CountDownTimer = object : CountDownTimer(timeoutInMillis, timeoutInMillis) {
        override fun onTick(millisUntilFinished: Long) = Unit
        override fun onFinish() { playListeners.forEach { it.b() } }
    }
    fun addPlayListener(listener: b) { playListeners.addIfAbsent(listener) }
    fun removeAllPlayListener() = playListeners.clear()
    fun removePlayListener(listener: b) { playListeners.remove(listener) }
    open fun pause() = playListeners.forEach { it.onPause() }
    open fun resume() = playListeners.forEach { it.onResume() }
    override fun start(uri: String, mode: Int) {
        if (holder?.surface?.isValid == true) { playListeners.forEach { it.onStart() }; countDownTimer.start() }
        else playListeners.forEach { it.a() }
    }
    open fun stop() { countDownTimer.cancel(); playListeners.forEach { it.onStop() } }
}
