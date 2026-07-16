package hik.common.yyrj.businesscommon;

import android.content.Context;
import android.content.SharedPreferences;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import kotlin.Lazy;
import kotlin.LazyKt;
import kotlin.LazyThreadSafetyMode;
import kotlin.jvm.functions.Function0;
import kotlin.jvm.internal.DefaultConstructorMarker;
import kotlin.jvm.internal.Intrinsics;

public final class b {
    public static final hik.common.yyrj.businesscommon.b.a d = new hik.common.yyrj.businesscommon.b.a(null);
    private static final Lazy<hik.common.yyrj.businesscommon.b> e = LazyKt.lazy(LazyThreadSafetyMode.SYNCHRONIZED, new Function0<hik.common.yyrj.businesscommon.b>() { @Override public hik.common.yyrj.businesscommon.b invoke() { return hik.common.yyrj.businesscommon.b.c(); } });
    private Context a;
    private final ObjectMapper b = new ObjectMapper();
    private SharedPreferences c;
    public b() {}
    public static final class a { private a() {} public /* synthetic */ a(DefaultConstructorMarker marker) { this(); } public final hik.common.yyrj.businesscommon.b a() { return (hik.common.yyrj.businesscommon.b) hik.common.yyrj.businesscommon.b.d().getValue(); } }
    private final void J(List value) { c.edit().putString("preview_logo_visible", b.writeValueAsString(value)).apply(); }
    private static final boolean K(String it, String value) { Intrinsics.checkNotNullParameter(it, "it"); return Intrinsics.areEqual(it, value); }
    public static /* synthetic */ boolean a(String it, String value) { return K(it, value); }
    public static /* synthetic */ hik.common.yyrj.businesscommon.b b() { return c(); }
    private static final hik.common.yyrj.businesscommon.b c() { return new hik.common.yyrj.businesscommon.b(); }
    public static final /* synthetic */ Lazy d() { return e; }
    private final List n() { String json = c.getString("preview_logo_visible", ""); if (json == null || json.length() == 0) return new ArrayList(); Object value = b.readValue(json, new ArrayList().getClass()); Intrinsics.checkNotNullExpressionValue(value, "readValue(...)"); return new ArrayList((Collection) value); }
    public static /* synthetic */ boolean x(hik.common.yyrj.businesscommon.b self, String serialNum, int mask, Object unused) { if ((mask & 1) != 0) serialNum = u5.B.a.k().getSerialNumber(); return self.w(serialNum); }
    public final void A(long value) { c.edit().putLong("agree_privacy_version", value).apply(); }
    public final void B(long value) { c.edit().putLong("privacy_version", value).apply(); }
    public final void C(List value) { Intrinsics.checkNotNullParameter(value, "value"); c.edit().putString("device_list_for_name", b.writeValueAsString(value)).apply(); }
    public final void D(int value) { c.edit().putInt("imageManagerFileType", value).apply(); }
    public final void E(List value) { Intrinsics.checkNotNullParameter(value, "value"); c.edit().putString("logged_devices_list", b.writeValueAsString(value)).apply(); }
    public final void F(String value) { Intrinsics.checkNotNullParameter(value, "value"); c.edit().putString("manual_login_ip", value).apply(); }
    public final void G(String value) { Intrinsics.checkNotNullParameter(value, "value"); c.edit().putString("pdfList", value).apply(); }
    public final void H(List value) { Intrinsics.checkNotNullParameter(value, "value"); J(value); }
    public final void I(String key, boolean value) { Intrinsics.checkNotNullParameter(key, "key"); c.edit().putBoolean(key, value).apply(); }
    public final void L(boolean value) { c.edit().putBoolean("isAutoCollect", value).apply(); }
    public final void M(boolean value) { c.edit().putBoolean("isAutoPicName", value).apply(); }
    public final void N(List value) { Intrinsics.checkNotNullParameter(value, "value"); c.edit().putString("preview_logo_visible", b.writeValueAsString(value)).apply(); }
    public final void O(boolean value) { c.edit().putBoolean("is_show_detail_info", value).apply(); }
    public final void P(boolean value) { c.edit().putBoolean("is_show_fusion", value).apply(); }
    public final void Q(boolean value) { c.edit().putBoolean("is_show_logo", value).apply(); }
    public final void R(boolean value) { c.edit().putBoolean("is_show_osd", value).apply(); }
    public final void S(boolean value) { c.edit().putBoolean("show_photo_zoom_tip", value).apply(); }
    public final boolean e() { return c.getBoolean("activate_business_agree", false); }
    public final long f() { return c.getLong("agree_privacy_version", 0L); }
    public final long g() { return c.getLong("privacy_version", 0L); }
    public final List h() { String json = c.getString("device_list_for_name", ""); return json == null || json.length() == 0 ? new ArrayList() : new ArrayList(); }
    public final int i() { return c.getInt("imageManagerFileType", 0); }
    public final long j() { return c.getLong("language_change_time", 0L); }
    public final List k() { String json = c.getString("logged_devices_list", ""); return json == null || json.length() == 0 ? new ArrayList() : new ArrayList(); }
    public final String l() { return c.getString("manual_login_ip", ""); }
    public final List m() { String json = c.getString("pdfList", ""); return json == null || json.length() == 0 ? new ArrayList() : new ArrayList(); }
    public final boolean o() { return c.getBoolean("isAutoCollect", false); }
    public final boolean p() { return c.getBoolean("isAutoPicName", false); }
    public final List q() { String json = c.getString("preview_logo_visible", ""); return json == null || json.length() == 0 ? new ArrayList() : new ArrayList(); }
    public final boolean r() { return c.getBoolean("is_show_detail_info", false); }
    public final boolean s() { return c.getBoolean("is_show_fusion", false); }
    public final boolean t() { return c.getBoolean("is_show_logo", false); }
    public final boolean u() { return c.getBoolean("is_show_osd", false); }
    public final void v(Context context) { Intrinsics.checkNotNullParameter(context, "context"); this.a = context; this.c = context.getSharedPreferences("com.hikvison.commercialvision:settingConfig", 0); }
    public final boolean w(String serialNum) { Intrinsics.checkNotNullParameter(serialNum, "serialNum"); for (Object item : n()) if (Intrinsics.areEqual((String) item, serialNum)) return false; return true; }
    public final boolean y() { return c.getBoolean("is_show_detail_info", false); }
    public final void z(boolean value) { c.edit().putBoolean("activate_business_agree", value).apply(); }
}
