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

    fun readLastCrash(context: Context): JSONObject = readLastCrashFile(crashFile(context))

    fun clearLastCrash(context: Context): JSONObject = clearLastCrashFile(crashFile(context))

    internal fun readLastCrashFile(file: File): JSONObject = readLastCrashFields(file).toJsonObject()

    internal fun readLastCrashFields(file: File): Map<String, Any> {
        if (!file.isFile) {
            return mapOf(
                "present" to false,
                "file_name" to ANDROID_CRASH_LOG_FILE,
                "capture_scope" to "java_kotlin_uncaught_exception_only",
                "native_crash_limit" to NATIVE_CRASH_LIMIT_NOTE,
            )
        }
        val text = runCatching { file.readText() }.getOrElse { readError ->
            "crash_log_read_failed ${readError.javaClass.simpleName}: ${readError.message ?: "no message"}"
        }
        return mapOf(
            "present" to true,
            "file_name" to ANDROID_CRASH_LOG_FILE,
            "path" to file.absolutePath,
            "size_bytes" to file.length(),
            "last_modified_epoch_ms" to file.lastModified(),
            "capture_scope" to "java_kotlin_uncaught_exception_only",
            "native_crash_limit" to NATIVE_CRASH_LIMIT_NOTE,
            "text" to text.take(12_000),
        )
    }

    internal fun clearLastCrashFile(file: File): JSONObject = clearLastCrashFields(file).toJsonObject()

    internal fun clearLastCrashFields(file: File): Map<String, Any> {
        if (file.exists()) file.delete()
        return readLastCrashFields(file)
    }

    private fun writeCrash(context: Context, thread: Thread, error: Throwable) {
        runCatching {
            writeCrashFile(crashFile(context), thread.name, error)
        }
    }

    internal fun writeCrashFile(
        file: File,
        threadName: String,
        error: Throwable,
        timeEpochMs: Long = System.currentTimeMillis(),
    ) {
        val stack = StringWriter().also { writer ->
            PrintWriter(writer).use { printer ->
                printer.println("thread=$threadName")
                printer.println("type=${error.javaClass.name}")
                printer.println("message=${error.message ?: "no message"}")
                printer.println("time_epoch_ms=$timeEpochMs")
                error.printStackTrace(printer)
            }
        }.toString()
        file.parentFile?.mkdirs()
        file.writeText(stack)
    }

    private fun Map<String, Any>.toJsonObject(): JSONObject = JSONObject().also { json ->
        forEach { (key, value) -> json.put(key, value) }
    }

    private fun crashFile(context: Context): File =
        File(context.applicationContext.filesDir, ANDROID_CRASH_LOG_FILE)
}
