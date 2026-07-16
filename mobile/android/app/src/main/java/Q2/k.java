package Q2;

import android.graphics.RectF;
import kotlin.jvm.internal.Intrinsics;

public final class k {
    private float a;
    private RectF b;
    private int c;
    private boolean d;
    private boolean e;

    public k(float ratio, RectF rectF, int colorData, boolean selected, boolean canMove) {
        Intrinsics.checkNotNullParameter(rectF, "rectF");
        this.a = ratio;
        this.b = rectF;
        this.c = colorData;
        this.d = selected;
        this.e = canMove;
    }

    public final boolean a() { return e; }
    public final int b() { return c; }
    public final float c() { return a; }
    public final RectF d() { return b; }
    public final boolean e() { return d; }
    public final void f(int colorData) { this.c = colorData; }
    public final void g(float ratio) { this.a = ratio; }
    public final void h(RectF rectF) { Intrinsics.checkNotNullParameter(rectF, "<set-?>"); this.b = rectF; }
    public final void i(boolean selected) { this.d = selected; }

    @Override
    public boolean equals(Object other) {
        if (this == other) return true;
        if (!(other instanceof k)) return false;
        k that = (k) other;
        return Float.compare(this.a, that.a) == 0
                && Intrinsics.areEqual(this.b, that.b)
                && this.c == that.c
                && this.d == that.d
                && this.e == that.e;
    }

    @Override
    public int hashCode() {
        int result = Float.hashCode(a);
        result = 31 * result + b.hashCode();
        result = 31 * result + Integer.hashCode(c);
        result = 31 * result + Boolean.hashCode(d);
        result = 31 * result + Boolean.hashCode(e);
        return result;
    }

    @Override
    public String toString() {
        return "ColorfulMoveBean(ratio=" + a + ", rectF=" + b + ", colorData=" + c
                + ", selected=" + d + ", canMove=" + e + ')';
    }
}
