package f3

open class f : i() {
    companion object {}

    private var coding: Int = 11
    private var packetSize: Int = 206_392
    private var streamingNew: Boolean = true

    override fun b(value: Int) { packetSize = value }
    override fun d(value: Int) { coding = value }
    override fun f(): Int = packetSize
    override fun h(value: Boolean) { streamingNew = value }
    override fun k(): Int = coding
    override fun n(): Boolean = streamingNew
}
