package kr.auto.titration.mobile

import java.nio.file.Files
import java.nio.file.Path
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OfficialF2UsbLifecycleReconcilerTest {
    @Test
    fun resumeResetsStaleActiveSessionWhenCurrentUsbDeviceIsMissing() {
        val resets = mutableListOf<String>()
        val reconciler = reconciler(
            snapshot = OfficialF2UsbLifecycleSnapshot(
                activeUserId = 116,
                activeChannel = 0,
                currentDeviceName = null,
                isActiveForCurrentDevice = false,
            ),
            activeDeviceNames = setOf("/dev/bus/usb/001/002"),
            resets = resets,
        )

        val action = reconciler.onResume()

        assertEquals(OfficialF2UsbLifecycleAction.RESET_STALE_ACTIVE_SESSION, action)
        assertEquals(listOf("activity_onResume"), resets)
    }

    @Test
    fun resumeResetsStaleActiveSessionWhenCurrentDeviceDoesNotMatchActiveSession() {
        val resets = mutableListOf<String>()
        val reconciler = reconciler(
            snapshot = OfficialF2UsbLifecycleSnapshot(
                activeUserId = 116,
                activeChannel = 0,
                currentDeviceName = "/dev/bus/usb/001/003",
                isActiveForCurrentDevice = false,
            ),
            activeDeviceNames = setOf("/dev/bus/usb/001/002"),
            resets = resets,
        )

        val action = reconciler.onResume()

        assertEquals(OfficialF2UsbLifecycleAction.RESET_STALE_ACTIVE_SESSION, action)
        assertEquals(listOf("activity_onResume"), resets)
    }

    @Test
    fun resumeDoesNotResetHealthyActiveSessionAndNeverStartsStreams() {
        val resets = mutableListOf<String>()
        var snapshotReads = 0
        val reconciler = OfficialF2UsbLifecycleReconciler(
            snapshot = {
                snapshotReads += 1
                OfficialF2UsbLifecycleSnapshot(
                    activeUserId = 116,
                    activeChannel = 0,
                    currentDeviceName = "/dev/bus/usb/001/002",
                    isActiveForCurrentDevice = true,
                )
            },
            isActiveForDeviceName = { it == "/dev/bus/usb/001/002" },
            resetStaleSession = { resets += it },
        )

        val action = reconciler.onResume()

        assertEquals(OfficialF2UsbLifecycleAction.NONE, action)
        assertEquals(1, snapshotReads)
        assertTrue("passive lifecycle reconciliation must not reset or imply native stream start", resets.isEmpty())
    }

    @Test
    fun detachResetsOnlyWhenTheDetachedDeviceOwnsOrStalesTheActiveSession() {
        val staleResets = mutableListOf<String>()
        val stale = reconciler(
            snapshot = OfficialF2UsbLifecycleSnapshot(
                activeUserId = 116,
                activeChannel = 0,
                currentDeviceName = null,
                isActiveForCurrentDevice = false,
            ),
            activeDeviceNames = setOf("/dev/bus/usb/001/002"),
            resets = staleResets,
        )
        assertEquals(OfficialF2UsbLifecycleAction.RESET_STALE_ACTIVE_SESSION, stale.onUsbDetached("/dev/bus/usb/001/002"))
        assertEquals(listOf("usb_detached"), staleResets)

        val healthyResets = mutableListOf<String>()
        val healthy = reconciler(
            snapshot = OfficialF2UsbLifecycleSnapshot(
                activeUserId = 116,
                activeChannel = 0,
                currentDeviceName = "/dev/bus/usb/001/002",
                isActiveForCurrentDevice = true,
            ),
            activeDeviceNames = setOf("/dev/bus/usb/001/002"),
            resets = healthyResets,
        )
        assertEquals(OfficialF2UsbLifecycleAction.NONE, healthy.onUsbDetached("/dev/bus/usb/001/099"))
        assertTrue(healthyResets.isEmpty())
    }

    @Test
    fun attachResetsMismatchedActiveSessionBeforeNextExplicitStreamAttempt() {
        val resets = mutableListOf<String>()
        val reconciler = reconciler(
            snapshot = OfficialF2UsbLifecycleSnapshot(
                activeUserId = 116,
                activeChannel = 0,
                currentDeviceName = "/dev/bus/usb/001/003",
                isActiveForCurrentDevice = false,
            ),
            activeDeviceNames = setOf("/dev/bus/usb/001/002"),
            resets = resets,
        )

        val action = reconciler.onUsbAttached("/dev/bus/usb/001/003")

        assertEquals(OfficialF2UsbLifecycleAction.RESET_STALE_ACTIVE_SESSION, action)
        assertEquals(listOf("usb_attached"), resets)
    }

    @Test
    fun attachResetsMismatchedActiveSessionEvenBeforeDeviceListRefreshes() {
        val resets = mutableListOf<String>()
        val reconciler = reconciler(
            snapshot = OfficialF2UsbLifecycleSnapshot(
                activeUserId = 116,
                activeChannel = 0,
                currentDeviceName = null,
                isActiveForCurrentDevice = false,
            ),
            activeDeviceNames = setOf("/dev/bus/usb/001/002"),
            resets = resets,
        )

        val action = reconciler.onUsbAttached("/dev/bus/usb/001/003")

        assertEquals(OfficialF2UsbLifecycleAction.RESET_STALE_ACTIVE_SESSION, action)
        assertEquals(listOf("usb_attached"), resets)
    }

    @Test
    fun productionLifecycleReceiverIsRegisteredOnceAndDoesNotCallProbeAttemptRawStream() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/MainActivity.kt")
        val register = functionSlice(source, "private fun registerUsbLifecycleReceiver()", "    private fun unregisterUsbLifecycleReceiver()")
        val attach = functionSlice(source, "private fun reconcileOfficialF2UsbLifecycleAttach", "    private fun reconcileOfficialF2UsbLifecycleDetach")
        val detach = functionSlice(source, "private fun reconcileOfficialF2UsbLifecycleDetach", "    private fun resetOfficialF2SessionForUsbLifecycle")
        val reset = functionSlice(source, "private fun resetOfficialF2SessionForUsbLifecycle", "    private fun requestBluetoothPermissionIfNeeded")

        assertTrue(register.contains("if (usbLifecycleReceiverRegistered) return"))
        assertTrue(register.contains("ACTION_USB_DEVICE_ATTACHED"))
        assertTrue(register.contains("ACTION_USB_DEVICE_DETACHED"))
        assertFalse("attach reconciliation must not start native streaming", attach.contains("attemptRawStream = true"))
        assertFalse("detach reconciliation must not start native streaming", detach.contains("attemptRawStream = true"))
        assertFalse("reset cleanup must not run a probe that starts native streaming", reset.contains("probe("))
        assertTrue(reset.contains("press Mini2 USB 확인 for an explicit stream probe"))
    }

    @Test
    fun officialPreviewHostUsbLifecycleResetClosesSessionAndRebindsSurfaceWithoutDestroyingHost() {
        val source = source("app/src/main/java/kr/auto/titration/mobile/OfficialPreviewHost.kt")
        val reset = functionSlice(source, "fun resetOfficialF2SessionForUsbLifecycle", "    fun destroy()")
        val surfaceDestroyed = functionSlice(source, "override fun surfaceDestroyed", "    private fun retryRebindCallback")

        assertTrue(reset.contains("if (destroyed)"))
        assertTrue(reset.contains("val wasBound = bound"))
        assertTrue(reset.contains("shutdownOfficialPreviewSessionWithRetryRegistration("))
        assertTrue(reset.contains("beforeRetryScheduled"))
        assertTrue(reset.contains("onRetryClosed = retryRebindCallback()"))
        assertTrue(reset.contains("officialPreviewHostCloseAction(result, terminalDestroy = false)"))
        assertTrue(reset.contains("bound = false"))
        assertTrue(reset.contains("maybeBindOfficialPreview()"))
        assertTrue(reset.contains("bound = wasBound"))
        assertFalse("USB lifecycle reset must not mark the host destroyed", reset.contains("destroyed = true"))
        assertFalse("ordinary passive surface loss still must not close native session", surfaceDestroyed.contains("shutdownPreviewSession()"))
    }

    private fun reconciler(
        snapshot: OfficialF2UsbLifecycleSnapshot,
        activeDeviceNames: Set<String>,
        resets: MutableList<String>,
    ): OfficialF2UsbLifecycleReconciler = OfficialF2UsbLifecycleReconciler(
        snapshot = { snapshot },
        isActiveForDeviceName = { it in activeDeviceNames },
        resetStaleSession = { resets += it },
    )

    private fun functionSlice(source: String, startNeedle: String, endNeedle: String): String {
        val start = source.indexOf(startNeedle)
        val end = source.indexOf(endNeedle, start.coerceAtLeast(0))
        assertTrue("missing start needle: $startNeedle", start >= 0)
        assertTrue("missing end needle after $startNeedle: $endNeedle", end > start)
        return source.substring(start, end)
    }

    private fun source(relativePath: String): String {
        var root = Path.of("").toAbsolutePath()
        repeat(5) {
            val candidate = root.resolve(relativePath)
            if (Files.exists(candidate)) return String(Files.readAllBytes(candidate))
            val appCandidate = root.resolve("../").normalize().resolve(relativePath)
            if (Files.exists(appCandidate)) return String(Files.readAllBytes(appCandidate))
            root = root.parent ?: root
        }
        throw java.nio.file.NoSuchFileException(relativePath)
    }
}
