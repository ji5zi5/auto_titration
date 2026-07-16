package f3

import android.util.Size

class a : k {
    private val previewSize: Size = Size(0, 0)
    private val videoSize: Size = Size(0, 0)
    private var frameRate: Int = 0
    private val thermalSize: Size = Size(0, 0)
    private val rawSize: Size = Size(0, 0)
    private var coding: Int = 0
    private var packetSize: Int = 0
    private var streamingNew: Boolean = false
    private val supportsIfr: Boolean = false
    private val supportsFusion: Boolean = false

    override fun a(): Size = thermalSize
    override fun b(value: Int) { packetSize = value }
    override fun c(): Size = previewSize
    override fun d(value: Int) { coding = value }
    override fun e(): List<Int> = arrayListOf(f())
    override fun f(): Int = packetSize
    override fun g(): Size = rawSize
    override fun h(value: Boolean) { streamingNew = value }
    override fun i(): Boolean = supportsIfr
    override fun j(): Size = videoSize
    override fun k(): Int = coding
    override fun l(): Int = frameRate
    override fun m(): Boolean = supportsFusion
    override fun n(): Boolean = streamingNew
    override fun o(value: Int) { frameRate = value }
}
