package A2;

import android.os.Build;
import kotlin.jvm.internal.Intrinsics;

/** Exact Viewer LA2/b device record-source guard recovered from classes.dex. */
public final class b {
    public static final b a;
    private static final boolean b;
    private static final boolean c;
    private static final boolean d;
    private static final boolean e;
    private static final boolean f;
    private static final boolean g;
    private static final boolean h;
    private static final boolean i;
    private static final boolean j;
    private static final boolean k;
    private static final boolean l;
    private static final boolean m;
    private static final boolean n;
    private static final boolean o;
    private static final boolean p;
    private static final boolean q;
    private static final boolean r;
    private static final boolean s;
    private static final boolean t;
    private static final boolean u;
    private static final boolean v;
    private static final boolean w;
    private static final boolean x;

    static {
        a = new b();
        String manufacturer = Build.MANUFACTURER;
        b = Intrinsics.areEqual(manufacturer, "HUAWEI") && Intrinsics.areEqual(Build.MODEL, "CET-AL00");
        c = Intrinsics.areEqual(manufacturer, "samsung") && Intrinsics.areEqual(Build.MODEL, "SM-S9010");
        d = Intrinsics.areEqual(manufacturer, "samsung") && Intrinsics.areEqual(Build.MODEL, "SM-T500");
        e = Intrinsics.areEqual(manufacturer, "samsung") && Intrinsics.areEqual(Build.MODEL, "SM-X200");
        f = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 3");
        g = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 3 XL");
        h = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 3a");
        i = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 3a XL");
        j = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 4");
        k = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 4 XL");
        l = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 4a");
        m = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 4a 5G");
        n = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 5");
        o = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 5a");
        p = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 6");
        q = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 6a");
        r = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 6 Pro");
        s = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 7");
        t = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 7a");
        u = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 7 Pro");
        v = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 8");
        w = Intrinsics.areEqual(manufacturer, "Google") && Intrinsics.areEqual(Build.MODEL, "Pixel 8 Pro");
        x = (f || g || h || i || j || k || l || m || n || o || p || q || r || s || t || u || v || w)
            && Build.VERSION.SDK_INT >= 34;
    }

    private b() { }

    public final boolean a() { return x; }
    public final boolean b() { return g; }
    public final boolean c() { return j; }
    public final boolean d() { return l; }
    public final boolean e() { return c; }
}
