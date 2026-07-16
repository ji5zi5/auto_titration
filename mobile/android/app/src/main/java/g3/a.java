package g3;

import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import kotlin.jvm.functions.Function1;
import kotlin.jvm.functions.Function5;

public abstract class a {
    private Function1 a;
    private Function1 b;
    private Function1 c;
    private Function5 d;
    private Function1 e;

    public abstract PreviewStreamInfo d(byte[] frameInfoData);

    protected final Function1 e() { return this.a; }
    protected final Function1 f() { return this.b; }
    protected final Function1 g() { return this.e; }
    protected final Function5 h() { return this.d; }
    protected final Function1 i() { return this.c; }

    public final void j(Function1 callback1, Function1 callback2, Function1 callback3, Function5 callback4, Function1 callback5) {
        this.a = callback1;
        this.b = callback2;
        this.c = callback3;
        this.d = callback4;
        this.e = callback5;
    }

    public final void k() {
        this.a = null;
        this.b = null;
        this.c = null;
        this.d = null;
        this.e = null;
    }
}
