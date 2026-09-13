package com.hik.viewer.manager;

import android.graphics.Bitmap;
import android.os.Handler;
import android.os.Looper;
import android.util.Size;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.TextView;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.DefaultLifecycleObserver;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.LifecycleOwner;
import androidx.lifecycle.ViewTreeLifecycleOwner;
import com.hcusbsdk.Interface.FStreamCallBack;
import com.hcusbsdk.Interface.USB_FRAME_INFO;
import com.hik.f1module.hcusbcamerasdk.callback.IStreamCallback;
import kr.auto.titration.mobile.thermal.PreviewManagerIIAppBinding;
import com.hik.library.player.b;
import com.hik.viewer.bean.DiagnoseBean;
import com.hik.viewercommon.data.bean.OsdBgCallbackBean;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import com.hik.viewercommon.data.bean.SceneModeBean;
import com.hik.viewercommon.data.bean.UsbModuleType;
import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback;
import hik.common.yyrj.uicommon.data.ModuleType;
import hik.common.yyrj.uicommon.widget.FloatTextureView;
import java.io.File;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.TreeSet;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.function.BiConsumer;
import kotlin.Unit;
import kotlin.jvm.functions.Function0;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2PaletteSnapshot;

public final class PreviewManagerII {
    public static final PreviewManagerII$a D0;

    static {
        D0 = new PreviewManagerII$a(null);
    }

    private final Object lifecycleLock = new Object();
    private Lifecycle a;
    private final boolean b;
    private final boolean c;
    private final int d = 830;
    private int e;
    private int f;
    private int g;
    private float h;
    private float i;
    private volatile OfficialF2PaletteSnapshot N;
    private volatile String paletteSnapshotFailure;
    private volatile String lastStreamProcessingFailure;
    private boolean j;
    private boolean k;
    private volatile boolean streamClosed;
    private volatile long processingEpoch;
    private boolean usbTransitionSuspended;
    private volatile long rendererEpoch;
    private long lifecycleBindingEpoch;
    private boolean previewGraphInitialized;
    private long frameCounter;
    private long invalidPacketStartMs;
    private long lastCallbackAtMs;
    private long firstCallbackAtMs;
    private long streamClosedIngressCount;
    private long packetSizeNotAllowedIngressCount;
    private long mailboxAcceptedIngressCount;
    private long processorAcceptedIngressCount;
    private long appHandoffIngressCount;
    private StreamIngressDiagnostic streamIngressDiagnostic = StreamIngressDiagnostic.notObserved();
    private ScheduledExecutorService x0;
    private ExecutorService C = Executors.newSingleThreadExecutor();

    private volatile V2.f E;
    private X2.b rendererFactoryOverride;
    private g3.a D;
    private f3.k processorProfile;
    private int processorCodingType = -1;
    private Set<Integer> processorAllowedPacketSizes = Collections.emptySet();
    private View G;
    private SurfaceView H;
    private TextView I;
    private FloatTextureView J;
    private SceneModeBean O;
    private Bitmap P;
    private Function1<Boolean, Unit> Q;
    private Function1<Integer, Unit> T;
    private int U;
    private boolean V;
    private boolean W;
    private Function1<Boolean, Unit> X;
    private Function0<Unit> Y;
    private Function0<Unit> Z;
    private Function0<Unit> a0;
    private BiConsumer<Integer, Long> invalidPacketSizeTimeoutCallback;
    private Function0<Unit> b0;
    private Function1<Object, Unit> c0;
    private Function0<Unit> d0;
    private Function0<Unit> e0;
    private Function1<Object, Unit> f0;
    private Function1<DiagnoseBean, Unit> z;
    private Function5<Object, Object, Object, Object, Object, Unit> h0;
    private IStreamCallback B0;
    private FStreamCallBack C0;
    private boolean F = true;
    private boolean L = true;
    private boolean M;
    private boolean R;
    private boolean S = true;
    private boolean q0 = true;
    private boolean m0 = true;
    private PreviewInfoDataBean i0 = new PreviewInfoDataBean();
    private byte[] j0 = new byte[0];
    private boolean l0 = true;
    private byte[] l;
    private byte[] o = new byte[0];
    byte[] r0 = new byte[0];
    byte[] s0 = new byte[0];
    private FrameEnvelope offlineFrameEnvelope;
    private FrameEnvelope normalFrameEnvelope;
    int t0;
    int u0;
    int v0;
    private java.util.List<Object> w0;
    private String y0 = "";
    private String z0 = "";
    private byte[] A0 = new byte[0];
    private float q = 1f;
    private int r;
    private int s;
    private long u;
    private java.util.ArrayList<Object> v;
    private long w;
    private boolean x;
    private int y;
    private int n0;
    private long o0;
    private int p0;
    private Size p = new Size(0, 0);
    private Size m = new Size(0, 0);
    private Size n = new Size(0, 0);
    private Size t = new Size(0, 0);
    private Handler K;
    private final PreviewManagerII$g A = new PreviewManagerII$g(this);
    private final PreviewManagerII$defaultLifecycleObserver$1 B = new PreviewManagerII$defaultLifecycleObserver$1(this);
    private int lastUserId;
    private int lastWidth;
    private int lastHeight;
    private int lastFrameType;
    private int lastDataType;
    private int lastStreamType;
    private long lastFrameNumber;

    public PreviewManagerII(Lifecycle lifecycle, boolean b, boolean c) {
        this.a = lifecycle;
        this.b = b;
        this.c = c;
        this.v = new java.util.ArrayList<>(10);
        try { this.K = new Handler(Looper.getMainLooper()); } catch (RuntimeException ignored) { this.K = null; }
        this.B0 = new PreviewManagerII$e(this);
        this.C0 = new PreviewManagerII$d(this, processingEpoch);
    }

    public final FStreamCallBack R() { return C0; }
    public final IStreamCallback U() { return B0; }
    public final byte[] S() { return A0; }
    public final Size T() { return m; }
    public final int V() { return f; }

    /** Host-neutral equivalent of the official PaletteBean-returning Q(). */
    public final OfficialF2PaletteSnapshot Q() {
        String failure = paletteSnapshotFailure;
        if (failure != null) throw new IllegalStateException(failure);
        return N;
    }

    public final void R0(int pseudoColor) { e = pseudoColor; }
    public final void v0(int agcMode, float wideTempUpThreshold, float wideTempDownThreshold) {
        g = agcMode;
        h = wideTempUpThreshold;
        i = wideTempDownThreshold;
    }
    public final void z0(int ispMode) { f = ispMode; }

    public final void l0(SurfaceView viewerSurfaceView) {
        LifecycleOwner owner = ViewTreeLifecycleOwner.get(viewerSurfaceView);
        if (owner != null) a = owner.getLifecycle();
        hik.common.yyrj.businesscommon.b.d.a().v(d2.a.a());
        A5.y.c.b().K(d2.a.a());
        l0(null, viewerSurfaceView, null, null, null, null, null, null);
    }

    public final void l0(View viewerRootView, SurfaceView viewerSurfaceView, TextView viewerErrorText,
                         FloatTextureView visibleLightView, SceneModeBean sceneModeBean,
                         Function1<Boolean, Unit> freezeCallback,
                         Function1<Boolean, Unit> overlayAvailabilityCallback,
                         Function1<Integer, Unit> frameNumberCallback) {
        boolean initializeGraph;
        V2.f renderer;
        long selectedRendererEpoch;
        Size showSize;
        Lifecycle lifecycle;
        synchronized (lifecycleLock) {
            initializeGraph = !previewGraphInitialized;
            this.G = viewerRootView;
            this.H = viewerSurfaceView;
            this.J = visibleLightView;
            this.I = viewerErrorText;
            this.X = freezeCallback;
            this.O = sceneModeBean;
            this.Q = overlayAvailabilityCallback;
            this.T = frameNumberCallback;
            if (initializeGraph) {
                // Renderer/processor graph attachment can happen after the native stream callback
                // has already been registered. It is not a session boundary, so preserve the
                // callback's processing epoch; open/close/full teardown own epoch invalidation.
                if (s0()) {
                    m = Z2.a.a.p().c();
                    n = Z2.a.a.p().c();
                    t = new Size(m.getWidth(), m.getHeight());
                    if (O != null && (t0() || q0())) { n0(n); p0(); }
                    b1();
                    D = g3.b.a.a(Z2.a.a.p().k(), t0());
                    captureProcessorProfile(Z2.a.a.p());
                } else if (r0()) {
                    m = new Size(120, 160);
                    n = new Size(120, 160);
                    t = new Size(120, 160);
                    com.hik.f1module.F1UsbModuleHelper.INSTANCE.USB_SetYuvSize(t);
                }
                S = u5.B.a.L() == 1;
                U = Z2.g.a.w(Z2.g.a.U().getSerialNumber());
                previewGraphInitialized = true;
            }
            boolean useM4 = rendererFactoryOverride != null || l2.k.a("useM4", true);
            bindOfficialRenderer(viewerSurfaceView, useM4);
            renderer = E;
            selectedRendererEpoch = rendererEpoch;
            showSize = Z2.g.a.E();
            lifecycle = a;
        }
        if (initializeGraph) {
            g1(this, false, 1, null);
        }
        if (renderer != null && isRendererCurrent(selectedRendererEpoch, renderer)) {
            if (rendererFactoryOverride == null && shouldApplyRendererShowSize()) {
                renderer.i(showSize);
            }
            if (isRendererCurrent(selectedRendererEpoch, renderer)) {
                renderer.b(new PreviewManagerII$f(this));
            }
        }
        if (initializeGraph && lifecycle != null && isLifecycleCurrent(lifecycle)) {
            lifecycle.addObserver(B);
        }
    }

    private V2.f bindOfficialRenderer(SurfaceView viewerSurfaceView, boolean useM4) {
        rendererEpoch++;
        X2.b factory = rendererFactoryOverride != null
                ? rendererFactoryOverride
                : (useM4 ? new X2.c() : new X2.a());
        V2.f selected;
        if (rendererFactoryOverride != null) selected = factory.a(viewerSurfaceView);
        else if (!s0()) selected = factory.a(viewerSurfaceView);
        else if (Z2.a.a.t()) selected = factory.c(viewerSurfaceView);
        else selected = factory.b(viewerSurfaceView);
        E = selected;
        return selected;
    }

    private String X() { return Z2.g.a.U().getModuleID(); }
    private ModuleType Y() { return d3.c.a.a(X()); }
    private boolean q0() { return Y() == ModuleType.F2ModuleType.F0; }
    private boolean r0() { return Z2.g.b(Z2.g.a, false, 1, null) == UsbModuleType.F1.INSTANCE; }
    private boolean s0() { return Z2.g.b(Z2.g.a, false, 1, null) == UsbModuleType.F2.INSTANCE; }
    private boolean t0() { return Y() == ModuleType.F2ModuleType.F2V2; }
    private void n0(Size size) { com.hikvision.rid.AnalyzerPaletteRid.a.initRID(size.getWidth(), size.getHeight()); }
    private void p0() {
        String serialNumber = Z2.g.a.U().getSerialNumber();
        File calibration = new File(A5.y.c.b().u(), "HM-Calibration_" + serialNumber + ".dat");
        if (calibration.exists()) calibration.length();
    }
    private void b1() {
        e1();
        x0 = Executors.newSingleThreadScheduledExecutor();
        final long schedulerEpoch = processingEpoch;
        x0.scheduleWithFixedDelay(
                () -> {
                    if (isProcessingEpochCurrent(schedulerEpoch)) new K2.e(this).run();
                },
                0L,
                20L,
                TimeUnit.MILLISECONDS);
    }
    private void e1() { if (x0 != null) x0.shutdownNow(); x0 = null; }

    public final void f1(boolean secondMenuVisible) {
        int showWidth = l2.l.a.b();
        boolean widerThanReportLimit = showWidth > d;
        if (q0() && widerThanReportLimit && !W) showWidth = d;
        int sourceWidth = m.getWidth();
        int sourceHeight = m.getHeight();
        if (sourceWidth <= 0 || sourceHeight <= 0) return;
        int showHeight = (int) (showWidth * (float) sourceHeight / sourceWidth);
        int statusBarHeight = l2.l.a.c();
        int titleBarHeight = l2.n.a.a(44);
        l2.n.a.a(22);
        int firstMenuHeight = l2.n.a.a(72);
        int mediaControllerHeight = l2.n.a.a(120);
        int availableHeight = l2.l.a.a() - (titleBarHeight + statusBarHeight + firstMenuHeight + mediaControllerHeight);
        if (secondMenuVisible) availableHeight -= statusBarHeight;
        if (showHeight > availableHeight) { showWidth = (int) (availableHeight * (float) sourceWidth / sourceHeight); showHeight = availableHeight; }
        if (J != null) {
            int visibleWidth = showWidth / 3;
            int visibleHeight = showHeight / 3;
            J.getLayoutParams().width = visibleWidth + (40 - visibleWidth % 40);
            J.getLayoutParams().height = visibleHeight + (40 - visibleHeight % 40);
            J.requestLayout();
        }
        if (U == 90 || U == 270) {
            showWidth = l2.l.a.b();
            if (q0() && widerThanReportLimit && !W) showWidth = d;
            showHeight = (int) (showWidth * (float) sourceWidth / sourceHeight);
        }
        Size showSize = new Size(showWidth, showHeight);
        if (G != null && G.getLayoutParams() != null) { G.getLayoutParams().width = showWidth; G.getLayoutParams().height = showHeight; }
        if (J != null) h1(this, showSize);
    }

    public final byte[] i1(Size picSize) {
        V2.f renderer;
        long expectedRendererEpoch;
        synchronized (lifecycleLock) {
            renderer = E;
            expectedRendererEpoch = rendererEpoch;
        }
        if (renderer == null) return null;
        byte[] captured = renderer.e(picSize);
        return isRendererCurrent(expectedRendererEpoch, renderer) ? captured : null;
    }
    public final com.hik.library.player.d W(Size picSize) {
        V2.f renderer;
        long expectedRendererEpoch;
        synchronized (lifecycleLock) {
            renderer = E;
            expectedRendererEpoch = rendererEpoch;
        }
        if (renderer == null) return null;
        com.hik.library.player.d captured = renderer.f(picSize);
        return isRendererCurrent(expectedRendererEpoch, renderer) ? captured : null;
    }
    public final void D0(Function1<DiagnoseBean, Unit> callback) { z = callback; }
    public final void G0(Function0<Unit> callback) { Z = callback; }
    public final void setInvalidPacketSizeTimeoutCallback(BiConsumer<Integer, Long> callback) { invalidPacketSizeTimeoutCallback = callback; }
    public final boolean refreshF2ProcessorFromRuntimeProfile() {
        synchronized (lifecycleLock) {
            f3.k profile = Z2.a.a.p();
            if (profile == null
                    || profile.e() == null
                    || profile.e().isEmpty()
                    || profile.e().contains(0)
                    || Z2.g.a.U().getModuleID() == null
                    || Z2.g.a.U().getModuleID().trim().isEmpty()) {
                return false;
            }
            if (D != null && processorProfile == profile && processorMatchesProfile(D, profile)) {
                captureProcessorProfile(profile);
                return true;
            }

            g3.a replacement;
            try {
                replacement = g3.b.a.a(profile.k(), profile.n());
            } catch (RuntimeException error) {
                return false;
            }
            if (replacement == null) return false;

            if (D != null) D.k();
            m = profile.c();
            n = profile.c();
            t = profile.c();
            D = replacement;
            captureProcessorProfile(profile);
            if (!streamClosed && (x0 == null || x0.isShutdown())) b1();
            return true;
        }
    }
    private void captureProcessorProfile(f3.k profile) {
        processorProfile = profile;
        processorCodingType = profile == null ? -1 : profile.k();
        processorAllowedPacketSizes = profile == null || profile.e() == null
                ? Collections.emptySet()
                : Collections.unmodifiableSet(new HashSet<>(profile.e()));
    }
    private int processorCodingType() {
        synchronized (lifecycleLock) {
            return processorCodingType;
        }
    }
    private boolean processorCodingTypeIs12ForEpoch(long expectedEpoch) {
        synchronized (lifecycleLock) {
            return isProcessingEpochCurrentLocked(expectedEpoch) && processorCodingType == 12;
        }
    }
    private boolean processorMatchesProfile(g3.a processor, f3.k profile) {
        Class<?> expectedClass;
        switch (profile.k()) {
            case 8:
                expectedClass = g3.f.class;
                break;
            case 9:
                expectedClass = g3.g.class;
                break;
            case 11:
                expectedClass = g3.c.class;
                break;
            case 12:
                expectedClass = profile.n() ? g3.e.class : g3.d.class;
                break;
            case 10:
            default:
                expectedClass = g3.g.class;
                break;
        }
        return processor.getClass() == expectedClass;
    }
    public final void J0(Function5<Object, Object, Object, Object, Object, Unit> callback) { h0 = callback; }
    public final void K0(Function1<Object, Unit> callback) { c0 = callback; }
    public final void prepareF2RuntimeActivation() {
        synchronized (lifecycleLock) {
            processingEpoch++;
            streamClosed = true;
            usbTransitionSuspended = false;
            e1();
            clearFrameMailboxes();
            N = null;
            paletteSnapshotFailure = null;
            lastStreamProcessingFailure = null;
            frameCounter = 0L;
            firstCallbackAtMs = 0L;
            lastCallbackAtMs = 0L;
            resetIngressDiagnosticsLocked();
            t0 = 0;
            u0 = 0;
            if (D != null) D.k();
            D = null;
            captureProcessorProfile(null);
            if (C != null) C.shutdownNow();
            C = null;
            C0 = null;
        }
    }
    /**
     * Quiesces publication for a reversible native stop while retaining the exact processor,
     * renderer, callback object, and profile owner. A failed native stop can therefore resume the
     * same owner without reconstructing it from mutable runtime profile state.
     */
    public final void suspendF2PublicationForUsbTransition() {
        synchronized (lifecycleLock) {
            streamClosed = true;
            usbTransitionSuspended = true;
            e1();
            clearFrameMailboxes();
            N = null;
            paletteSnapshotFailure = null;
            lastStreamProcessingFailure = null;
            if (C != null) C.shutdownNow();
            C = null;
        }
    }
    public final boolean hasRetainedF2Processor() {
        synchronized (lifecycleLock) {
            return D != null && processorProfile != null;
        }
    }
    public final void adoptHostLifecycle(Lifecycle lifecycle) {
        if (lifecycle == null) throw new IllegalArgumentException("lifecycle must not be null");
        Lifecycle previousLifecycle;
        boolean observerInstalled;
        long bindingEpoch;
        synchronized (lifecycleLock) {
            if (a == lifecycle) return;
            previousLifecycle = a;
            observerInstalled = previewGraphInitialized;
            bindingEpoch = ++lifecycleBindingEpoch;
        }
        if (previousLifecycle != null && observerInstalled) {
            previousLifecycle.removeObserver(B);
        }
        if (observerInstalled) {
            lifecycle.addObserver(B);
        }
        boolean keepObserver;
        synchronized (lifecycleLock) {
            if (lifecycleBindingEpoch != bindingEpoch || a != previousLifecycle) {
                keepObserver = false;
            } else {
                a = lifecycle;
                keepObserver = previewGraphInitialized;
            }
        }
        if (observerInstalled && !keepObserver) {
            lifecycle.removeObserver(B);
        } else if (!observerInstalled && keepObserver) {
            lifecycle.addObserver(B);
        }
    }
    /**
     * Transfers a stop-failed session away from an Activity that is about to be destroyed.
     *
     * <p>The native stream, exact processor, callback object, and renderer generation remain
     * owned by this manager. Removing the old observer prevents the Activity's subsequent
     * ON_DESTROY dispatch from calling {@link #u0()} before a replacement host can adopt the
     * retained manager.
     */
    public final void detachHostLifecycleForTerminalCloseRetry() {
        Lifecycle previousLifecycle;
        boolean observerInstalled;
        synchronized (lifecycleLock) {
            lifecycleBindingEpoch++;
            previousLifecycle = a;
            observerInstalled = previewGraphInitialized;
            a = null;
        }
        if (previousLifecycle != null && observerInstalled) {
            previousLifecycle.removeObserver(B);
        }
    }
    public final void closePreviewCallback() {
        u0();
        synchronized (lifecycleLock) {
            clearFrameMailboxes();
            N = null;
            paletteSnapshotFailure = null;
            firstCallbackAtMs = 0L;
            lastCallbackAtMs = 0L;
        }
    }
    public final void openPreviewCallback() {
        synchronized (lifecycleLock) {
            boolean resumeUsbTransition = usbTransitionSuspended;
            if (!resumeUsbTransition) processingEpoch++;
            streamClosed = false;
            usbTransitionSuspended = false;
            if (!resumeUsbTransition) {
                firstCallbackAtMs = 0L;
                lastCallbackAtMs = 0L;
            }
            lastStreamProcessingFailure = null;
            resetIngressDiagnosticsLocked();
            if (C == null || C.isShutdown()) C = Executors.newSingleThreadExecutor();
            if (C0 == null || !resumeUsbTransition) {
                C0 = new PreviewManagerII$d(this, processingEpoch);
            }
            b1();
        }
    }
    public final void detachOfficialRenderer() {
        V2.f renderer;
        synchronized (lifecycleLock) {
            rendererEpoch++;
            renderer = E;
            E = null;
            H = null;
        }
        if (renderer != null) {
            renderer.stop();
            renderer.c();
            renderer.release();
        }
    }
    public final void u0() {
        V2.f renderer;
        g3.a processor;
        ExecutorService callbackExecutor;
        ScheduledExecutorService scheduler;
        Handler handler;
        synchronized (lifecycleLock) {
            processingEpoch++;
            streamClosed = true;
            usbTransitionSuspended = false;
            rendererEpoch++;
            lifecycleBindingEpoch++;
            renderer = E;
            E = null;
            B0 = null; C0 = null; X = null; Y = null; Z = null; a0 = null; invalidPacketSizeTimeoutCallback = null; b0 = null; c0 = null; d0 = null; e0 = null; f0 = null; h0 = null;
            processor = D;
            D = null;
            captureProcessorProfile(null);
            callbackExecutor = C;
            C = null;
            scheduler = x0;
            x0 = null;
            q0 = true; m0 = true; previewGraphInitialized = false; G = null; H = null; I = null; J = null;
            firstCallbackAtMs = 0L;
            lastCallbackAtMs = 0L;
            handler = K;
        }
        if (renderer != null) {
            renderer.c();
            renderer.release();
        }
        if (processor != null) processor.k();
        if (callbackExecutor != null) callbackExecutor.shutdownNow();
        if (scheduler != null) scheduler.shutdownNow();
        if (handler != null) {
            handler.removeCallbacksAndMessages(null);
        }
    }

    void G(byte[] packet) {
        long epoch;
        synchronized (lifecycleLock) {
            epoch = processingEpoch;
        }
        G(new FrameEnvelope(lastUserId, lastWidth, lastHeight, lastFrameType, lastDataType,
                lastStreamType, lastFrameNumber, epoch, packet));
    }

    private void G(FrameEnvelope frame) {
        byte[] packet = frame.packet();
        PreviewStreamInfo streamInfo;
        String processorBucket;
        g3.a processor;
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
            processor = D;
            if (processor == null) {
                lastStreamProcessingFailure = "preview_processor_unavailable";
                return;
            }
            processorBucket = processor.getClass().getName();
            try {
                processor.j(X, new K2.f(this), c0, h0, new K2.g(this));
                if (processor instanceof g3.d) {
                    ((g3.d) processor).o(new K2.h(this, frame.processingEpoch));
                }
            } catch (RuntimeException | LinkageError error) {
                lastStreamProcessingFailure = processingFailure("processor_setup", error);
                return;
            }
        }
        try {
            streamInfo = processor.d(packet);
        } catch (RuntimeException | LinkageError error) {
            synchronized (lifecycleLock) {
                if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
                lastStreamProcessingFailure = processingFailure("processor", error);
            }
            return;
        }
        recordProcessorAccepted(frame);
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
        }
        handOffOfficialFrame(streamInfo, frame, processorBucket);
    }

    private void handOffOfficialFrame(
            PreviewStreamInfo previewStreamInfo,
            FrameEnvelope frame,
            String processorBucket) {
        byte[] packet = frame.packet();
        String handoffBucket = processorBucket;
        try {
            FrameHandoff handoff;
            synchronized (lifecycleLock) {
                if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
                PreviewInfoDataBean previewInfo = previewStreamInfo.getPreviewInfoData();
                byte[] nv12Data = previewInfo.getByteArrDst();
                updateOfficialPaletteSnapshot(previewStreamInfo);
                int frameNumStamp = d3.b.a.c(previewInfo.getByteArrYuvAppendData());
                int packetWidth = officialProcessedF2PacketWidth(packet.length);
                int packetHeight = officialProcessedF2PacketHeight(packet.length);
                if (packetWidth == 0 || packetHeight == 0) {
                    Size unknownPacketSize = officialProcessedF2PacketDimensions(packet.length);
                    packetWidth = unknownPacketSize.getWidth();
                    packetHeight = unknownPacketSize.getHeight();
                }
                Size packetSize = new Size(packetWidth, packetHeight);
                Size sourceSize = (m.getWidth() > 0 && m.getHeight() > 0) ? m : packetSize;
                Size outputSize = (t.getWidth() > 0 && t.getHeight() > 0) ? t : sourceSize;
                handoff = new FrameHandoff(
                        previewStreamInfo.getIStreamInfo(),
                        previewInfo.getByteArrSrc(),
                        nv12Data,
                        previewInfo.getByteArrHead(),
                        sourceSize,
                        outputSize,
                        frameNumStamp,
                        U,
                        V,
                        Z2.a.a.t(),
                        processorCodingType,
                        z,
                        E,
                        rendererEpoch,
                        T,
                        P);
            }
            if (handoff.streamInfo != null) {
                Z2.g.a.B0(handoff.streamInfo);
            }
            if (handoff.nv12Data.length != 0) {
                byte[] transformedNv12;
                Size transformedSize;
                if (handoff.directRendererPath) {
                    z3.c.a.w(handoff.rotation);
                    z3.c.a.x(handoff.flip);
                    z3.c.a.p(handoff.flip);
                    transformedNv12 = handoff.nv12Data;
                    transformedSize = handoff.outputSize;
                } else {
                    transformedNv12 = k3.a.a.e(
                            handoff.nv12Data,
                            handoff.sourceSize,
                            handoff.outputSize,
                            handoff.rotation,
                            handoff.flip);
                    transformedSize = handoff.rotation == 90 || handoff.rotation == 270
                            ? new Size(handoff.outputSize.getHeight(), handoff.outputSize.getWidth())
                            : handoff.outputSize;
                    if (handoff.rotation == 90 || handoff.rotation == 270) {
                        synchronized (lifecycleLock) {
                            if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
                            t = transformedSize;
                        }
                    }
                }
                if (handoff.diagnosticCallback != null
                        && isProcessingEpochCurrent(frame.processingEpoch)) {
                    recordOfficialPacket(
                            frame.processingEpoch,
                            handoff.diagnosticCallback,
                            handoff.processorCodingType,
                            handoff.src,
                            transformedNv12,
                            handoff.head,
                            packet);
                }
                if (isRendererDispatchCurrent(
                        frame.processingEpoch,
                        handoff.rendererEpoch,
                        handoff.renderer)) {
                    if (handoff.directRendererPath) {
                        handoff.renderer.j(
                                null,
                                transformedNv12,
                                transformedSize,
                                handoff.frameNumStamp,
                                null,
                                handoff.overlayBitmap);
                    } else {
                        handoff.renderer.h(
                                null,
                                transformedNv12,
                                transformedSize,
                                handoff.frameNumStamp);
                    }
                }
                if (handoff.frameNumberCallback != null
                        && isProcessingEpochCurrent(frame.processingEpoch)) {
                    handoff.frameNumberCallback.invoke(handoff.frameNumStamp);
                }
            }
            synchronized (lifecycleLock) {
                if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
                lastStreamProcessingFailure = null;
            }
        } catch (RuntimeException | LinkageError error) {
            synchronized (lifecycleLock) {
                if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
                lastStreamProcessingFailure = processingFailure("handoff", error);
                handoffBucket = processorBucket + ":" + lastStreamProcessingFailure;
            }
        } finally {
            publishOfficialFrame(previewStreamInfo, frame, handoffBucket);
        }
    }

    private void publishOfficialFrame(
            PreviewStreamInfo previewStreamInfo,
            FrameEnvelope frame,
            String processorBucket) {
        if (!isProcessingEpochCurrent(frame.processingEpoch)) return;
        byte[] packet = frame.packet();
        int packetWidth = officialProcessedF2PacketWidth(packet.length);
        int packetHeight = officialProcessedF2PacketHeight(packet.length);
        if (packetWidth == 0 || packetHeight == 0) {
            Size dimensions = officialProcessedF2PacketDimensions(packet.length);
            packetWidth = dimensions.getWidth();
            packetHeight = dimensions.getHeight();
        }
        PreviewManagerIIAppBinding.afterOfficialG(this, frame.processingEpoch, frame.userId, frame.frameNumber, frame.width, frame.height,
                frame.frameType, frame.dataType, frame.streamType, packet, packetWidth, packetHeight,
                previewStreamInfo, isOfficialOfflineMailboxFrame(packet.length), processorBucket);
    }

    public final boolean isProcessingEpochCurrent(long expectedEpoch) {
        synchronized (lifecycleLock) {
            return isProcessingEpochCurrentLocked(expectedEpoch);
        }
    }

    public final boolean isProcessingEpochCurrentSnapshot(long expectedEpoch) {
        return !streamClosed && processingEpoch == expectedEpoch;
    }

    public final long currentProcessingEpoch() {
        synchronized (lifecycleLock) {
            return processingEpoch;
        }
    }

    public final long currentRendererEpoch() {
        synchronized (lifecycleLock) {
            return rendererEpoch;
        }
    }

    public final boolean isOfficialRendererEpochCurrent(long expectedEpoch) {
        synchronized (lifecycleLock) {
            return E != null && rendererEpoch == expectedEpoch;
        }
    }

    public final boolean isOfficialRendererEpochCurrentSnapshot(long expectedEpoch) {
        return E != null && rendererEpoch == expectedEpoch;
    }

    private boolean isProcessingEpochCurrentLocked(long expectedEpoch) {
        return !streamClosed && processingEpoch == expectedEpoch;
    }

    private String processingFailure(String stage, Throwable error) {
        return stage + "_failure=" + error.getClass().getSimpleName()
                + ":" + String.valueOf(error.getMessage());
    }

    public final void onScheduledProcessingFailure(Throwable error) {
        lastStreamProcessingFailure = processingFailure("scheduler", error);
    }

    public final String getLastStreamProcessingFailure() {
        return lastStreamProcessingFailure;
    }

    public final StreamIngressDiagnostic getStreamIngressDiagnostic() {
        synchronized (lifecycleLock) {
            return streamIngressDiagnostic;
        }
    }

    public final boolean recordAppHandoff(
            long expectedEpoch,
            int userId,
            int packetSize,
            int streamType,
            long frameNumber) {
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(expectedEpoch)) return false;
            appHandoffIngressCount++;
            recordIngressLocked(
                    "app_handoff",
                    userId,
                    packetSize,
                    streamType,
                    frameNumber,
                    processorAllowedPacketSizes);
            return true;
        }
    }

    void recordNativeBoundaryFailure(long expectedEpoch, String stage, Throwable error) {
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(expectedEpoch)) return;
            lastStreamProcessingFailure = processingFailure(stage, error);
        }
    }

    /**
     * Official C(...)/Q() palette lifecycle. Viewer 2.6.0 only assigns N for
     * coding-12 F2V2/F0 frames after pseudo/ISP/AGC state is initialized.
     * Standard F2 therefore has an actual null Q() result.
     */
    private void updateOfficialPaletteSnapshot(PreviewStreamInfo previewStreamInfo) {
        if (processorCodingType() != 12 || (!t0() && !q0())) {
            N = null;
            paletteSnapshotFailure = null;
            return;
        }
        if (e == 0 || f == 0 || g == 0) return;

        PreviewInfoDataBean previewInfo = previewStreamInfo.getPreviewInfoData();
        float maxTmp = 0f;
        float minTmp = 0f;
        h3.a streamInfo = previewStreamInfo.getIStreamInfo();
        if (streamInfo instanceof h3.c) {
            com.hik.f2module.IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO upload = ((h3.c) streamInfo).a();
            maxTmp = upload.fMaxTmp;
            minTmp = upload.fMinTmp;
        } else if (streamInfo instanceof h3.b) {
            com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy.IFR_GLOBLE_OUTCOME_INFO global =
                    ((h3.b) streamInfo).a().temp_Info.GlobalInfo;
            maxTmp = d3.i.a.d(global.maxTmp, global.tempUnit);
            minTmp = d3.i.a.d(global.minTmp, global.tempUnit);
        }

        try {
            N = C(previewInfo.getByteArrYuvAppendData(), maxTmp, minTmp);
            paletteSnapshotFailure = null;
        } catch (RuntimeException error) {
            N = null;
            paletteSnapshotFailure = "official_preview_manager_Q_palette_incomplete_fail_closed: "
                    + error.getClass().getSimpleName() + ": " + error.getMessage();
        }
    }

    /** Smallest host-neutral reconstruction of official PreviewManagerII.C(...). */
    private OfficialF2PaletteSnapshot C(byte[] yuvAppendData, float maxTmp, float minTmp) {
        if (Z2.g.a.k()) {
            throw new IllegalStateException(
                    "custom_palette_enabled_but_exact_Q2_m_interpolation_is_not_host_reconstructed");
        }
        return buildStandardOfficialPaletteSnapshot(
                yuvAppendData, maxTmp, minTmp, e, f, g, h, i);
    }

    private static OfficialF2PaletteSnapshot buildStandardOfficialPaletteSnapshot(
            byte[] yuvAppendData,
            float maxTmp,
            float minTmp,
            int pseudoColor,
            int ispMode,
            int agcMode,
            float wideTempUpThreshold,
            float wideTempDownThreshold) {
        if (yuvAppendData == null || yuvAppendData.length < 38) {
            throw new IllegalArgumentException(
                    "official_palette_yuv_append_requires_38_bytes actual="
                            + (yuvAppendData == null ? 0 : yuvAppendData.length));
        }
        return OfficialF2PaletteSnapshot.present(
                1,
                0,
                null,
                pseudoColor,
                maxTmp,
                minTmp,
                ispMode,
                agcMode,
                wideTempUpThreshold,
                wideTempDownThreshold,
                littleEndianSignedShort(yuvAppendData, 30),
                littleEndianSignedShort(yuvAppendData, 32),
                littleEndianSignedShort(yuvAppendData, 26),
                littleEndianSignedShort(yuvAppendData, 28),
                littleEndianSignedShort(yuvAppendData, 22),
                littleEndianSignedShort(yuvAppendData, 24),
                littleEndianSignedShort(yuvAppendData, 34),
                littleEndianSignedShort(yuvAppendData, 36));
    }

    private static int littleEndianSignedShort(byte[] bytes, int offset) {
        return (short) ((bytes[offset] & 0xff) | ((bytes[offset + 1] & 0xff) << 8));
    }

    private void recordOfficialPacket(
            long expectedEpoch,
            Function1<DiagnoseBean, Unit> callback,
            int codingType,
            byte[] src,
            byte[] dst,
            byte[] head,
            byte[] allData) {
        if (callback == null || !isProcessingEpochCurrent(expectedEpoch)) return;
        callback.invoke(new DiagnoseBean(
                true,
                0,
                src,
                dst,
                head,
                allData,
                codingType == 12 ? "yuy2" : "nv12",
                "nv12"));
    }

    private boolean isRendererDispatchCurrent(
            long expectedProcessingEpoch,
            long expectedRendererEpoch,
            V2.f expectedRenderer) {
        synchronized (lifecycleLock) {
            return isProcessingEpochCurrentLocked(expectedProcessingEpoch)
                    && rendererEpoch == expectedRendererEpoch
                    && E == expectedRenderer
                    && expectedRenderer != null;
        }
    }

    private boolean isRendererCurrent(long expectedRendererEpoch, V2.f expectedRenderer) {
        synchronized (lifecycleLock) {
            return rendererEpoch == expectedRendererEpoch
                    && E == expectedRenderer
                    && expectedRenderer != null;
        }
    }

    private boolean isLifecycleCurrent(Lifecycle expectedLifecycle) {
        synchronized (lifecycleLock) {
            return previewGraphInitialized && a == expectedLifecycle;
        }
    }

    private boolean shouldApplyRendererShowSize() { return !u5.B.a.h0() && !Z2.g.a.b0() && hik.common.yyrj.businesscommon.b.x(hik.common.yyrj.businesscommon.b.d.a(), null, 1, null); }
    private void showViewerErrorTip(String error) { if (error != null && I != null) I.setVisibility(error.isEmpty() ? View.GONE : View.VISIBLE); }
    private boolean isOfficialOfflineMailboxFrame(int packetSize) { return processorCodingType() == 12 && (packetSize == 41160 || packetSize == 183496 || packetSize == 400584); }

    public static void g1(PreviewManagerII manager, boolean secondMenuVisible, int mask, Object unused) { manager.f1((mask & 1) != 0 ? false : secondMenuVisible); }
    public static void m0(PreviewManagerII manager, View root, SurfaceView surface, TextView error, FloatTextureView visible, SceneModeBean scene, Function1<Boolean, Unit> freeze, Function1<Boolean, Unit> overlay, Function1<Integer, Unit> frameNum, int mask, Object unused) { manager.l0(root, surface, (mask & 4) != 0 ? null : error, visible, (mask & 16) != 0 ? null : scene, (mask & 32) != 0 ? null : freeze, (mask & 64) != 0 ? null : overlay, (mask & 128) != 0 ? null : frameNum); }
    private static void h1(PreviewManagerII manager, Size showSize) { if (manager.J != null) manager.J.f(Z2.g.a.W(), false, showSize, new Size(manager.J.getWidth(), manager.J.getHeight())); if (manager.shouldApplyRendererShowSize() && manager.E != null) manager.E.i(showSize); Z2.g.a.M0(showSize); }
    public static Unit c(PreviewManagerII manager, boolean isFreezeData) { return Unit.INSTANCE; }
    public static Unit d(PreviewManagerII manager, OsdBgCallbackBean bean) { PreviewManagerIIAppBinding.onOsd(bean); return Unit.INSTANCE; }
    public static Unit f(
            PreviewManagerII manager,
            PreviewInfoDataBean info,
            long processingEpoch) {
        int stamp = d3.b.a.c(info.getByteArrYuvAppendData());
        if (manager.processorCodingTypeIs12ForEpoch(processingEpoch)) {
            z3.c.a.r(stamp);
            long lifecycleGeneration =
                    PreviewManagerIIAppBinding.currentLifecycleGeneration(manager);
            if (manager.C != null && lifecycleGeneration >= 0L) {
                manager.C.execute(
                        new K2.i(
                                manager,
                                info,
                                stamp,
                                processingEpoch,
                                lifecycleGeneration));
            }
        }
        return Unit.INSTANCE;
    }
    public static void e(
            PreviewManagerII manager,
            PreviewInfoDataBean info,
            int stamp,
            long processingEpoch,
            long lifecycleGeneration) {
        PreviewManagerIIAppBinding.onOfflineCallback(
                manager,
                info,
                stamp,
                processingEpoch,
                lifecycleGeneration);
    }
    public static void g(PreviewManagerII manager) { manager.c1(); }

    private void c1() {
        v0++; if (v0 >= 999) v0 = 0;
        FrameEnvelope frame;
        synchronized (lifecycleLock) {
            if (streamClosed) return;
            if (offlineFrameEnvelope != null) {
                frame = offlineFrameEnvelope;
                offlineFrameEnvelope = null;
                r0 = new byte[0];
            }
            else {
                if (normalFrameEnvelope == null) return;
                byte[] packet = normalFrameEnvelope.packet();
                int hash = Arrays.hashCode(packet);
                if (hash == t0) { u0++; if (u0 % 100 == 0) System.out.println("PreviewManager: 超过2秒（100次）没有更新。"); return; }
                t0 = hash;
                u0 = 0;
                frame = normalFrameEnvelope;
            }
        }
        G(frame);
    }

    private void clearFrameMailboxes() {
        offlineFrameEnvelope = null;
        normalFrameEnvelope = null;
        r0 = new byte[0];
        s0 = new byte[0];
    }

    long h0() { return firstCallbackAtMs; }
    int M() { return 0; }
    void P0(long value) { firstCallbackAtMs = value; }
    Function0<Unit> c0() { return a0; }
    BiConsumer<Integer, Long> invalidPacketSizeTimeoutCallback() { return invalidPacketSizeTimeoutCallback; }
    static CallbackEntry beginCallback(PreviewManagerII manager) {
        return beginCallback(manager, manager.processingEpoch, manager.C0, -1, null);
    }
    static CallbackEntry beginCallback(
            PreviewManagerII manager,
            long callbackEpoch,
            FStreamCallBack callbackIdentity,
            int userId,
            USB_FRAME_INFO frameInfo) {
        synchronized (manager.lifecycleLock) {
            if (callbackEpoch != manager.processingEpoch || callbackIdentity != manager.C0) {
                return null;
            }
            if (manager.streamClosed) {
                manager.streamClosedIngressCount++;
                manager.recordIngressLocked(
                        "stream_closed",
                        userId,
                        frameInfo == null ? -1 : frameInfo.dwBufSize,
                        frameInfo == null ? -1 : frameInfo.dwStreamType,
                        frameInfo == null ? -1L : frameInfo.nFrameNum,
                        manager.processorAllowedPacketSizes);
                return null;
            }
            long now = System.currentTimeMillis();
            manager.lastCallbackAtMs = now;
            manager.frameCounter += 1L;
            if (manager.firstCallbackAtMs == 0L) manager.firstCallbackAtMs = now;
            return new CallbackEntry(
                    manager.processingEpoch,
                    manager.frameCounter,
                    manager.processorCodingType,
                    manager.processorAllowedPacketSizes);
        }
    }
    static boolean u(PreviewManagerII manager, FrameEnvelope value) {
        synchronized (manager.lifecycleLock) {
            if (!manager.isProcessingEpochCurrentLocked(value.processingEpoch)) return false;
            manager.normalFrameEnvelope = value;
            manager.s0 = value.packet();
            manager.mailboxAcceptedIngressCount++;
            manager.recordIngressLocked(
                    "mailbox_accepted",
                    value.userId,
                    value.packet.length,
                    value.streamType,
                    value.frameNumber,
                    manager.processorAllowedPacketSizes);
            return true;
        }
    }
    static boolean v(PreviewManagerII manager, FrameEnvelope value) {
        synchronized (manager.lifecycleLock) {
            if (!manager.isProcessingEpochCurrentLocked(value.processingEpoch)) return false;
            manager.offlineFrameEnvelope = value;
            manager.r0 = value.packet();
            manager.mailboxAcceptedIngressCount++;
            manager.recordIngressLocked(
                    "mailbox_accepted",
                    value.userId,
                    value.packet.length,
                    value.streamType,
                    value.frameNumber,
                    manager.processorAllowedPacketSizes);
            return true;
        }
    }
    static FrameEnvelope frameEnvelope(
            int userId,
            USB_FRAME_INFO info,
            long fallbackFrameNumber,
            long processingEpoch,
            byte[] packet) {
        return new FrameEnvelope(
                userId,
                info.dwWidth,
                info.dwHeight,
                info.dwFrameType,
                info.dwDataType,
                info.dwStreamType,
                info.nFrameNum > 0 ? info.nFrameNum : fallbackFrameNumber,
                processingEpoch,
                packet);
    }
    static void rememberFrame(PreviewManagerII manager, int userId, USB_FRAME_INFO info) { manager.lastUserId = userId; manager.lastWidth = info.dwWidth; manager.lastHeight = info.dwHeight; manager.lastFrameType = info.dwFrameType; manager.lastDataType = info.dwDataType; manager.lastStreamType = info.dwStreamType; manager.lastFrameNumber = info.nFrameNum > 0 ? info.nFrameNum : manager.frameCounter; }

    static final class FrameEnvelope {
        final int userId;
        final int width;
        final int height;
        final int frameType;
        final int dataType;
        final int streamType;
        final long frameNumber;
        final long processingEpoch;
        private final byte[] packet;

        FrameEnvelope(
                int userId,
                int width,
                int height,
                int frameType,
                int dataType,
                int streamType,
                long frameNumber,
                long processingEpoch,
                byte[] packet) {
            this.userId = userId;
            this.width = width;
            this.height = height;
            this.frameType = frameType;
            this.dataType = dataType;
            this.streamType = streamType;
            this.frameNumber = frameNumber;
            this.processingEpoch = processingEpoch;
            this.packet = Arrays.copyOf(packet, packet.length);
        }

        byte[] packet() {
            return Arrays.copyOf(packet, packet.length);
        }

    }

    static final class CallbackEntry {
        final long processingEpoch;
        final long frameNumber;
        final int processorCodingType;
        final Set<Integer> allowedPacketSizes;

        CallbackEntry(
                long processingEpoch,
                long frameNumber,
                int processorCodingType,
                Set<Integer> allowedPacketSizes) {
            this.processingEpoch = processingEpoch;
            this.frameNumber = frameNumber;
            this.processorCodingType = processorCodingType;
            this.allowedPacketSizes = Collections.unmodifiableSet(new HashSet<>(allowedPacketSizes));
        }

        boolean acceptsPacketSize(int packetSize) { return allowedPacketSizes.contains(packetSize); }
        boolean isCoding12() { return processorCodingType == 12; }
    }

    void recordPacketSizeNotAllowed(
            long expectedEpoch,
            int userId,
            int packetSize,
            int streamType,
            long frameNumber,
            Set<Integer> allowedPacketSizes) {
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(expectedEpoch)) return;
            packetSizeNotAllowedIngressCount++;
            recordIngressLocked(
                    "packet_size_not_allowed",
                    userId,
                    packetSize,
                    streamType,
                    frameNumber,
                    allowedPacketSizes);
        }
    }

    InvalidPacketCallbacks consumeInvalidPacketCallbacks(
            long expectedEpoch,
            FStreamCallBack callbackIdentity) {
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(expectedEpoch)
                    || callbackIdentity != C0) return null;
            long startMs = firstCallbackAtMs;
            long now = System.currentTimeMillis();
            if ((now - startMs) <= 40000L || M() != 0) return null;
            firstCallbackAtMs = 0L;
            return new InvalidPacketCallbacks(
                    expectedEpoch,
                    now - startMs,
                    callbackIdentity,
                    invalidPacketSizeTimeoutCallback,
                    a0);
        }
    }

    boolean isCallbackCurrent(long expectedEpoch, FStreamCallBack callbackIdentity) {
        synchronized (lifecycleLock) {
            return isProcessingEpochCurrentLocked(expectedEpoch)
                    && callbackIdentity == C0;
        }
    }

    static final class InvalidPacketCallbacks {
        final long processingEpoch;
        final long elapsedMs;
        final FStreamCallBack callbackIdentity;
        final BiConsumer<Integer, Long> diagnosticCallback;
        final Function0<Unit> legacyCallback;

        InvalidPacketCallbacks(
                long processingEpoch,
                long elapsedMs,
                FStreamCallBack callbackIdentity,
                BiConsumer<Integer, Long> diagnosticCallback,
                Function0<Unit> legacyCallback) {
            this.processingEpoch = processingEpoch;
            this.elapsedMs = elapsedMs;
            this.callbackIdentity = callbackIdentity;
            this.diagnosticCallback = diagnosticCallback;
            this.legacyCallback = legacyCallback;
        }
    }

    private static final class FrameHandoff {
        final h3.a streamInfo;
        final byte[] src;
        final byte[] nv12Data;
        final byte[] head;
        final Size sourceSize;
        final Size outputSize;
        final int frameNumStamp;
        final int rotation;
        final boolean flip;
        final boolean directRendererPath;
        final int processorCodingType;
        final Function1<DiagnoseBean, Unit> diagnosticCallback;
        final V2.f renderer;
        final long rendererEpoch;
        final Function1<Integer, Unit> frameNumberCallback;
        final Bitmap overlayBitmap;

        FrameHandoff(
                h3.a streamInfo,
                byte[] src,
                byte[] nv12Data,
                byte[] head,
                Size sourceSize,
                Size outputSize,
                int frameNumStamp,
                int rotation,
                boolean flip,
                boolean directRendererPath,
                int processorCodingType,
                Function1<DiagnoseBean, Unit> diagnosticCallback,
                V2.f renderer,
                long rendererEpoch,
                Function1<Integer, Unit> frameNumberCallback,
                Bitmap overlayBitmap) {
            this.streamInfo = streamInfo;
            this.src = src;
            this.nv12Data = nv12Data;
            this.head = head;
            this.sourceSize = sourceSize;
            this.outputSize = outputSize;
            this.frameNumStamp = frameNumStamp;
            this.rotation = rotation;
            this.flip = flip;
            this.directRendererPath = directRendererPath;
            this.processorCodingType = processorCodingType;
            this.diagnosticCallback = diagnosticCallback;
            this.renderer = renderer;
            this.rendererEpoch = rendererEpoch;
            this.frameNumberCallback = frameNumberCallback;
            this.overlayBitmap = overlayBitmap;
        }
    }

    private void recordProcessorAccepted(FrameEnvelope frame) {
        synchronized (lifecycleLock) {
            if (!isProcessingEpochCurrentLocked(frame.processingEpoch)) return;
            processorAcceptedIngressCount++;
            recordIngressLocked(
                    "processor_accepted",
                    frame.userId,
                    frame.packet.length,
                    frame.streamType,
                    frame.frameNumber,
                    processorAllowedPacketSizes);
        }
    }

    private void recordIngressLocked(
            String reason,
            int userId,
            int packetSize,
            int streamType,
            long frameNumber,
            Set<Integer> allowedPacketSizes) {
        streamIngressDiagnostic = new StreamIngressDiagnostic(
                reason,
                userId,
                packetSize,
                streamType,
                frameNumber,
                allowedPacketSizes,
                streamClosedIngressCount,
                packetSizeNotAllowedIngressCount,
                mailboxAcceptedIngressCount,
                processorAcceptedIngressCount,
                appHandoffIngressCount);
    }

    private void resetIngressDiagnosticsLocked() {
        streamClosedIngressCount = 0L;
        packetSizeNotAllowedIngressCount = 0L;
        mailboxAcceptedIngressCount = 0L;
        processorAcceptedIngressCount = 0L;
        appHandoffIngressCount = 0L;
        streamIngressDiagnostic = StreamIngressDiagnostic.notObserved();
    }

    public static final class StreamIngressDiagnostic {
        private final String reason;
        private final int userId;
        private final int packetSize;
        private final int streamType;
        private final long frameNumber;
        private final Set<Integer> allowedPacketSizes;
        private final long streamClosedCount;
        private final long packetSizeNotAllowedCount;
        private final long mailboxAcceptedCount;
        private final long processorAcceptedCount;
        private final long appHandoffCount;

        private StreamIngressDiagnostic(
                String reason,
                int userId,
                int packetSize,
                int streamType,
                long frameNumber,
                Set<Integer> allowedPacketSizes,
                long streamClosedCount,
                long packetSizeNotAllowedCount,
                long mailboxAcceptedCount,
                long processorAcceptedCount,
                long appHandoffCount) {
            this.reason = reason;
            this.userId = userId;
            this.packetSize = packetSize;
            this.streamType = streamType;
            this.frameNumber = frameNumber;
            this.allowedPacketSizes = Collections.unmodifiableSet(
                    new TreeSet<>(allowedPacketSizes == null
                            ? Collections.emptySet()
                            : allowedPacketSizes));
            this.streamClosedCount = streamClosedCount;
            this.packetSizeNotAllowedCount = packetSizeNotAllowedCount;
            this.mailboxAcceptedCount = mailboxAcceptedCount;
            this.processorAcceptedCount = processorAcceptedCount;
            this.appHandoffCount = appHandoffCount;
        }

        static StreamIngressDiagnostic notObserved() {
            return new StreamIngressDiagnostic(
                    "not_observed",
                    -1,
                    -1,
                    -1,
                    -1L,
                    Collections.emptySet(),
                    0L,
                    0L,
                    0L,
                    0L,
                    0L);
        }

        public String getReason() { return reason; }
        public int getUserId() { return userId; }
        public int getPacketSize() { return packetSize; }
        public int getStreamType() { return streamType; }
        public long getFrameNumber() { return frameNumber; }
        public Set<Integer> getAllowedPacketSizes() { return allowedPacketSizes; }
        public long getStreamClosedCount() { return streamClosedCount; }
        public long getPacketSizeNotAllowedCount() { return packetSizeNotAllowedCount; }
        public long getMailboxAcceptedCount() { return mailboxAcceptedCount; }
        public long getProcessorAcceptedCount() { return processorAcceptedCount; }
        public long getAppHandoffCount() { return appHandoffCount; }
    }

    static Size officialProcessedF2PacketDimensions(int packetSize) { switch (packetSize) { case 41160: case 61384: return new Size(96, 96); case 183496: case 203720: case 101320: return new Size(192, 256); case 400584: case 193480: return new Size(288, 384); default: return new Size(0, 0); } }
    private static int officialProcessedF2PacketWidth(int packetSize) { switch (packetSize) { case 41160: case 61384: return 96; case 183496: case 203720: case 101320: return 192; case 400584: case 193480: return 288; default: return 0; } }
    private static int officialProcessedF2PacketHeight(int packetSize) { switch (packetSize) { case 41160: case 61384: return 96; case 183496: case 203720: case 101320: return 256; case 400584: case 193480: return 384; default: return 0; } }
    void onOfficialSurfaceCreated() { if (E != null) E.start(); }
    void onOfficialSurfaceDestroyed() { if (E != null) E.stop(); }
    void onOfficialLifecycleCreate() { if (c) { q = 1f; r = 0; s = 0; } else { q = l2.k.c("FUSE_VIS_SCALE", 1f); r = l2.k.e("FUSE_VIS_TRANSLATE_X", 0); s = l2.k.e("FUSE_VIS_TRANSLATE_Y", 0); } }
    void onOfficialLifecycleDestroy(LifecycleOwner owner) { if (owner instanceof Fragment) ((Fragment) owner).getLifecycle().removeObserver(B); u0(); }
    void onOfficialLifecyclePause() { if (Y != null) Y.invoke(); }
    void onOfficialLifecycleStart() { if (H != null) { H.getHolder().addCallback(A); H.setVisibility(View.VISIBLE); } m0 = false; }
    void onOfficialLifecycleStop() { if (H != null) { H.setVisibility(View.GONE); H.getHolder().removeCallback(A); } l = null; m0 = true; }
}
