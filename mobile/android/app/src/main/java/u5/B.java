package u5;

import android.content.Context;
import hik.common.yyrj.businesscommon.data.DeviceInfoModel;
import hik.common.yyrj.businesscommon.entry.DeviceLoginModel;
import hik.common.yyrj.businesscommon.entry.F1DeviceInfo;
import hik.common.yyrj.businesscommon.entry.OfflineFileModel;
import java.util.*;
import kotlin.Unit;
import kotlin.jvm.functions.Function0;
import kotlin.jvm.internal.Intrinsics;

public final class B {
    private static int A; private static boolean B; private static String C; private static String D; private static String E; private static String F;
    private static boolean G; private static boolean H; private static boolean I; private static Function0 J; private static Function0 K;
    private static boolean L; private static boolean M; private static boolean N; private static boolean O; private static int P; private static boolean Q; private static boolean R;
    private static final String[] S;
    public static final u5.B a;
    private static DeviceInfoModel b; private static DeviceLoginModel c; private static F1DeviceInfo d;
    private static List e; private static List f; private static List g; private static String h; private static String i; private static String j; private static String k;
    private static boolean l; private static String m; private static String n; private static String o; private static String p; private static String q; private static boolean r;
    private static final Map s; private static final Map t; private static final Map u; private static OfflineFileModel v; private static List w; private static androidx.lifecycle.B x; private static int y; private static int z;
    static { a = new u5.B(); b = new DeviceInfoModel(); c = new DeviceLoginModel(); d = new F1DeviceInfo(); e = new ArrayList(); f = new ArrayList(); g = new ArrayList(); h = ""; i = ""; j = ""; k = ""; m = "google"; n = ""; o = ""; p = ""; q = ""; s = new LinkedHashMap(); t = new LinkedHashMap(); u = new LinkedHashMap(); w = new ArrayList(); x = new androidx.lifecycle.B(); C = ""; D = ""; E = ""; F = "release"; I = true; P = 40; S = new String[0]; }
    private B() {}
    private static final Unit W0() { return Unit.INSTANCE; } private static final Unit X0() { return Unit.INSTANCE; }
    public static /* synthetic */ Unit a() { return W0(); } public static /* synthetic */ Unit b() { return X0(); }
    public final String A(){return n;} public final void A0(DeviceLoginModel value){Intrinsics.checkNotNullParameter(value,"<set-?>"); c=value;}
    public final String B(){return o;} public final void B0(F1DeviceInfo value){Intrinsics.checkNotNullParameter(value,"<set-?>"); d=value;}
    public final String C(Context context){Intrinsics.checkNotNullParameter(context,"context"); return C;} public final void C0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); C=value;}
    public final String D(Context context){Intrinsics.checkNotNullParameter(context,"context"); return D;} public final void D0(int value){A=value;}
    public final int E(){return A;} public final void E0(int value){P=value;}
    public final OfflineFileModel F(){return v;} public final void F0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); D=value;}
    public final List G(){return w;} public final void G0(int value){y=value;}
    public final boolean H(){return B;} public final void H0(boolean value){B=value;}
    public final String I(){return C;} public final void I0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); E=value;}
    public final String J(){return D;} public final void J0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); F=value;}
    public final int K(){return l2.k.f("IMAGE_ENHANCE_LEVEL",0,2,null);} public final void K0(int value){z=value;}
    public final int L(){return l2.k.e("PERFORMANCE_F22X",-1);} public final void L0(OfflineFileModel value){v=value;}
    public final boolean M(){return l2.k.b("IS_FIRST_USE",false,2,null);} public final void M0(boolean value){G=value;}
    public final String[] N(){return S;} public final void N0(boolean value){H=value;}
    public final Function0 O(){return J;} public final void O0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); h=value;}
    public final Function0 P(){return K;} public final void P0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); i=value;}
    public final boolean Q(){return G;} public final void Q0(Function0 value){Intrinsics.checkNotNullParameter(value,"<set-?>"); J=value;}
    public final String R(){return E;} public final void R0(boolean value){I=value;}
    public final void S(){ if (J != null) J.invoke(); } public final void S0(Function0 value){Intrinsics.checkNotNullParameter(value,"<set-?>"); K=value;}
    public final boolean T(){return l2.k.b("SHOW_TEMP_BAR",false,2,null);} public final void T0(boolean value){L=value;}
    public final boolean U(){return H;} public final void U0(boolean value){M=value;}
    public final boolean V(){return I;} public final void V0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); j=value;}
    public final boolean W(String value){Intrinsics.checkNotNullParameter(value,"serial"); return Arrays.asList(S).contains(value);} public final boolean X(){return L;} public final boolean Y(){return M;} public final boolean Z(){return l2.k.b("TEMP_ALARM_SWITCH",false,2,null);} public final boolean a0(){return l2.k.b("TEMP_ALARM_VIBRATE",false,2,null);} public final androidx.lifecycle.B b0(){return x;} public final String c(){return h;} public final boolean c0(){return N;} public final boolean d(){return l;} public final boolean d0(){return O;} public final String e(){return i;} public final boolean e0(){return l2.k.b("TEMP_ALARM_SOUND",false,2,null);} public final List f(){return e;} public final boolean f0(){return P == 1;} public final String h(){return j;} public final boolean g0(){return Q;} public final String i(){return k;} public final boolean h0(){return Intrinsics.areEqual(h, "ThgStart");} public final String j(){return m;} public final boolean i0(){return l2.k.b("VIEWER_TEMP_BAR_LOCK",false,2,null);} public final DeviceInfoModel k(){return b;} public final Map l(){return s;} public final DeviceLoginModel m(){return c;} public final boolean n(String key){Intrinsics.checkNotNullParameter(key,"key"); return l2.k.b(key,false,2,null);} public final Integer o(String key){Intrinsics.checkNotNullParameter(key,"key"); return l2.k.f(key,0,2,null);} public final Map p(){return t;} public final String q(Context context){Intrinsics.checkNotNullParameter(context,"context"); return E;} public final String r(Context context){Intrinsics.checkNotNullParameter(context,"context"); return F;} public final List s(){return f;} public final List t(){return g;} public final int u(String key){Intrinsics.checkNotNullParameter(key,"key"); return l2.k.f(key,0,2,null);} public final float v(String key){Intrinsics.checkNotNullParameter(key,"key"); return l2.k.d(key,0f,2,null);} public final F1DeviceInfo w(){return d;} public final String x(){return p;} public final int y(){return y;} public final int z(){return z;}
    public final float g(String key){Intrinsics.checkNotNullParameter(key,"key"); return l2.k.d(key,0f,2,null);} public final void j0(String key,float value){Intrinsics.checkNotNullParameter(key,"key"); l2.k.k(key,value);} public final void k0(String key,boolean value){Intrinsics.checkNotNullParameter(key,"key"); l2.k.j(key,value);} public final void l0(String key,int value){Intrinsics.checkNotNullParameter(key,"key"); l2.k.l(key,value);} public final void m0(String key,int value){Intrinsics.checkNotNullParameter(key,"key"); l2.k.l(key,value);} public final void n0(String key,float value){Intrinsics.checkNotNullParameter(key,"key"); l2.k.k(key,value);} public final void o0(int value){A=value;} public final void p0(int value){y=value;} public final void q0(int value){z=value;} public final void r0(boolean value){l=value;} public final void s0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); k=value;} public final void t0(boolean value){N=value;} public final void u0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); m=value;} public final void v0(String value){Intrinsics.checkNotNullParameter(value,"<set-?>"); n=value;} public final void w0(boolean value){O=value;} public final void x0(boolean value){Q=value;} public final void y0(boolean value){R=value;} public final void z0(DeviceInfoModel value){Intrinsics.checkNotNullParameter(value,"<set-?>"); b=value;}
}
