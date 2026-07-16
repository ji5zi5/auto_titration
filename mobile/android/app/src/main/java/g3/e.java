package g3;

import android.util.Size;
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy;
import com.hik.f2module.IFR_INFO;
import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import java.util.Arrays;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

public final class e extends g3.d {
    public static final e.a j = new e.a(null);
    private final i3.a i;


    public e(i3.a iStreamInfoDeal) {
        super(iStreamInfoDeal);
        Intrinsics.checkNotNullParameter(iStreamInfoDeal, "iStreamInfoDeal");
        this.i = iStreamInfoDeal;
    }

    @Override public PreviewStreamInfo d(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        PreviewStreamInfo result = kr.auto.titration.mobile.thermal.internal.G3DexBytes.emptyStreamInfo();
        boolean isOffStreamInfo = false;
        boolean isFreezeData = false;
        if (frameInfoData.length == 183496) {
            PreviewInfoDataBean previewInfo = m(frameInfoData);
            IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE upload = new IFR_INFO.USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE();
            k3.b.d(k3.b.a, upload, previewInfo.getByteArrHead(), null, 4, null);
            result = new PreviewStreamInfo(previewInfo, new h3.c(upload.ifrRealtimeTmOutcomeUploadInfo));
            isFreezeData = upload.dwIsFreezedata != 0;
            isOffStreamInfo = true;
        } else if (frameInfoData.length == 203720) {
            PreviewInfoDataBean previewInfo = n(frameInfoData);
            HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO privateInfo = new HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO();
            k3.b.d(k3.b.a, privateInfo, previewInfo.getByteArrHead(), null, 4, null);
            result = new PreviewStreamInfo(previewInfo, new h3.b(privateInfo));
            isFreezeData = privateInfo.temp_Info.Upload.bFreez != 0;
        }
        a(isFreezeData, e(), f());
        PreviewInfoDataBean resultPreviewInfo = result.getPreviewInfoData();
        b(result.getIStreamInfo(), resultPreviewInfo, i(), h());
        c(result.getIStreamInfo(), resultPreviewInfo.getByteArrRawAppendData(), g());
        if (isOffStreamInfo) {
            Function1 callback = l();
            if (callback != null) callback.invoke(result.getPreviewInfoData());
        }
        return result;
    }

    @Override protected PreviewInfoDataBean n(byte[] frameInfoData) {
        Intrinsics.checkNotNullParameter(frameInfoData, "frameInfoData");
        Size yuvSize = new Size(256, 192);
        Size rotateSize = new Size(192, 256);
        byte[] head = Arrays.copyOfRange(frameInfoData, 0, 27592);
        byte[] raw = Arrays.copyOfRange(frameInfoData, 27592, 125896);
        byte[] rawAppend = Arrays.copyOfRange(frameInfoData, 125896, 127944);
        int line1End = 125896 + yuvSize.getWidth() * 2;
        int line2End = line1End + yuvSize.getWidth() * 2;
        byte[] line1 = Arrays.copyOf(Arrays.copyOfRange(frameInfoData, 125896, line1End), yuvSize.getHeight() * 2);
        byte[] line2 = Arrays.copyOf(Arrays.copyOfRange(frameInfoData, line1End, line2End), yuvSize.getHeight() * 2);
        byte[] offAppend = kr.auto.titration.mobile.thermal.internal.G3DexBytes.concat(line1, line2);
        byte[] rotatedRaw = kr.auto.titration.mobile.thermal.internal.G3DexBytes.rotateRaw(raw, rotateSize);
        byte[] yuv = Arrays.copyOfRange(frameInfoData, 127944, 201672);
        byte[] yuvAppend = Arrays.copyOfRange(frameInfoData, 201672, 203720);
        return new PreviewInfoDataBean(yuv, k3.a.a.c(yuv, yuvSize, rotateSize, 90), head,
                rotatedRaw, rawAppend, yuvAppend, line2, raw, offAppend);
    }

    public static final class a {
        private a() {}
        public a(DefaultConstructorMarker marker) {}
    }
}
