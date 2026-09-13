package com.hik.f2module

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class F2UsbModuleApiLifecycleTest {
    @Test
    fun replacementStopFailurePreservesNoActiveAndDiagnosticContracts() {
        val failedStop = F2StageResult(false, "USB_StopChannel=attempted ok=false error=84")

        assertNull(
            "channel -1 stop failure must preserve the existing start path",
            replacementStartBlockedResult(
                activeChannelBeforeStop = -1,
                stopResult = failedStop,
                startPath = "official_interface_wrapper",
                stageReport = "before-stop",
                profileResolution = null,
            ),
        )

        val blocked = replacementStartBlockedResult(
            activeChannelBeforeStop = 7,
            stopResult = failedStop,
            startPath = "official_interface_wrapper",
            stageReport = "before-stop",
            profileResolution = null,
        ) ?: error("active replacement must be blocked when stop fails")

        assertFalse(blocked.ok)
        assertEquals(7, blocked.channel)
        assertTrue(blocked.stageReport.contains("USB_StartStreamCallback=not_run"))
        assertEquals("blocked_existing_channel_stop_failed", blocked.attemptDiagnostics.single().startStatus)
        assertEquals("official_interface_wrapper", blocked.attemptDiagnostics.single().startPath)
    }

    @Test
    fun appCallbackIsPreparedBeforeNativeStartAndRolledBackWhenStartFails() {
        val source = apiSource()
        val appStart = extractFunctionSource(source, "startStreamPreview")
        val stopTransition = extractFunctionSource(source, "stopForTransition")
        val nativeStartTransition = extractFunctionSource(source, "startNativeStreamPreviewLocked")

        val invalidate = stopTransition.indexOf("PreviewManagerIIAppBinding.suspendForUsbTransition(bindingManager)")
        val nativeStop = stopTransition.indexOf("helper.stopStreamPreview(context, streamingNew)")
        assertTrue("the prior app generation must be invalidated before native stop", invalidate in 0 until nativeStop)
        assertFalse(
            "a reversible stop must preserve the renderer/surface instead of performing full unbind",
            stopTransition.contains("PreviewManagerIIAppBinding.unbind(bindingManager)"),
        )

        val nativeStart = appStart.indexOf("startNativeStreamPreviewLocked")
        val rejectFailedStart = appStart.indexOf("if (!result.ok)")
        val activateNew = appStart.indexOf("PreviewManagerIIAppBinding.bind(previewManager, callback)")
        val resetDiagnostics = nativeStartTransition.indexOf("resetStreamCallbackEntryDiagnostics()")
        val validateCallback = nativeStartTransition.indexOf("val fStreamCallBack = streamCallback.getFStreamCallBack()")
        val invokeNativeStart = nativeStartTransition.indexOf("helper.startStreamPreview(")
        assertTrue(
            "the app callback generation must exist before native start so synchronous first frames are not lost",
            activateNew in 0 until nativeStart,
        )
        assertTrue(
            "existing callback evidence must survive all pre-native callback validation failures",
            resetDiagnostics > validateCallback && resetDiagnostics < invokeNativeStart,
        )
        assertTrue(
            "all provisional start work must be exception-transactional",
                appStart.contains("runF2StartTransition(") &&
                activateNew > appStart.indexOf("runF2StartTransition(") &&
                source.contains("catch (error: RuntimeException)") &&
                source.contains("catch (error: LinkageError)"),
        )
        assertTrue("native start failure must be handled after the pre-bound callback generation", rejectFailedStart > nativeStart)
        assertTrue(
            "failed native start must roll back the prepared generation without destroying the renderer",
            appStart.substring(rejectFailedStart)
                .contains("rollbackPreparedAppStart(previewManager)") &&
                extractFunctionSource(source, "rollbackPreparedAppStart")
                    .contains("PreviewManagerIIAppBinding.suspendForUsbTransition(previewManager)"),
        )
        assertFalse(
            "failed native start must not leave the host falsely bound to a destroyed renderer",
            appStart.substring(rejectFailedStart)
                .contains("previewManager.closePreviewCallback()"),
        )
    }

    @Test
    fun thrownStartTransitionRollsBackExactlyOnceAndRethrowsTheOriginalFailure() {
        val runtimeFailure = IllegalStateException("runtime start failure")
        var runtimeRollbackCount = 0
        val observedRuntime = assertThrows(IllegalStateException::class.java) {
            runF2StartTransition(
                rollback = { runtimeRollbackCount += 1 },
                start = { throw runtimeFailure },
            )
        }
        assertSame(runtimeFailure, observedRuntime)
        assertEquals(1, runtimeRollbackCount)

        val linkageFailure = UnsatisfiedLinkError("native symbol failure")
        var linkageRollbackCount = 0
        val observedLinkage = assertThrows(UnsatisfiedLinkError::class.java) {
            runF2StartTransition(
                rollback = { linkageRollbackCount += 1 },
                start = { throw linkageFailure },
            )
        }
        assertSame(linkageFailure, observedLinkage)
        assertEquals(1, linkageRollbackCount)

        var successRollbackCount = 0
        assertEquals(
            "started",
            runF2StartTransition(
                rollback = { successRollbackCount += 1 },
                start = { "started" },
            ),
        )
        assertEquals(0, successRollbackCount)

        val rollbackFailure = IllegalArgumentException("rollback failure")
        val originalFailure = IllegalStateException("original failure")
        val observedOriginal = assertThrows(IllegalStateException::class.java) {
            runF2StartTransition(
                rollback = { throw rollbackFailure },
                start = { throw originalFailure },
            )
        }
        assertSame(originalFailure, observedOriginal)
        assertEquals(listOf(rollbackFailure), observedOriginal.suppressed.toList())
    }

    @Test
    fun usbSessionTransitionsInvalidateMeasurementsAndRestoreOnlyThePriorBindingOnFailedActiveStop() {
        val source = apiSource()
        val open = extractFunctionSource(source, "openUsbModule")
        val stopTransition = extractFunctionSource(source, "stopForTransition")
        val exceptionalRestore = extractFunctionSource(source, "restorePriorAppBindingIfSessionUnchanged")

        assertTrue(
            "USB reopen must invalidate in-flight official measurements before helper session mutation",
            open.indexOf("OfficialF2MeasurementCoordinator.resetLifecycle()") in
                0 until open.indexOf("helper.openUsbDevice"),
        )
        assertTrue(
            "a failed reopen must restore the prior app binding only while the exact native session is still active",
            exceptionalRestore.contains("helper.activeUserId() != previousUserId") &&
                exceptionalRestore.contains("helper.activeChannel() != previousChannel") &&
                open.contains("restorePriorAppBindingIfSessionUnchanged("),
        )
        assertTrue(
            "USB reopen preparation and helper open calls must share one exception rollback boundary",
            open.indexOf("runF2StartTransition(") in
                0 until open.indexOf("OfficialF2MeasurementCoordinator.resetLifecycle()"),
        )
        val measurementReset = stopTransition.indexOf("OfficialF2MeasurementCoordinator.resetLifecycle()")
        val nativeStop = stopTransition.indexOf("helper.stopStreamPreview(context, streamingNew)")
        assertTrue("active stop must invalidate measurements before native stop", measurementReset in 0 until nativeStop)
        assertTrue(
            "channel -1 remains excluded from active-session measurement invalidation",
            stopTransition.substringBefore("OfficialF2MeasurementCoordinator.resetLifecycle()")
                .contains("activeChannelBeforeStop != -1"),
        )
        assertTrue(
            "stop preparation, measurement reset, and native stop must share one exception rollback boundary",
            stopTransition.indexOf("runF2StartTransition(") in
                0 until stopTransition.indexOf("PreviewManagerIIAppBinding.suspendForUsbTransition(bindingManager)"),
        )
        assertTrue(
            "a failed active stop restores only when the exact prior native session still owns the channel",
            stopTransition.contains("restorePriorAppBindingIfSessionUnchanged(") &&
                stopTransition.contains("activeUserIdBeforeStop") &&
                stopTransition.contains("activeChannelBeforeStop"),
        )
        assertTrue(
            "reversible stop suspension must retain the exact processor instead of destroying it",
            source(
                "app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java",
                "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/PreviewManagerIIAppBinding.java",
            ).contains("current.suspendF2PublicationForUsbTransition()"),
        )
        assertFalse(
            "failed stop rollback must not reconstruct a processor from mutable profile state",
            stopTransition.contains("refreshF2ProcessorFromRuntimeProfile()"),
        )
        val restoreTimeout = stopTransition.indexOf("restorePriorAppBindingIfSessionUnchanged(")
        assertTrue("the exact prior owner must be restored on failed stop", restoreTimeout >= 0)
        assertTrue(
            "the restoration helper must bind the prior callback",
            extractFunctionSource(source, "restorePriorAppBinding")
                .contains("PreviewManagerIIAppBinding.bind(previewManager, callback)"),
        )
        assertFalse(
            "the requested replacement callback must never be classified as active after failed stop",
            stopTransition.contains("PreviewManagerIIAppBinding.bind(bindingManager, callback)"),
        )
    }

    @Test
    fun terminalCloseIsApiOwnedSoNativeAndAppCallbackStateCannotDiverge() {
        val api = apiSource()
        val closeSession = extractFunctionSource(api, "closeSession")
        val stream = source(
            "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt",
            "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt",
        )
        val shutdown = extractFunctionSource(stream, "shutdownOfficialPreviewSession")

        assertTrue(closeSession.contains("OfficialF2MeasurementCoordinator.resetLifecycle()"))
        val suspendBinding =
            closeSession.indexOf("PreviewManagerIIAppBinding.suspendForUsbTransition(bindingManager)")
        val nativeClose = closeSession.indexOf("helper.closeSession()")
        val commitUnbind = closeSession.indexOf("PreviewManagerIIAppBinding.unbind(bindingManager)")
        assertTrue(
            "terminal close must suspend app publication before native close without forgetting ownership",
            suspendBinding in 0 until nativeClose,
        )
        assertTrue(
            "terminal app teardown may commit only after native close returns",
            commitUnbind > nativeClose,
        )
        assertFalse(
            "the API owner must not be cleared before native close can fail",
            closeSession.substring(0, nativeClose).contains("activeAppCallback = null"),
        )
        assertTrue(closeSession.contains("F2SessionCloseOutcome.STREAM_PRESERVED"))
        assertTrue(closeSession.contains("restorePriorAppBinding("))
        assertTrue(closeSession.contains("retainManagerForTerminalCloseRetry"))
        assertTrue(closeSession.contains("releaseManagerFromTerminalCloseRetry"))
        assertTrue(closeSession.contains("PreviewManagerIIAppBinding.unbind(bindingManager)"))
        assertTrue(closeSession.contains("helper.closeSession()"))
        assertTrue(shutdown.contains("f2Api.closeSession()"))
        assertFalse(shutdown.contains("f2Helper.closeSession()"))
        assertTrue(
            "stream-owned renderer teardown must happen only after the API native close result",
            shutdown.indexOf("f2Api.closeSession()") < shutdown.indexOf("closeBoundOfficialPreviewLocked()"),
        )
        assertTrue(
            shutdown.contains(
                "if (closeResult.closeOutcome == F2SessionCloseOutcome.STREAM_PRESERVED)",
            ),
        )
        assertTrue(shutdown.contains("return closeResult"))
    }

    @Test
    fun freshOpenCleanupIsFacadeOwnedAndPreservedStreamBlocksOpenWithExactOwnerRetained() {
        val api = apiSource()
        val freshOpenClose = extractFunctionSource(api, "closeSessionForFreshOpen")
        val stream = source(
            "app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt",
            "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/HikmicroJnaMini2Stream.kt",
        )
        val ensure = extractFunctionSource(stream, "ensureStreamingLocked")
        val cleanup = extractFunctionSource(stream, "closeSessionForFreshOpenOrBlocked")

        assertTrue(freshOpenClose.contains("val result = closeSession()"))
        assertTrue(freshOpenClose.contains("F2SessionCloseOutcome.STREAM_PRESERVED"))
        assertFalse(
            "the app adapter must never mutate native lifecycle state through the helper",
            stream.contains("f2Helper.closeSession()"),
        )
        for (reason in listOf("stale_frame", "explicit_retry", "pre_open_cleanup")) {
            assertTrue("missing facade cleanup for $reason", ensure.contains("reason = \"$reason\""))
        }
        assertTrue(cleanup.contains("f2Api.closeSessionForFreshOpen(reason)"))
        assertTrue(cleanup.contains("closeResult.closeOutcome != F2SessionCloseOutcome.STREAM_PRESERVED"))
        assertTrue(cleanup.contains("exact prior binding ownership retained"))
        assertTrue(
            "each fresh-open cleanup must return its blocked status before open can run",
            ensure.indexOf("closeSessionForFreshOpenOrBlocked(\n                route = route,\n                reason = \"pre_open_cleanup\"") <
                ensure.indexOf("f2Api.openUsbModule("),
        )
        assertTrue(ensure.contains("closeSessionForFreshOpenOrBlocked("))
        assertTrue(ensure.contains("?.let { return it }"))
        assertTrue(
            "exception cleanup must also remain behind the lifecycle facade",
            ensure.contains("val closeResult = f2Api.closeSession()"),
        )
    }

    private fun apiSource(): String {
        return source(
            "app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
            "mobile/android/app/src/main/java/com/hik/f2module/F2UsbModuleApi.kt",
        )
    }

    private fun source(vararg relativePaths: String): String {
        val roots = generateSequence(java.io.File(System.getProperty("user.dir"))) { it.parentFile }
            .take(8)
            .toList()
        for (root in roots) {
            for (relativePath in relativePaths) {
                val file = java.io.File(root, relativePath)
                if (file.isFile) return file.readText()
            }
        }
        error("Unable to locate any of ${relativePaths.toList()}")
    }

    private fun extractFunctionSource(source: String, functionName: String): String {
        val start = source.indexOf("fun $functionName(")
        require(start >= 0) { "Function $functionName not found" }
        val bodyStart = source.indexOf('{', start)
        require(bodyStart >= 0) { "Function $functionName body not found" }
        var depth = 0
        for (index in bodyStart until source.length) {
            when (source[index]) {
                '{' -> depth += 1
                '}' -> {
                    depth -= 1
                    if (depth == 0) return source.substring(start, index + 1)
                }
            }
        }
        error("Function $functionName body did not close")
    }
}
