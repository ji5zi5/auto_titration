package com.hik.viewer.manager;

import com.hcusbsdk.Interface.FStreamCallBack;
import com.hcusbsdk.Interface.USB_FRAME_INFO;
import java.util.Arrays;
import kotlin.Unit;
import kotlin.jvm.functions.Function0;

public final class PreviewManagerII$d implements FStreamCallBack {
    private long a;
    final PreviewManagerII b;
    PreviewManagerII$d(PreviewManagerII manager) { this.b = manager; }
    @Override public synchronized void fStreamCallback(int userId, USB_FRAME_INFO frameInfo) {
        if (PreviewManagerII.n(b)) return;
        if (frameInfo == null) { System.out.println("PreviewManager: 码流预览回调为空, pFrameInfo = null"); return; }
        PreviewManagerII.x(b, System.currentTimeMillis());
        PreviewManagerII.t(b, PreviewManagerII.i(b) + 1L);
        if (b.h0() == 0L) b.P0(System.currentTimeMillis());
        a++;
        int size = frameInfo.dwBufSize;
        byte[] copied = Arrays.copyOf(frameInfo.pBuf, size);
        Z2.g.a.A0(size);
        PreviewManagerII.rememberFrame(b, userId, frameInfo);
        if (Z2.a.a.p().e().contains(size)) {
            boolean off = (size == 183496 || size == 400584 || size == 183496 || size == 41160);
            if (Z2.a.a.p().k() == 12 && off) PreviewManagerII.v(b, copied); else PreviewManagerII.u(b, copied);
        } else if ((System.currentTimeMillis() - b.h0()) > 40000L && b.M() == 0) {
            Function0<Unit> callback = b.c0();
            if (callback != null) callback.invoke();
            b.P0(0L);
        }
    }
}
