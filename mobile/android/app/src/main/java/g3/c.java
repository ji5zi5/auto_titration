package g3;

import com.hik.f2module.IFR_INFO;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.Arrays;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

public final class c extends g3.a implements i3.a {
    public static final c.a g = new c.a(null);
    private final i3.a f;
    public c(i3.a iStreamInfoDeal) { Intrinsics.checkNotNullParameter(iStreamInfoDeal, "iStreamInfoDeal"); this.f = iStreamInfoDeal; }
    @Override public void a(boolean isFreezeData, Function1 freezeCallback, Function1 thawCallback) { this.f.a(isFreezeData, freezeCallback, thawCallback); }
    @Override public void b(h3.a streamInfo, PreviewInfoDataBean previewInfoData, Function1 metadataCallback, Function5 overlayCallback) { Intrinsics.checkNotNullParameter(previewInfoData, "previewInfoData"); this.f.b(streamInfo, previewInfoData, metadataCallback, overlayCallback); }
    @Override public void c(h3.a streamInfo, byte[] rawAppendData, Function1 callback) { this.f.c(streamInfo, rawAppendData, callback); }
    @Override public PreviewStreamInfo d(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        PreviewInfoDataBean previewInfo = l(frameInfoData);
        IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV upload = new IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV();
        k3.b.d(k3.b.a, upload, previewInfo.getByteArrHead(), null, 4, null);
        PreviewStreamInfo result = new PreviewStreamInfo(previewInfo, new h3.c(upload.ifrRealtimeTmOutcomeUploadInfo));
        boolean frozen = upload.dwIsFreezedata != 0;
        a(frozen, e(), f()); b(result.getIStreamInfo(), previewInfo, i(), h()); c(result.getIStreamInfo(), previewInfo.getByteArrRawAppendData(), g());
        return result;
    }
    protected PreviewInfoDataBean l(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        int rawSize = 0, rawAppendStartExtra = 0, rawAppendSize = 0, yuvSize = 0;
        if (frameInfoData.length == 206392) { rawSize = 98304; rawAppendStartExtra = 98304; rawAppendSize = 1536; yuvSize = 98304; }
        else if (frameInfoData.length == 453688) { rawSize = 221184; rawAppendStartExtra = 221184; rawAppendSize = 2304; yuvSize = 221184; }
        byte[] head = Arrays.copyOfRange(frameInfoData, 0, 6712);
        int rawEnd = 6712 + rawSize;
        byte[] rawData = Arrays.copyOfRange(frameInfoData, 6712, rawEnd + (rawAppendSize / 2));
        int rawAppendStart = 6712 + rawAppendStartExtra - (rawAppendSize / 2);
        int yuvStart = rawEnd + rawAppendSize;
        byte[] rawAppend = Arrays.copyOfRange(frameInfoData, rawAppendStart, yuvStart);
        byte[] yuy2 = Arrays.copyOfRange(frameInfoData, yuvStart, yuvStart + yuvSize);
        return new PreviewInfoDataBean(yuy2, k3.a.a.i(yuy2, Z2.a.a.p().c()), head, rawData, rawAppend, new byte[0], new byte[0], new byte[0], new byte[0]);
    }
    public static final class a { private a() {} public a(DefaultConstructorMarker marker) {} }
}
