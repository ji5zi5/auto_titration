package K2

import com.hik.viewer.manager.PreviewManagerII
import com.hik.viewercommon.data.bean.OsdBgCallbackBean

class g(private val manager: PreviewManagerII) : (Any?) -> Unit {
    override fun invoke(value: Any?) {
        PreviewManagerII.d(manager, value as OsdBgCallbackBean)
    }
}
