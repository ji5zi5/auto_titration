package A2;

import android.os.Build;
import org.Thermal.PlayM4.Player;

/** Exact Viewer LA2/d record-source default selector recovered from classes.dex. */
public final class d {
    public static final d a;

    static {
        a = new d();
    }

    private d() { }

    public final int a() {
        b guard = b.a;
        int defaultRecordCodecType;
        if (!guard.e() && !guard.b() && !guard.c() && !guard.d() && !guard.a()) {
            defaultRecordCodecType = Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_NV12;
        } else {
            defaultRecordCodecType = Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_I420;
        }
        new StringBuilder()
            .append("getDefaultRecordCodecType:manufacturer_")
            .append(Build.MANUFACTURER)
            .append("_model_")
            .append(Build.MODEL)
            .append("_defaultRecordCodecType_")
            .append(defaultRecordCodecType);
        return defaultRecordCodecType;
    }
}
