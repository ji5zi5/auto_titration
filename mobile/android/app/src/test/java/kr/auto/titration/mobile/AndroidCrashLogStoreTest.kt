package kr.auto.titration.mobile

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class AndroidCrashLogStoreTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun absentCrashReportIsExplicitAboutCaptureScopeAndNativeCrashLimit() {
        val file = crashFile()

        val report = AndroidCrashLogStore.readLastCrashFields(file)

        assertFalse(report["present"] as Boolean)
        assertEquals("last-crash.txt", report["file_name"])
        assertEquals("java_kotlin_uncaught_exception_only", report["capture_scope"])
        assertTrue((report["native_crash_limit"] as String).contains("native SIGSEGV/process crashes"))
        assertFalse("absent reports should not invent a text field", report.containsKey("text"))
    }

    @Test
    fun writeThenReadPersistsCrashMetadataAndStackWithoutClaimingNativeCapture() {
        val file = crashFile()
        val error = IllegalStateException("boom")

        AndroidCrashLogStore.writeCrashFile(
            file = file,
            threadName = "worker-1",
            error = error,
            timeEpochMs = 123_456L,
        )
        val report = AndroidCrashLogStore.readLastCrashFields(file)

        assertTrue(report["present"] as Boolean)
        assertEquals("last-crash.txt", report["file_name"])
        assertEquals(file.absolutePath, report["path"])
        assertEquals(file.length(), report["size_bytes"])
        assertEquals(file.lastModified(), report["last_modified_epoch_ms"])
        assertEquals("java_kotlin_uncaught_exception_only", report["capture_scope"])
        assertTrue((report["native_crash_limit"] as String).contains("may not be recoverable in-app"))

        val text = report["text"] as String
        assertTrue(text.contains("thread=worker-1"))
        assertTrue(text.contains("type=java.lang.IllegalStateException"))
        assertTrue(text.contains("message=boom"))
        assertTrue(text.contains("time_epoch_ms=123456"))
        assertTrue(text.contains("java.lang.IllegalStateException: boom"))
    }

    @Test
    fun clearRemovesExistingCrashAndReturnsAbsentReport() {
        val file = crashFile().apply { writeText("previous crash") }
        assertTrue(file.exists())

        val report = AndroidCrashLogStore.clearLastCrashFields(file)

        assertFalse(file.exists())
        assertFalse(report["present"] as Boolean)
        assertEquals("java_kotlin_uncaught_exception_only", report["capture_scope"])
        assertTrue((report["native_crash_limit"] as String).contains("logcat"))
    }

    @Test
    fun readTruncatesDisplayedCrashTextButKeepsActualSize() {
        val file = crashFile()
        val prefix = "important-prefix\n"
        val hiddenSuffix = "hidden-after-limit"
        file.writeText(prefix + "x".repeat(12_500) + hiddenSuffix)

        val report = AndroidCrashLogStore.readLastCrashFields(file)

        assertTrue(report["present"] as Boolean)
        assertEquals(file.length(), report["size_bytes"])
        val text = report["text"] as String
        assertEquals(12_000, text.length)
        assertTrue(text.startsWith(prefix))
        assertFalse(text.contains(hiddenSuffix))
    }

    private fun crashFile(): File = temporaryFolder.newFolder("crash-store").resolve("last-crash.txt")
}
