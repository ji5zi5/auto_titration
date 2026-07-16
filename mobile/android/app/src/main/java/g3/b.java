package g3;

public final class b {
    public static final b a = new b();

    private b() {}

    public final g3.a a(int moduleId, boolean streamingNew) {
        i3.b streamInfoDeal = new i3.b();
        switch (moduleId) {
            case 8: return new g3.f(streamInfoDeal);
            case 9: return new g3.g(streamInfoDeal);
            case 11: return new g3.c(streamInfoDeal);
            case 12: return streamingNew ? new g3.e(streamInfoDeal) : new g3.d(streamInfoDeal);
            case 10:
            default: return new g3.g(streamInfoDeal);
        }
    }
}
