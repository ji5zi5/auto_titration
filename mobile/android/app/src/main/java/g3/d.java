package g3;

import android.util.Size;
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy;
import com.hik.f2module.IFR_INFO;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.Arrays;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

public class d extends g3.a implements i3.a {
    public static final d.a h = new d.a(null);
    private final i3.a f;
    private Function1 g;


    public d(i3.a iStreamInfoDeal) {
        Intrinsics.checkNotNullParameter(iStreamInfoDeal, "iStreamInfoDeal");
        this.f = iStreamInfoDeal;
    }

    @Override public void a(boolean isFreezeData, Function1 freezeCallback, Function1 thawCallback) {
        this.f.a(isFreezeData, freezeCallback, thawCallback);
    }

    @Override public void b(h3.a streamInfo, PreviewInfoDataBean previewInfoData, Function1 metadataCallback, Function5 overlayCallback) {
        Intrinsics.checkNotNullParameter(previewInfoData, "previewInfoData");
        this.f.b(streamInfo, previewInfoData, metadataCallback, overlayCallback);
    }

    @Override public void c(h3.a streamInfo, byte[] rawAppendData, Function1 callback) {
        this.f.c(streamInfo, rawAppendData, callback);
    }

    @Override public PreviewStreamInfo d(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        PreviewStreamInfo result = kr.auto.titration.mobile.thermal.internal.G3DexBytes.emptyStreamInfo();
        boolean isOffStreamInfo = false;
        boolean isFreezeData = false;
        switch (frameInfoData.length) {
            case 41160:
            case 183496:
            case 400584: {
                PreviewInfoDataBean previewInfo = m(frameInfoData);
                byte[] head = previewInfo.getByteArrHead();
                IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE upload = new IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE();
                k3.b.d(k3.b.a, upload, head, null, 4, null);
                result = new PreviewStreamInfo(previewInfo, new h3.c(upload.ifrRealtimeTmOutcomeUploadInfo));
                isFreezeData = upload.dwIsFreezedata != 0;
                isOffStreamInfo = true;
                break;
            }
            case 61384:
            case 101320:
            case 193480: {
                PreviewInfoDataBean previewInfo = n(frameInfoData);
                byte[] head = previewInfo.getByteArrHead();
                HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO privateInfo = new HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO();
                k3.b.d(k3.b.a, privateInfo, head, null, 4, null);
                result = new PreviewStreamInfo(previewInfo, new h3.b(privateInfo));
                isFreezeData = privateInfo.temp_Info.Upload.bFreez != 0;
                break;
            }
            default:
                break;
        }
        a(isFreezeData, e(), f());
        PreviewInfoDataBean resultPreviewInfo = result.getPreviewInfoData();
        b(result.getIStreamInfo(), resultPreviewInfo, i(), h());
        c(result.getIStreamInfo(), resultPreviewInfo.getByteArrRawAppendData(), g());
        if (isOffStreamInfo && this.g != null) this.g.invoke(result.getPreviewInfoData());
        return result;
    }

    public final Function1 l() { return this.g; }

    protected PreviewInfoDataBean m(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        Size yuvSize = new Size(0, 0);
        Size rotateSize = new Size(0, 0);
        int rawSize = 0;
        int rawAppendSize = 0;
        int lineBytes = 0;
        int yuvSizeBytes = 0;
        switch (frameInfoData.length) {
            case 41160:
                yuvSize = new Size(96, 96); rotateSize = new Size(96, 96);
                rawSize = 18432; rawAppendSize = 768; lineBytes = 384; yuvSizeBytes = 13824; break;
            case 183496:
                yuvSize = new Size(256, 192); rotateSize = new Size(192, 256);
                rawSize = 98304; rawAppendSize = 2048; lineBytes = 1024; yuvSizeBytes = 73728; break;
            case 400584:
                yuvSize = new Size(384, 288); rotateSize = new Size(288, 384);
                rawSize = 221184; rawAppendSize = 3072; lineBytes = 1536; yuvSizeBytes = 165888; break;
            default: break;
        }
        byte[] head = Arrays.copyOfRange(frameInfoData, 0, 7368);
        int rawEnd = 7368 + rawSize;
        byte[] raw = Arrays.copyOfRange(frameInfoData, 7368, rawEnd);
        byte[] rotatedRaw = kr.auto.titration.mobile.thermal.internal.G3DexBytes.rotateRaw(raw, rotateSize);
        int line1End = rawEnd + yuvSize.getWidth() * 2;
        int line2End = line1End + yuvSize.getWidth() * 2;
        byte[] line1 = Arrays.copyOf(Arrays.copyOfRange(frameInfoData, rawEnd, line1End), yuvSize.getHeight() * 2);
        byte[] line2 = Arrays.copyOf(Arrays.copyOfRange(frameInfoData, line1End, line2End), yuvSize.getHeight() * 2);
        byte[] offAppend = kr.auto.titration.mobile.thermal.internal.G3DexBytes.concat(line1, line2);
        byte[] rawAppend = Arrays.copyOfRange(frameInfoData, rawEnd, rawEnd + rawAppendSize);
        int yuvStart = rawEnd + rawAppendSize;
        int yuvEnd = yuvStart + yuvSizeBytes;
        byte[] yuv = Arrays.copyOfRange(frameInfoData, yuvStart, yuvEnd);
        byte[] yuvAppend = Arrays.copyOfRange(frameInfoData, yuvEnd, yuvEnd + rawAppendSize);
        return new PreviewInfoDataBean(yuv, k3.a.a.c(yuv, yuvSize, rotateSize, 90), head,
                kr.auto.titration.mobile.thermal.internal.G3DexBytes.concat(rotatedRaw, offAppend), rawAppend, yuvAppend, line2, rotatedRaw, offAppend);
    }

    protected PreviewInfoDataBean n(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        Size yuvSize = new Size(0, 0);
        Size rotateSize = new Size(0, 0);
        int rawSize = 0;
        int rawAppendSize = 0;
        int lineSourceStart = 0;
        int yuvSizeBytes = 0;
        boolean hasRaw = false;
        switch (frameInfoData.length) {
            case 61384:
                yuvSize = new Size(96, 96); rotateSize = new Size(96, 96);
                rawSize = 18432; rawAppendSize = 768; lineSourceStart = 46024; yuvSizeBytes = 13824; hasRaw = true; break;
            case 101320:
                yuvSize = new Size(256, 192); rotateSize = new Size(192, 256);
                rawAppendSize = 2048; lineSourceStart = 27592; yuvSizeBytes = 73728; break;
            case 193480:
                yuvSize = new Size(384, 288); rotateSize = new Size(288, 384);
                rawAppendSize = 3072; lineSourceStart = 27592; yuvSizeBytes = 165888; break;
            default: break;
        }
        byte[] head = Arrays.copyOfRange(frameInfoData, 0, 27592);
        byte[] raw = hasRaw ? Arrays.copyOfRange(frameInfoData, 27592, 27592 + rawSize) : new byte[0];
        byte[] rotatedRaw = hasRaw ? kr.auto.titration.mobile.thermal.internal.G3DexBytes.rotateRaw(raw, rotateSize) : new byte[0];
        int line1End = lineSourceStart + yuvSize.getWidth() * 2;
        int line2End = line1End + yuvSize.getWidth() * 2;
        byte[] line1 = Arrays.copyOf(Arrays.copyOfRange(frameInfoData, lineSourceStart, line1End), yuvSize.getHeight() * 2);
        byte[] line2 = Arrays.copyOf(Arrays.copyOfRange(frameInfoData, line1End, line2End), yuvSize.getHeight() * 2);
        byte[] offAppend = kr.auto.titration.mobile.thermal.internal.G3DexBytes.concat(line1, line2);
        byte[] rawAppend = hasRaw ? Arrays.copyOfRange(frameInfoData, 27592 + rawSize, 27592 + rawSize + rawAppendSize) : new byte[0];
        int yuvStart = hasRaw ? 27592 + rawSize + rawAppendSize : 27592;
        byte[] yuv = Arrays.copyOfRange(frameInfoData, yuvStart, yuvStart + yuvSizeBytes);
        byte[] yuvAppend = hasRaw ? Arrays.copyOfRange(frameInfoData, yuvStart + yuvSizeBytes, yuvStart + yuvSizeBytes + rawAppendSize) : new byte[0];
        return new PreviewInfoDataBean(yuv, k3.a.a.c(yuv, yuvSize, rotateSize, 90), head,
                rotatedRaw, rawAppend, yuvAppend, line2, new byte[0], offAppend);
    }

    public final void o(Function1 function1) { this.g = function1; }

    public static final class a {
        private a() {}
        public a(DefaultConstructorMarker marker) {}
    }
}
