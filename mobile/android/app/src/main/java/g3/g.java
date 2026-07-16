package g3;

import android.util.Size;
import com.hik.f2module.IFR_INFO;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.Arrays;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

public final class g extends g3.a implements i3.a {
    public static final g.a g = new g.a(null);
    private final i3.a f;
    public g(i3.a iStreamInfoDeal) { Intrinsics.checkNotNullParameter(iStreamInfoDeal, "iStreamInfoDeal"); this.f = iStreamInfoDeal; }
    @Override public void a(boolean isFreezeData, Function1 freezeCallback, Function1 thawCallback) { this.f.a(isFreezeData, freezeCallback, thawCallback); }
    @Override public void b(h3.a streamInfo, PreviewInfoDataBean previewInfoData, Function1 metadataCallback, Function5 overlayCallback) { Intrinsics.checkNotNullParameter(previewInfoData, "previewInfoData"); this.f.b(streamInfo, previewInfoData, metadataCallback, overlayCallback); }
    @Override public void c(h3.a streamInfo, byte[] rawAppendData, Function1 callback) { this.f.c(streamInfo, rawAppendData, callback); }
    @Override public PreviewStreamInfo d(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        PreviewInfoDataBean previewInfo = l(frameInfoData);
        IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV upload = new IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV();
        k3.b.d(k3.b.a, upload, previewInfo.getByteArrHead(), null, 4, null);
        return new PreviewStreamInfo(previewInfo, new h3.c(upload.ifrRealtimeTmOutcomeUploadInfo));
    }
    protected PreviewInfoDataBean l(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        Size yuvSize = new Size(0, 0); Size rotateSize = new Size(0, 0);
        int rawSize = 0, rawAppendSize = 0, lineBytes = 0, yuvBytes = 0;
        if (frameInfoData.length == 176128) { yuvSize = new Size(256, 192); rotateSize = new Size(192, 256); rawSize = 98304; rawAppendSize = 2048; lineBytes = 1024; yuvBytes = 73728; }
        else if (frameInfoData.length == 393216) { yuvSize = new Size(384, 288); rotateSize = new Size(288, 384); rawSize = 221184; rawAppendSize = 3072; lineBytes = 1536; yuvBytes = 165888; }
        byte[] rawData = rawSize + lineBytes >= 0 ? Arrays.copyOfRange(frameInfoData, 0, rawSize + lineBytes) : new byte[0];
        int yuvStart = rawSize + rawAppendSize;
        byte[] yuv = Arrays.copyOfRange(frameInfoData, yuvStart, yuvStart + yuvBytes);
        return new PreviewInfoDataBean(yuv, k3.a.a.c(yuv, yuvSize, rotateSize, 90), new byte[0], rawData,
                Arrays.copyOfRange(frameInfoData, rawSize, rawSize + rawAppendSize), new byte[0], new byte[0], new byte[0], new byte[0]);
    }
    public static final class a { private a() {} public a(DefaultConstructorMarker marker) {} }
}
