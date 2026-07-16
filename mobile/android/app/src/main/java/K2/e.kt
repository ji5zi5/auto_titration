package K2

import com.hik.viewer.manager.PreviewManagerII

class e(private val manager: PreviewManagerII) : Runnable {
    override fun run() {
        PreviewManagerII.g(manager)
    }
}
