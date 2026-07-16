package d2;

import android.annotation.SuppressLint;
import android.content.Context;
import kotlin.jvm.internal.Intrinsics;

public final class a {
    public static final d2.a a;

    @SuppressLint("StaticFieldLeak")
    private static Context b;

    static {
        a = new d2.a();
    }

    private a() {
    }

    public static final Context a() {
        Context v0 = b;
        if (v0 == null) {
            Intrinsics.throwUninitializedPropertyAccessException("appContext");
            v0 = null;
        }
        return v0;
    }

    public static final void b(Context context) {
        Intrinsics.checkNotNullParameter(context, "context");
        Context applicationContext = context.getApplicationContext();
        Intrinsics.checkNotNullExpressionValue(applicationContext, "context.applicationContext");
        b = applicationContext;
    }
}
