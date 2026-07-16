package g3;

import com.hik.f2module.IFR_INFO;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.Arrays;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

public final class f extends g3.a implements i3.a {
    public static final f.a g = new f.a(null);
    private final i3.a f;
    public f(i3.a iStreamInfoDeal) { Intrinsics.checkNotNullParameter(iStreamInfoDeal, "iStreamInfoDeal"); this.f = iStreamInfoDeal; }
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
        byte[] head = Arrays.copyOfRange(frameInfoData, 0, 4640);
        byte[] first = Arrays.copyOfRange(frameInfoData, 4640, Math.min(102944, frameInfoData.length));
        byte[] second = frameInfoData.length >= 102944 ? Arrays.copyOfRange(frameInfoData, 102944, frameInfoData.length) : new byte[0];
        byte[] yuy2 = frameInfoData.length == 102944 ? first : frameInfoData.length == 201248 ? second : new byte[0];
        return new PreviewInfoDataBean(yuy2, k3.a.a.i(yuy2, Z2.a.a.p().c()), head, new byte[0], new byte[0], new byte[0], new byte[0], new byte[0], new byte[0]);
    }
    public static final class a { private a() {} public a(DefaultConstructorMarker marker) {} }
}
