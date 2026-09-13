package K2

import com.hik.viewer.manager.PreviewManagerII

class e(private val manager: PreviewManagerII) : Runnable {
    override fun run() {
        try {
            PreviewManagerII.g(manager)
        } catch (error: RuntimeException) {
            manager.onScheduledProcessingFailure(error)
        } catch (error: LinkageError) {
            manager.onScheduledProcessingFailure(error)
        }
    }
}
