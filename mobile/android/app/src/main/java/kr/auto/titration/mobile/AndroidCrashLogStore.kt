package kr.auto.titration.mobile

import android.content.Context
import android.os.Process
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import kotlin.system.exitProcess
import org.json.JSONObject

private const val ANDROID_CRASH_LOG_FILE = "last-crash.txt"
private const val NATIVE_CRASH_LIMIT_NOTE =
    "Java/Kotlin uncaught exceptions are saved here; native SIGSEGV/process crashes may require Android system logs/logcat and may not be recoverable in-app."

/**
 * Stores the last Java/Kotlin uncaught exception so the next app launch can
 * expose it through the WebView. Native SIGSEGV-style crashes cannot be caught
 * here, so Mini2 native stream calls must still stay manually gated.
 */
object AndroidCrashLogStore {
    @Volatile
    private var installed = false

    fun install(context: Context) {
        if (installed) return
        synchronized(this) {
            if (installed) return
            val appContext = context.applicationContext
            val previous = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler { thread, error ->
                writeCrash(appContext, thread, error)
                if (previous != null) {
                    previous.uncaughtException(thread, error)
                } else {
                    Process.killProcess(Process.myPid())
                    exitProcess(10)
                }
            }
            installed = true
        }
    }

    fun readLastCrash(context: Context): JSONObject {
        val file = crashFile(context)
        if (!file.isFile) {
            return JSONObject()
                .put("present", false)
                .put("file_name", ANDROID_CRASH_LOG_FILE)
                .put("capture_scope", "java_kotlin_uncaught_exception_only")
                .put("native_crash_limit", NATIVE_CRASH_LIMIT_NOTE)
        }
        val text = runCatching { file.readText() }.getOrElse { readError ->
            "crash_log_read_failed ${readError.javaClass.simpleName}: ${readError.message ?: "no message"}"
        }
        return JSONObject()
            .put("present", true)
            .put("file_name", ANDROID_CRASH_LOG_FILE)
            .put("path", file.absolutePath)
            .put("size_bytes", file.length())
            .put("last_modified_epoch_ms", file.lastModified())
            .put("capture_scope", "java_kotlin_uncaught_exception_only")
            .put("native_crash_limit", NATIVE_CRASH_LIMIT_NOTE)
            .put("text", text.take(12_000))
    }

    fun clearLastCrash(context: Context): JSONObject {
        val file = crashFile(context)
        if (file.exists()) file.delete()
        return readLastCrash(context)
    }

    private fun writeCrash(context: Context, thread: Thread, error: Throwable) {
        runCatching {
            val stack = StringWriter().also { writer ->
                PrintWriter(writer).use { printer ->
                    printer.println("thread=${thread.name}")
                    printer.println("type=${error.javaClass.name}")
                    printer.println("message=${error.message ?: "no message"}")
                    printer.println("time_epoch_ms=${System.currentTimeMillis()}")
                    error.printStackTrace(printer)
                }
            }.toString()
            crashFile(context).writeText(stack)
        }
    }

    private fun crashFile(context: Context): File =
        File(context.applicationContext.filesDir, ANDROID_CRASH_LOG_FILE)
}
