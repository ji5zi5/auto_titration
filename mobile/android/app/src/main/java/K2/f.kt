package K2

import com.hik.viewer.manager.PreviewManagerII

class f(private val manager: PreviewManagerII) : (Boolean) -> Unit {
    override fun invoke(value: Boolean) {
        PreviewManagerII.c(manager, value)
    }
}
