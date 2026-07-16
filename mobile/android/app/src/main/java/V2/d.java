package V2;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.RectF;
import android.util.Size;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.content.Context;
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy;
import com.hik.f1module.helper.ThermalInfoHelper;
import com.hik.f2module.IFR_INFO;
import com.hik.modulelib.bean.ThermometryBasicBean;
import com.hik.thermalplayer.ThermalPlayer;
import hik.common.yyrj.uicommon.data.ModuleType;
import hik.common.yyrj.uicommon.data.ModuleType.F2ModuleType;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

/** Official M4 F2 renderer: packets are packed as ThermalPlayer private/YUV frames. */
public final class d implements f {
    public static final d.a c = new d.a(null);
    private final SurfaceView a;
    private ThermalPlayer b;

    public d(SurfaceView surfaceView) {
        Intrinsics.checkNotNullParameter(surfaceView, "surfaceView");
        this.a = surfaceView;
        Context context = surfaceView.getContext();
        Intrinsics.checkNotNullExpressionValue(context, "getContext(...)");
        SurfaceHolder holder = surfaceView.getHolder();
        Intrinsics.checkNotNullExpressionValue(holder, "getHolder(...)");
        this.b = new ThermalPlayer(context, holder, 25000L);
    }

    private String l() { return Z2.g.a.U().getModuleID(); }
    private ModuleType m() { return d3.c.a.a(l()); }
    private boolean n() { return m() == F2ModuleType.F0; }
    private boolean o() { return Z2.g.a.U().getDevType() == 1; }

    @Override public boolean a() { return this.b.stopRecord(); }
    @Override public void b(com.hik.library.player.b listener) { Intrinsics.checkNotNullParameter(listener, "listener"); this.b.addPlayListener(listener); }
    @Override public void c() { this.b.removeAllPlayListener(); }
    @Override public boolean d(Size picSize, String filePath) { Intrinsics.checkNotNullParameter(picSize, "picSize"); Intrinsics.checkNotNullParameter(filePath, "filePath"); return this.b.startRecord(filePath, picSize, l2.k.e("RECORD_CODEC_TYPE", A2.d.a.a())); }
    @Override public byte[] e(Size picSize) { Intrinsics.checkNotNullParameter(picSize, "picSize"); return this.b.takePhoto(picSize).b(); }
    @Override public com.hik.library.player.d f(Size picSize) { Intrinsics.checkNotNullParameter(picSize, "picSize"); return this.b.takePhoto(picSize); }

    @Override public void g(boolean first, boolean second, boolean third, boolean fourth, int mode, float firstScale, float secondScale) {
        Z2.g state = Z2.g.a;
        state.s();
        Size showFirSize = state.E();
        new StringBuilder().append("setupOsdBgPicAddInfo: showFirSize=").append(showFirSize);
        boolean landscape = showFirSize.getWidth() > showFirSize.getHeight();

        InputStream stream;
        try {
            stream = d2.a.a().getResources().getAssets().open("osd_bg.png");
        } catch (IOException exception) {
            throw new RuntimeException(exception);
        }
        Intrinsics.checkNotNullExpressionValue(stream, "open(...)");
        Bitmap osdBitmap = BitmapFactory.decodeStream(stream);

        int temperatureRows = second ? 1 : 0;
        if (third) temperatureRows += 1;
        if (fourth) temperatureRows += 1;

        float firstHeight;
        if (temperatureRows == 1) firstHeight = 0.046f;
        else if (temperatureRows == 2) firstHeight = 0.084f;
        else if (temperatureRows == 3) firstHeight = 0.12f;
        else firstHeight = 0f;

        float row1Height = 0f;
        float row2Height = 0f;
        float row3Height = 0f;
        float row4Height = 0f;
        List<?> rowTypes = state.F();
        if (rowTypes.size() > 0) {
            int rectType = ((Number) rowTypes.get(0)).intValue();
            row1Height = (rectType + 1) * 0.0405f;
            if (rectType == 0) row1Height += 0.01f;
            else if (rectType == 1 || rectType == 2) row1Height += 0.005f;
        }
        if (rowTypes.size() > 1) {
            int rectType = ((Number) rowTypes.get(1)).intValue();
            row2Height = (rectType + 1) * 0.0405f;
            if (rectType == 0) row2Height += 0.01f;
            else if (rectType == 1) row2Height += 0.005f;
            else if (rectType == 2) row1Height += 0.005f;
        }
        if (rowTypes.size() > 2) {
            int rectType = ((Number) rowTypes.get(2)).intValue();
            row3Height = (rectType + 1) * 0.0405f;
            if (rectType == 0) row3Height += 0.01f;
            else if (rectType == 1) row3Height += 0.005f;
            else if (rectType == 2) row1Height += 0.005f;
        }
        if (rowTypes.size() > 3) {
            int rectType = ((Number) rowTypes.get(3)).intValue();
            row4Height = (rectType + 1) * 0.0405f;
            if (rectType == 0) row4Height += 0.01f;
            else if (rectType == 1) row4Height += 0.005f;
            else if (rectType == 2) row1Height += 0.005f;
        }

        float right = 0.116f + 0.028f * firstScale + 0.01f;
        if (landscape) right = 0.11f + 0.007f * firstScale + 0.004f;
        if (n()) right *= 0.8f;

        RectF firstRect = new RectF(0.01f, 0.008f, right, 0.008f + firstHeight);
        boolean firstVisible = temperatureRows > 0;
        Intrinsics.checkNotNull(osdBitmap);
        this.b.setOsdBgPicAddInfo00(osdBitmap, firstRect, 0.55f, firstVisible);

        float row1Top = firstVisible ? firstRect.bottom + 0.008f : firstRect.bottom;
        RectF row1 = new RectF(firstRect.left, row1Top, right, row1Top + row1Height);
        float row2Top = row1.bottom + 0.008f;
        RectF row2 = new RectF(firstRect.left, row2Top, right, row2Top + row2Height);
        float row3Top = row2.bottom + 0.008f;
        RectF row3 = new RectF(firstRect.left, row3Top, right, row3Top + row3Height);
        float row4Top = row3.bottom + 0.008f;
        RectF row4 = new RectF(firstRect.left, row4Top, right, row4Top + row4Height);

        boolean disabled = false;
        if (o()) {
            if (mode == 1) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, false);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, false);
                this.b.setOsdBgPicAddInfo04(osdBitmap, row4, 0.55f, false);
            } else if (mode == 2) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, true);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, false);
                this.b.setOsdBgPicAddInfo04(osdBitmap, row4, 0.55f, false);
            } else if (mode == 3) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, true);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, true);
                this.b.setOsdBgPicAddInfo04(osdBitmap, row4, 0.55f, false);
            } else if (mode == 4) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, true);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, true);
                this.b.setOsdBgPicAddInfo04(osdBitmap, row4, 0.55f, true);
                disabled = false;
            } else {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, false);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, false);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, false);
                this.b.setOsdBgPicAddInfo04(osdBitmap, row4, 0.55f, false);
            }
        }
        if (!first) {
            this.b.setOsdBgPicAddInfo00(osdBitmap, firstRect, 0.55f, disabled);
            this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, disabled);
            this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, disabled);
            this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, disabled);
            this.b.setOsdBgPicAddInfo04(osdBitmap, row4, 0.55f, disabled);
        }
    }

    @Override public void h(byte[] rawData, byte[] nv12Data, Size yuvImgSize, int frameNumStamp) {
        Intrinsics.checkNotNullParameter(nv12Data, "nv12Data");
        Intrinsics.checkNotNullParameter(yuvImgSize, "yuvImgSize");
        new StringBuilder().append("updateFrameData: f2ModuleOsdUseM4 ").append(Z2.a.a.i());
        if (!Z2.a.a.i()) {
            byte[] yuvFrame = ThermalInfoHelper.INSTANCE.getYuvThermalDataInfo(nv12Data, yuvImgSize);
            if (yuvFrame != null) this.b.updateFrameData(yuvFrame);
            return;
        }

        Z2.g state = Z2.g.a;
        String serialNumber = state.U().getSerialNumber();
        ModuleType moduleType = d3.c.a.a(state.U().getModuleID());
        int alarmStatus = state.i(serialNumber, state.f() ? 1 : 0);
        String alarmHigh = state.g(serialNumber, state.e());
        String alarmLow = state.h(serialNumber);
        int degree = state.w(serialNumber);
        Integer[] specialFrameSizes = new Integer[] {98304, 221184};
        h3.a streamInfo = state.o();
        new StringBuilder().append("updateFrameData: iStreamInfo ").append(streamInfo);

        byte[] thermalPrivateInfoData = null;
        if (streamInfo instanceof h3.b) {
            new StringBuilder().append("updateFrameData:is PrivateStreamInfo frameNumStamp=").append(frameNumStamp);
            HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO privateInfo = ((h3.b) streamInfo).a();
            HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO info = d3.i.a.m(
                privateInfo,
                state.v(),
                alarmStatus,
                alarmHigh,
                alarmLow,
                state.u(),
                degree
            );
            privateInfo.privateInfo_header.dsp_std_stamp = frameNumStamp;
            thermalPrivateInfoData = k3.b.b(k3.b.a, info, null, 2, null);
        } else if (streamInfo instanceof h3.c) {
            IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO uploadInfo = ((h3.c) streamInfo).a();
            new StringBuilder().append("updateFrameData: 8 11 12的抓图和12的假图 frameNumStamp=").append(frameNumStamp);
            if (java.util.Arrays.asList(specialFrameSizes).contains(state.n())) {
                byte[] yuvFrame = ThermalInfoHelper.INSTANCE.getYuvThermalDataInfo(state.j(), yuvImgSize);
                if (yuvFrame != null) this.b.updateFrameData(yuvFrame);
                return;
            }
            ThermometryBasicBean basic = state.K();
            HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO info = d3.i.a.k(
                uploadInfo,
                basic.getEnableCenterTem(),
                basic.getEnableHighTem(),
                basic.getEnableLowTem(),
                state.L(),
                true,
                alarmStatus,
                alarmHigh,
                alarmLow,
                state.u(),
                state.M(),
                moduleType,
                degree
            );
            info.privateInfo_header.dsp_std_stamp = frameNumStamp;
            thermalPrivateInfoData = k3.b.b(k3.b.a, info, null, 2, null);
        }

        if (thermalPrivateInfoData != null) {
            new StringBuilder()
                .append("updateFrameData: thermalPrivateInfoData=")
                .append(thermalPrivateInfoData.length)
                .append(" nv12Data=")
                .append(nv12Data.length)
                .append(" yuvImgSize=")
                .append(yuvImgSize);
            int totalLength = n() ? 27640 : 0;
            byte[] frameDataNew = ThermalInfoHelper.INSTANCE.getThermalDataInfo(thermalPrivateInfoData, nv12Data, yuvImgSize, totalLength);
            new StringBuilder().append("updateFrameData: frameDataNew ").append(frameDataNew != null ? Integer.valueOf(frameDataNew.length) : null);
            if (frameDataNew != null) this.b.updateFrameData(frameDataNew);
        }
    }

    @Override public void i(Size showSize) {
        Intrinsics.checkNotNullParameter(showSize, "showSize");
        boolean topAtZero = Z2.g.a.s();
        InputStream stream;
        try {
            stream = d2.a.a().getResources().getAssets().open("logo_hik_w.png");
        } catch (IOException exception) {
            throw new RuntimeException(exception);
        }
        Intrinsics.checkNotNullExpressionValue(stream, "open(...)");
        Bitmap bitmap = BitmapFactory.decodeStream(stream);
        float scale = 0.06f / (((float) bitmap.getHeight()) / showSize.getHeight());
        float top = topAtZero ? 0f : 0.94f;
        Intrinsics.checkNotNull(bitmap);
        this.b.setLogoPicAddInfo(bitmap, new RectF(0.008f, top, ((float) bitmap.getWidth()) / showSize.getWidth() * scale, top + 0.06f));
    }

    @Override public void j(byte[] rawData, byte[] nv12Data, Size yuvImgSize, int frameNumStamp, List<?> overlays, Bitmap overlayBitmap) { Intrinsics.checkNotNullParameter(nv12Data, "nv12Data"); Intrinsics.checkNotNullParameter(yuvImgSize, "yuvImgSize"); }
    @Override public void k(int value) { this.b.setPseudoPicAddInfo(value, new Size(12, 83)); }
    @Override public void release() { this.b.release(); ThermalInfoHelper.INSTANCE.release(); }
    @Override public void start() { this.b.start(); }
    @Override public void stop() { this.b.stop(); }

    public static final class a {
        private a() { }
        public a(DefaultConstructorMarker ignored) { }
    }
}
