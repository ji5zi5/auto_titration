package com.hik.viewer.manager;

import com.hcusbsdk.Interface.FStreamCallBack;
import com.hcusbsdk.Interface.USB_FRAME_INFO;
import java.util.Arrays;

public final class PreviewManagerII$d implements FStreamCallBack {
    private long a;
    private final long c;
    final PreviewManagerII b;
    PreviewManagerII$d(PreviewManagerII manager, long processingEpoch) {
        this.b = manager;
        this.c = processingEpoch;
    }
    @Override public synchronized void invoke(int userId, USB_FRAME_INFO frameInfo) {
        if (frameInfo == null) { System.out.println("PreviewManager: 码流预览回调为空, pFrameInfo = null"); return; }
        int size = frameInfo.dwBufSize;
        if (frameInfo.pBuf == null || size < 0 || size > frameInfo.pBuf.length) {
            System.out.println(
                    "PreviewManager: rejected frame copy declaredBytes="
                            + size
                            + " availableBytes="
                            + (frameInfo.pBuf == null ? "null" : frameInfo.pBuf.length));
            return;
        }
        PreviewManagerII.CallbackEntry callbackEntry =
                PreviewManagerII.beginCallback(b, c, this, userId, frameInfo);
        if (callbackEntry == null) return;
        a++;
        byte[] copied = Arrays.copyOf(frameInfo.pBuf, size);
        Z2.g.a.A0(size);
        PreviewManagerII.FrameEnvelope envelope =
                PreviewManagerII.frameEnvelope(
                        userId,
                        frameInfo,
                        callbackEntry.frameNumber,
                        callbackEntry.processingEpoch,
                        copied);
        if (callbackEntry.acceptsPacketSize(size)) {
            boolean off = (size == 183496 || size == 400584 || size == 41160);
            if (callbackEntry.isCoding12() && off) PreviewManagerII.v(b, envelope); else PreviewManagerII.u(b, envelope);
        } else {
            b.recordPacketSizeNotAllowed(
                    callbackEntry.processingEpoch,
                    userId,
                    size,
                    frameInfo.dwStreamType,
                    envelope.frameNumber,
                    callbackEntry.allowedPacketSizes);
            PreviewManagerII.InvalidPacketCallbacks callbacks =
                    b.consumeInvalidPacketCallbacks(
                            callbackEntry.processingEpoch,
                            this);
            if (callbacks == null) return;
            if (callbacks.diagnosticCallback != null
                    && b.isCallbackCurrent(
                            callbacks.processingEpoch,
                            callbacks.callbackIdentity)) {
                try {
                    callbacks.diagnosticCallback.accept(size, callbacks.elapsedMs);
                } catch (RuntimeException | LinkageError error) {
                    b.recordNativeBoundaryFailure(
                            callbacks.processingEpoch,
                            "invalid_packet_callback",
                            error);
                }
            }
            if (callbacks.legacyCallback != null
                    && b.isCallbackCurrent(
                            callbacks.processingEpoch,
                            callbacks.callbackIdentity)) {
                try {
                    callbacks.legacyCallback.invoke();
                } catch (RuntimeException | LinkageError error) {
                    b.recordNativeBoundaryFailure(
                            callbacks.processingEpoch,
                            "invalid_packet_callback",
                            error);
                }
            }
        }
    }
}
