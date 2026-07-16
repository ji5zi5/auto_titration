package f3

import android.util.Size

open class i : k {
    companion object {}

    private val previewSize: Size = Z2.a.a.o()
    private val videoSize: Size = Z2.a.a.j()
    private var frameRate: Int = 25
    private val thermalSize: Size = Z2.a.a.m()
    private val rawSize: Size = Z2.a.a.k()
    private var coding: Int = 8
    private var packetSize: Int = 102_944
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
