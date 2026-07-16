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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import kotlin.Unit;
import kotlin.jvm.functions.Function0;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;

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
    private boolean j;
    private boolean k;
    private boolean streamClosed;
    private long frameCounter;
    private long invalidPacketStartMs;
    private long lastCallbackAtMs;
    private long firstCallbackAtMs;
    private ScheduledExecutorService x0;
    private ExecutorService C = Executors.newSingleThreadExecutor();

    private V2.f E;
    private g3.a D;
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
    private Function0<Unit> b0;
    private Function0<Unit> c0;
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
        this.C0 = new PreviewManagerII$d(this);
    }

    public final FStreamCallBack R() { return C0; }
    public final IStreamCallback U() { return B0; }
    public final byte[] S() { return A0; }
    public final Size T() { return m; }

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
        this.G = viewerRootView;
        this.H = viewerSurfaceView;
        this.J = visibleLightView;
        this.I = viewerErrorText;
        this.X = freezeCallback;
        this.O = sceneModeBean;
        this.Q = overlayAvailabilityCallback;
        this.T = frameNumberCallback;
        if (s0()) {
            m = Z2.a.a.p().c();
            n = Z2.a.a.p().c();
            t = new Size(m.getWidth(), m.getHeight());
            if (O != null && (t0() || q0())) { n0(n); p0(); }
            b1();
            D = g3.b.a.a(Z2.a.a.p().k(), t0());
        } else if (r0()) {
            m = new Size(120, 160);
            n = new Size(120, 160);
            t = new Size(120, 160);
            com.hik.f1module.F1UsbModuleHelper.INSTANCE.USB_SetYuvSize(t);
        }
        S = u5.B.a.L() == 1;
        U = Z2.g.a.w(Z2.g.a.U().getSerialNumber());
        g1(this, false, 1, null);
        Size showSize = Z2.g.a.E();
        bindOfficialRenderer(viewerSurfaceView, l2.k.a("useM4", true));
        if (E != null) {
            if (shouldApplyRendererShowSize()) E.i(showSize);
            E.b(new PreviewManagerII$f(this));
        }
        if (a != null) a.addObserver(B);
    }

    private V2.f bindOfficialRenderer(SurfaceView viewerSurfaceView, boolean useM4) {
        X2.b factory = useM4 ? new X2.c() : new X2.a();
        V2.f selected;
        if (!s0()) selected = factory.a(viewerSurfaceView);
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
        x0.scheduleAtFixedRate(new K2.e(this), 0L, 20L, TimeUnit.MILLISECONDS);
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

    public final byte[] i1(Size picSize) { synchronized (lifecycleLock) { return E != null ? E.e(picSize) : null; } }
    public final com.hik.library.player.d W(Size picSize) { synchronized (lifecycleLock) { return E != null ? E.f(picSize) : null; } }
    public final void D0(Function1<DiagnoseBean, Unit> callback) { z = callback; }
    public final void G0(Function0<Unit> callback) { Z = callback; }
    public final void J0(Function5<Object, Object, Object, Object, Object, Unit> callback) { h0 = callback; }
    public final void closePreviewCallback() { synchronized (lifecycleLock) { streamClosed = true; u0(); r0 = new byte[0]; s0 = new byte[0];  } }
    public final void openPreviewCallback() { synchronized (lifecycleLock) { streamClosed = false; if (C == null || C.isShutdown()) C = Executors.newSingleThreadExecutor(); if (C0 == null) C0 = new PreviewManagerII$d(this); b1(); } }
    public final void u0() {
        if (E != null) E.c();
        if (E != null) E.release();
        E = null;
        B0 = null; C0 = null; X = null; Y = null; Z = null; a0 = null; b0 = null; c0 = null; d0 = null; e0 = null; f0 = null; h0 = null;
        if (D != null) D.k();
        D = null;
        if (C != null) C.shutdownNow();
        C = null;
        e1(); q0 = true; m0 = true; G = null; H = null; I = null; J = null;
        if (K != null) K.removeCallbacksAndMessages(null);
    }

    void G(byte[] packet) {
        PreviewStreamInfo streamInfo = new PreviewStreamInfo(new PreviewInfoDataBean(), null);
        g3.a processor = D;
        if (processor == null) { processor = g3.b.a.a(Z2.a.a.p().k(), t0()); D = processor; }
        processor.j(X, new K2.f(this), null, h0, new K2.g(this));
        if (processor instanceof g3.d) ((g3.d) processor).o(new K2.h(this));
        streamInfo = processor.d(packet);
        handOffOfficialFrame(streamInfo, packet);
    }

    private void handOffOfficialFrame(PreviewStreamInfo previewStreamInfo, byte[] packet) {
        PreviewInfoDataBean previewInfo = previewStreamInfo.getPreviewInfoData();
        byte[] nv12Data = previewInfo.getByteArrDst();
        if (previewStreamInfo.getIStreamInfo() != null) Z2.g.a.B0(previewStreamInfo.getIStreamInfo());
        int frameNumStamp = d3.b.a.c(previewInfo.getByteArrYuvAppendData());
        Size packetSize = officialProcessedF2PacketDimensions(packet.length);
        Size sourceSize = (m.getWidth() > 0 && m.getHeight() > 0) ? m : packetSize;
        Size outputSize = (t.getWidth() > 0 && t.getHeight() > 0) ? t : sourceSize;
        if (nv12Data.length != 0 && sourceSize.getWidth() > 0 && sourceSize.getHeight() > 0) {
            byte[] transformedNv12;
            Size transformedSize;
            if (Z2.a.a.t()) {
                z3.c.a.w(U); z3.c.a.x(V); z3.c.a.p(V);
                transformedNv12 = nv12Data; transformedSize = outputSize;
            } else {
                transformedNv12 = k3.a.a.e(nv12Data, sourceSize, outputSize, U, V);
                if (U == 90 || U == 270) t = new Size(outputSize.getHeight(), outputSize.getWidth());
                transformedSize = t;
            }
            recordOfficialPacket(previewInfo.getByteArrSrc(), transformedNv12, previewInfo.getByteArrHead(), packet);
            V2.f renderer = E;
            if (Z2.a.a.t()) rendererOrNullJ(renderer, transformedNv12, transformedSize, frameNumStamp);
            else if (renderer != null) renderer.h(null, transformedNv12, transformedSize, frameNumStamp);
            if (T != null) T.invoke(frameNumStamp);
        }
        PreviewManagerIIAppBinding.afterOfficialG(this, lastUserId, lastFrameNumber, lastWidth, lastHeight,
                lastFrameType, lastDataType, lastStreamType, packet, packetSize.getWidth(), packetSize.getHeight(),
                previewStreamInfo, isOfficialOfflineMailboxFrame(packet.length), D != null ? D.getClass().getName() : "");
    }
    private void rendererOrNullJ(V2.f renderer, byte[] data, Size size, int stamp) { if (renderer != null) renderer.j(null, data, size, stamp, null, P); }

    private void recordOfficialPacket(byte[] src, byte[] dst, byte[] head, byte[] allData) {
        if (z == null) return;
        z.invoke(new DiagnoseBean(true, 0, src, dst, head, allData, Z2.a.a.p().k() == 12 ? "yuy2" : "nv12", "nv12"));
    }

    private boolean shouldApplyRendererShowSize() { return !u5.B.a.h0() && !Z2.g.a.b0() && hik.common.yyrj.businesscommon.b.x(hik.common.yyrj.businesscommon.b.d.a(), null, 1, null); }
    private void showViewerErrorTip(String error) { if (error != null && I != null) I.setVisibility(error.isEmpty() ? View.GONE : View.VISIBLE); }
    private boolean isOfficialOfflineMailboxFrame(int packetSize) { return Z2.a.a.p().k() == 12 && (packetSize == 41160 || packetSize == 183496 || packetSize == 400584); }

    public static void g1(PreviewManagerII manager, boolean secondMenuVisible, int mask, Object unused) { manager.f1((mask & 1) != 0 ? false : secondMenuVisible); }
    public static void m0(PreviewManagerII manager, View root, SurfaceView surface, TextView error, FloatTextureView visible, SceneModeBean scene, Function1<Boolean, Unit> freeze, Function1<Boolean, Unit> overlay, Function1<Integer, Unit> frameNum, int mask, Object unused) { manager.l0(root, surface, (mask & 4) != 0 ? null : error, visible, (mask & 16) != 0 ? null : scene, (mask & 32) != 0 ? null : freeze, (mask & 64) != 0 ? null : overlay, (mask & 128) != 0 ? null : frameNum); }
    private static void h1(PreviewManagerII manager, Size showSize) { if (manager.J != null) manager.J.f(Z2.g.a.W(), false, showSize, new Size(manager.J.getWidth(), manager.J.getHeight())); if (manager.shouldApplyRendererShowSize() && manager.E != null) manager.E.i(showSize); Z2.g.a.M0(showSize); }
    public static Unit c(PreviewManagerII manager, boolean isFreezeData) { return Unit.INSTANCE; }
    public static Unit d(PreviewManagerII manager, OsdBgCallbackBean bean) { PreviewManagerIIAppBinding.onOsd(bean); return Unit.INSTANCE; }
    public static Unit f(PreviewManagerII manager, PreviewInfoDataBean info) { int stamp = d3.b.a.c(info.getByteArrYuvAppendData()); if (Z2.a.a.p().k() == 12) { z3.c.a.r(stamp); if (manager.C != null) manager.C.execute(new K2.i(manager, info, stamp)); } return Unit.INSTANCE; }
    public static void e(PreviewManagerII manager, PreviewInfoDataBean info, int stamp) { PreviewManagerIIAppBinding.onOfflineCallback(info, stamp); }
    public static void g(PreviewManagerII manager) { manager.c1(); }

    private void c1() {
        v0++; if (v0 >= 999) v0 = 0;
        byte[] packet;
        synchronized (lifecycleLock) {
            if (streamClosed) return;
            if (r0.length != 0) { packet = r0; r0 = new byte[0]; }
            else {
                if (s0.length == 0) return;
                int hash = Arrays.hashCode(s0);
                if (hash == t0) { u0++; if (u0 % 100 == 0) System.out.println("PreviewManager: 超过2秒（100次）没有更新。"); return; }
                t0 = hash; u0 = 0; packet = s0;
            }
        }
        G(packet);
    }

    long h0() { return firstCallbackAtMs; }
    int M() { return 0; }
    void P0(long value) { firstCallbackAtMs = value; }
    Function0<Unit> c0() { return c0; }
    static boolean n(PreviewManagerII manager) { return manager.streamClosed; }
    static long i(PreviewManagerII manager) { return manager.frameCounter; }
    static void t(PreviewManagerII manager, long value) { manager.frameCounter = value; }
    static void x(PreviewManagerII manager, long value) { manager.lastCallbackAtMs = value; }
    static void u(PreviewManagerII manager, byte[] value) { manager.s0 = value; }
    static void v(PreviewManagerII manager, byte[] value) { manager.r0 = value; }
    static void rememberFrame(PreviewManagerII manager, int userId, USB_FRAME_INFO info) { manager.lastUserId = userId; manager.lastWidth = info.dwWidth; manager.lastHeight = info.dwHeight; manager.lastFrameType = info.dwFrameType; manager.lastDataType = info.dwDataType; manager.lastStreamType = info.dwStreamType; manager.lastFrameNumber = info.nFrameNum > 0 ? info.nFrameNum : manager.frameCounter; }

    static Size officialProcessedF2PacketDimensions(int packetSize) { switch (packetSize) { case 41160: case 61384: return new Size(96, 96); case 183496: case 203720: case 101320: return new Size(192, 256); case 400584: case 193480: return new Size(288, 384); default: return new Size(0, 0); } }
    void onOfficialSurfaceCreated() { if (E != null) E.start(); }
    void onOfficialSurfaceDestroyed() { if (E != null) E.stop(); }
    void onOfficialLifecycleCreate() { if (c) { q = 1f; r = 0; s = 0; } else { q = l2.k.c("FUSE_VIS_SCALE", 1f); r = l2.k.e("FUSE_VIS_TRANSLATE_X", 0); s = l2.k.e("FUSE_VIS_TRANSLATE_Y", 0); } }
    void onOfficialLifecycleDestroy(LifecycleOwner owner) { if (owner instanceof Fragment) ((Fragment) owner).getLifecycle().removeObserver(B); u0(); }
    void onOfficialLifecyclePause() { if (Y != null) Y.invoke(); }
    void onOfficialLifecycleStart() { if (H != null) { H.getHolder().addCallback(A); H.setVisibility(View.VISIBLE); } m0 = false; }
    void onOfficialLifecycleStop() { if (H != null) { H.setVisibility(View.GONE); H.getHolder().removeCallback(A); } l = null; m0 = true; }
}
