package kr.auto.titration.mobile.thermal;

import androidx.activity.ComponentActivity;
import androidx.lifecycle.Lifecycle;
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
    private static PreviewManagerII manager;
    private static Lifecycle installedLifecycle;
    private static final WeakHashMap<PreviewManagerII, F2StreamCallback> callbacks = new WeakHashMap<>();
    private static final WeakHashMap<PreviewManagerII, OfficialProcessedF2Frame> latestFrames = new WeakHashMap<>();
    private static OsdBgCallbackBean latestOsd;
    private static Pair<PreviewInfoDataBean, Integer> latestOfflineCallback;

    private PreviewManagerIIAppBinding() {}

    public static synchronized PreviewManagerII installLifecycle(ComponentActivity activity) {
        if (activity == null) {
            throw new IllegalArgumentException("PreviewManagerII requires a non-null ComponentActivity lifecycle");
        }
        return installLifecycle(activity.getLifecycle());
    }

    static synchronized PreviewManagerII installLifecycle(Lifecycle lifecycle) {
        if (lifecycle == null) {
            throw new IllegalArgumentException("PreviewManagerII requires a non-null lifecycle");
        }
        if (manager != null && installedLifecycle == lifecycle) {
            return manager;
        }
        if (manager != null) {
            callbacks.remove(manager);
            latestFrames.remove(manager);
            manager.closePreviewCallback();
        }
        installedLifecycle = lifecycle;
        manager = new PreviewManagerII(lifecycle, false, false);
        return manager;
    }

    public static synchronized PreviewManagerII manager() {
        if (manager == null) {
            throw new IllegalStateException(
                    "PreviewManagerII lifecycle is not installed; construct OfficialPreviewHost with a ComponentActivity before using the official preview manager");
        }
        return manager;
    }

    public static synchronized void bind(PreviewManagerII manager, F2StreamCallback callback) {
        PreviewManagerII current = manager();
        if (manager != current) {
            throw new IllegalStateException("stale PreviewManagerII cannot be bound after lifecycle replacement");
        }
        current.openPreviewCallback();
        callbacks.put(current, callback);
    }

    public static synchronized void unbind(PreviewManagerII manager) {
        if (manager == null) return;
        callbacks.remove(manager);
        latestFrames.remove(manager);
        manager.closePreviewCallback();
    }

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
        synchronized (PreviewManagerIIAppBinding.class) {
            if (manager != PreviewManagerIIAppBinding.manager) return;
            F2StreamCallback callback = callbacks.get(manager);
            if (callback == null) return;
            latestFrames.put(manager, new OfficialProcessedF2Frame(
                    frameCounter, packet.length, officialWidth, officialHeight, streamInfo, offline, processorBucket));
            callback.onFrame(new F2StreamFrame(userId, frameCounter, width, height, frameType, dataType, streamType, packet));
        }
    }
}
