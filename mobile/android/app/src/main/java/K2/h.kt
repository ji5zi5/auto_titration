package K2

import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.PreviewInfoDataBean

class h(
    private val manager: PreviewManagerII,
    private val processingEpoch: Long,
) : (PreviewInfoDataBean) -> Unit {
    override fun invoke(value: PreviewInfoDataBean) {
        PreviewManagerII.f(manager, value, processingEpoch)
    }
}
