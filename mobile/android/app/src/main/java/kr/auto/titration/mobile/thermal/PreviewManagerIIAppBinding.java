package kr.auto.titration.mobile.thermal;

import com.hik.f2module.F2StreamCallback;
import com.hik.f2module.F2StreamFrame;

import com.hik.viewer.manager.PreviewManagerII;
import com.hik.viewercommon.data.bean.OsdBgCallbackBean;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.WeakHashMap;
import kotlin.Pair;

/** App-side binding for observing official PreviewManagerII after G(byte[]) has completed. */
public final class PreviewManagerIIAppBinding {
    private static final PreviewManagerII MANAGER = new PreviewManagerII(null, false, false);
    private static final WeakHashMap<PreviewManagerII, F2StreamCallback> callbacks = new WeakHashMap<>();
    private static final WeakHashMap<PreviewManagerII, OfficialProcessedF2Frame> latestFrames = new WeakHashMap<>();
    private static OsdBgCallbackBean latestOsd;
    private static Pair<PreviewInfoDataBean, Integer> latestOfflineCallback;

    private PreviewManagerIIAppBinding() {}

    public static PreviewManagerII manager() { return MANAGER; }

    public static synchronized void bind(PreviewManagerII manager, F2StreamCallback callback) {
        manager.openPreviewCallback();
        callbacks.put(manager, callback);
    }

    public static synchronized void unbind(PreviewManagerII manager) { callbacks.remove(manager); }

    public static synchronized OfficialProcessedF2Frame latestOfficialProcessedFrame(PreviewManagerII manager, long frameCounter) {
        OfficialProcessedF2Frame frame = latestFrames.get(manager);
        return frame != null && frame.frameCounter == frameCounter ? frame : null;
    }

    public static synchronized Pair<PreviewInfoDataBean, Integer> latestExecutedOfflineCallback() { return latestOfflineCallback; }

    public static synchronized void onOsd(OsdBgCallbackBean bean) { latestOsd = bean; }

    public static synchronized void onOfflineCallback(PreviewInfoDataBean info, int stamp) {
        latestOfflineCallback = new Pair<>(info, stamp);
    }

    public static void afterOfficialG(PreviewManagerII manager, int userId, long frameCounter,
                                      int width, int height, int frameType, int dataType, int streamType,
                                      byte[] packet, int officialWidth, int officialHeight,
                                      PreviewStreamInfo streamInfo, boolean offline, String processorBucket) {
        F2StreamCallback callback;
        synchronized (PreviewManagerIIAppBinding.class) {
            latestFrames.put(manager, new OfficialProcessedF2Frame(
                    frameCounter, packet.length, officialWidth, officialHeight, streamInfo, offline, processorBucket));
            callback = callbacks.get(manager);
        }
        if (callback != null) {
            callback.onFrame(new F2StreamFrame(userId, frameCounter, width, height, frameType, dataType, streamType, packet));
        }
    }
}
