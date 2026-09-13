package K2

import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.PreviewInfoDataBean

class i(
    private val manager: PreviewManagerII,
    private val previewInfoData: PreviewInfoDataBean,
    private val frameNumStamp: Int,
    private val processingEpoch: Long,
    private val lifecycleGeneration: Long,
) : Runnable {
    override fun run() {
        PreviewManagerII.e(
            manager,
            previewInfoData,
            frameNumStamp,
            processingEpoch,
            lifecycleGeneration,
        )
    }
}
