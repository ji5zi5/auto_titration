package z3

import kotlin.jvm.functions.Function2

/** Official record-size callback object used by z3.c renderer setup. */
class b : Function2<Int, Int, kotlin.Unit> {
    override fun invoke(width: Int, height: Int): kotlin.Unit = c.a(width, height)
}
