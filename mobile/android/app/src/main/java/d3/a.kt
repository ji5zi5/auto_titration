package d3

/** Official d3.a helper: rotate a rectangular short plane 90 degrees clockwise. */
class a private constructor() {
    fun a(array2D: Array<ShortArray>): Array<ShortArray> {
        if (array2D.isEmpty()) return array2D
        val width = array2D[0].size
        val rotated = Array(width) { ShortArray(array2D.size) }
        for (x in 0 until width) {
            for (y in rotated[x].indices) {
                rotated[x][y] = array2D[rotated[x].size - (y + 1)][x]
            }
        }
        return rotated
    }

    companion object {
        @JvmField
        val a: a = a()
    }
}
