package V2;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.RectF;
import android.util.Size;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.content.Context;
import com.hik.thermalplayer.ThermalPlayer;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

/** Official M4 F1 renderer: raw/private frames are sent to ThermalPlayer. */
public final class b implements f {
    public static final b.a c = new b.a(null);
    private final SurfaceView a;
    private ThermalPlayer b;

    public b(SurfaceView surfaceView) {
        Intrinsics.checkNotNullParameter(surfaceView, "surfaceView");
        this.a = surfaceView;
        Context context = surfaceView.getContext();
        Intrinsics.checkNotNullExpressionValue(context, "getContext(...)");
        SurfaceHolder holder = surfaceView.getHolder();
        Intrinsics.checkNotNullExpressionValue(holder, "getHolder(...)");
        this.b = new ThermalPlayer(context, holder);
    }

    @Override public boolean a() { this.b.stopRecord(); return true; }
    @Override public void b(com.hik.library.player.b listener) { Intrinsics.checkNotNullParameter(listener, "listener"); }
    @Override public void c() { }
    @Override public boolean d(Size picSize, String filePath) {
        Intrinsics.checkNotNullParameter(picSize, "picSize");
        Intrinsics.checkNotNullParameter(filePath, "filePath");
        return this.b.startRecord(filePath, picSize, l2.k.e("RECORD_CODEC_TYPE", A2.d.a.a()));
    }
    @Override public byte[] e(Size picSize) { Intrinsics.checkNotNullParameter(picSize, "picSize"); return this.b.takePhoto(picSize).b(); }
    @Override public com.hik.library.player.d f(Size picSize) { Intrinsics.checkNotNullParameter(picSize, "picSize"); return this.b.takePhoto(picSize); }

    @Override public void g(boolean first, boolean second, boolean third, boolean fourth, int mode, float firstScale, float secondScale) {
        boolean devSupportsRows = Z2.g.a.U().getDevType() == 1;
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

        RectF firstRect = new RectF(
            0.005f,
            0.067f,
            0.16f + 0.021f * firstScale,
            0.122f + (temperatureRows - 1) * 0.04f
        );
        boolean firstVisible = temperatureRows > 0;
        Intrinsics.checkNotNull(osdBitmap);
        this.b.setOsdBgPicAddInfo00(osdBitmap, firstRect, 0.55f, firstVisible);

        float right = 0.11f + 0.015f * secondScale;
        RectF row1 = firstVisible
            ? new RectF(0.005f, 0.262f, right, 0.262f + 0.125f)
            : new RectF(0.005f, 0.067f, right, 0.067f + 0.125f);
        RectF row2 = firstVisible
            ? new RectF(0.005f, 0.432f, right, 0.432f + 0.125f)
            : new RectF(0.005f, 0.237f, right, 0.237f + 0.125f);
        float row3Top = (firstVisible ? 0.262f : 0.067f) + 2f * 0.17f;
        RectF row3 = new RectF(0.005f, row3Top, right, row3Top + 0.125f);

        if (devSupportsRows) {
            if (mode == 1) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, false);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, false);
            } else if (mode == 2) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, true);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, false);
            } else if (mode == 3) {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, true);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, true);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, true);
            } else {
                this.b.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, false);
                this.b.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, false);
                this.b.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, false);
            }
        }
    }

    @Override public void h(byte[] rawData, byte[] nv12Data, Size yuvImgSize, int frameNumStamp) {
        Intrinsics.checkNotNullParameter(nv12Data, "nv12Data");
        Intrinsics.checkNotNullParameter(yuvImgSize, "yuvImgSize");
        new StringBuilder().append("updateFrameData: ").append(rawData == null);
        if (rawData != null) this.b.updateFrameData(rawData);
    }

    @Override public void i(Size showSize) {
        Intrinsics.checkNotNullParameter(showSize, "showSize");
        InputStream stream;
        try {
            stream = d2.a.a().getResources().getAssets().open("logo_hik_w.png");
        } catch (IOException exception) {
            throw new RuntimeException(exception);
        }
        Intrinsics.checkNotNullExpressionValue(stream, "open(...)");
        Bitmap bitmap = BitmapFactory.decodeStream(stream);
        float scale = 0.06f / (((float) bitmap.getHeight()) / showSize.getHeight());
        Intrinsics.checkNotNull(bitmap);
        this.b.setLogoPicAddInfo(bitmap, new RectF(0.007f, 0f, ((float) bitmap.getWidth()) / showSize.getWidth() * scale, 0.06f));
    }

    @Override public void j(byte[] rawData, byte[] nv12Data, Size yuvImgSize, int frameNumStamp, List<?> overlays, Bitmap overlayBitmap) { Intrinsics.checkNotNullParameter(nv12Data, "nv12Data"); Intrinsics.checkNotNullParameter(yuvImgSize, "yuvImgSize"); }
    @Override public void k(int value) { this.b.setPseudoPicAddInfo(value, new Size(6, 83)); }
    @Override public void release() { }
    @Override public void start() { this.b.start(); com.hik.f1module.F1UsbModuleHelper.USB_SetPreviewEnable(true); }
    @Override public void stop() { this.b.stop(); com.hik.f1module.F1UsbModuleHelper.USB_SetPreviewEnable(false); }

    public static final class a {
        private a() { }
        public a(DefaultConstructorMarker ignored) { }
    }
}
