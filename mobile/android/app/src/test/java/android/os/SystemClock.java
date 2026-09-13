package android.os;

import java.time.Clock;

/** Host implementation for local JVM tests that execute Android elapsed-time calls. */
public final class SystemClock {
    private SystemClock() {}

    public static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    public static boolean setCurrentTimeMillis(long millis) {
        return false;
    }

    public static long uptimeMillis() {
        return elapsedRealtime();
    }

    public static long uptimeNanos() {
        return elapsedRealtimeNanos();
    }

    public static long elapsedRealtime() {
        return System.nanoTime() / 1_000_000L;
    }

    public static long elapsedRealtimeNanos() {
        return System.nanoTime();
    }

    public static long currentThreadTimeMillis() {
        return 0L;
    }

    public static Clock currentNetworkTimeClock() {
        return Clock.systemUTC();
    }

    public static Clock currentGnssTimeClock() {
        return Clock.systemUTC();
    }
}
