package Z2;

import android.util.Size;
import com.hik.viewercommon.data.bean.UsbModuleType;
import kotlin.jvm.internal.Intrinsics;

public final class a {
    public static final Z2.a a;
    private static final Size b;
    private static final Size c;
    private static final Size d;
    private static final Size e;
    private static final Size f;
    private static final Size g;
    private static final Size h;
    private static final Size i;
    private static final Size j;
    private static final Size k;
    private static final Size l;
    private static final Size m;
    private static final Size n;
    private static final Size o;
    private static f3.k p;
    private static boolean q;
    private static boolean r;
    private static boolean s;
    private static final int t;
    private static final int u;

    static {
        a = new Z2.a();
        b = new Size(192, 256);
        c = new Size(720, 960);
        d = new Size(96, 96);
        e = new Size(720, 720);
        f = new Size(192, 520);
        g = new Size(256, 344);
        h = new Size(192, 256);
        i = new Size(256, 192);
        j = new Size(288, 384);
        k = new Size(288, 776);
        l = new Size(96, 176);
        m = new Size(384, 512);
        n = new Size(288, 384);
        o = new Size(384, 288);
        p = new f3.a();
        q = true;
        s = true;
        t = org.Thermal.PlayM4.Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_NV12;
        u = org.Thermal.PlayM4.Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_I420;
    }

    private a() {}

    public final Size a() { return e; }
    public final Size b() { return l; }
    public final Size c() { return d; }
    public final Size d() { return n; }
    public final Size e() { return o; }
    public final Size f() { return k; }
    public final Size g() { return m; }
    public final Size h() { return j; }
    public final boolean i() { return q; }
    public final Size j() { return c; }
    public final Size k() { return h; }
    public final Size l() { return i; }
    public final Size m() { return f; }
    public final Size n() { return g; }
    public final Size o() { return b; }
    public final f3.k p() { return p; }
    public final boolean q() { return r; }
    public final int r() { return u; }
    public final int s() { return t; }
    public final boolean t() { return Intrinsics.areEqual(Z2.g.b(Z2.g.a, false, 1, null), UsbModuleType.F1.INSTANCE) && s; }
    public final void u(f3.k value) { Intrinsics.checkNotNullParameter(value, "<set-?>"); p = value; }
}
