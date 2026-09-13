package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class Mini2RawStreamPostStartStateTest {
    @Test
    fun preTimeoutWaitingStatusIsPreservedWithMachineReadableWaitingState() {
        val status = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "stream_attempt_started",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 0,
        )
        assertEquals("stream_attempt_started", status.rawStreamStatus)
        assertEquals("waiting_for_official_frame_before_bounded_wait", status.postStartState)
        val temperatureFields = status.toJsonTemperatureFieldsForTest()
        assertFalse(temperatureFields.getValue("celsius_allowed") as Boolean)
        assertEquals(null, temperatureFields["temperature_avg_c"])
    }

    @Test
    fun allowedCallbackPacketBeforeOfficialHandoffIsNotClassifiedAsWaiting() {
        val status = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "stream_attempt_started",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 129,
            callbackEntryDetail = "route=jni disposition=dispatched dispatchedCount=129 callbackUserId=116 dwBufSize=203720",
            managerIngressDiagnostic = Mini2ManagerIngressDiagnostic(
                reason = "mailbox_accepted",
                userId = 6,
                packetSize = 203_720,
                streamType = 103,
                frameNumber = 129,
                allowedPacketSizes = setOf(183_496, 203_720),
                streamClosedCount = 0,
                packetSizeNotAllowedCount = 0,
                mailboxAcceptedCount = 129,
                processorAcceptedCount = 0,
                appHandoffCount = 0,
            ),
        )

        assertEquals("stream_attempt_started", status.rawStreamStatus)
        assertEquals(
            "native_start_accepted_callback_packet_observed_official_handoff_missing",
            status.postStartState,
        )
        val temperatureFields = status.toJsonTemperatureFieldsForTest()
        assertFalse(temperatureFields.getValue("celsius_allowed") as Boolean)
        assertEquals(null, temperatureFields["temperature_avg_c"])
        val diagnosticFields = status.toJsonDiagnosticFieldsForTest()
        assertEquals(
            "native callback observed but app frame not published; first_uncompleted_manager_stage=processor",
            diagnosticFields.getValue("reason"),
        )
        assertEquals(
            "mailbox_accepted",
            (diagnosticFields.getValue("manager_ingress_diagnostic") as Map<*, *>)["reason"],
        )
    }

    @Test
    fun appHandoffWithoutPublishedFrameNamesCallbackConsumerPublicationStage() {
        val status = Mini2RawStreamStatus.streamAttemptStarted(
            reason = "stream_attempt_started",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 129,
            callbackEntryDetail =
                "route=jni disposition=dispatched dispatchedCount=129 callbackUserId=6 dwBufSize=203720",
            managerIngressDiagnostic = managerDiagnostic(reason = "app_handoff").copy(
                mailboxAcceptedCount = 129,
                processorAcceptedCount = 129,
                appHandoffCount = 129,
            ),
        )

        assertEquals(
            "native callback observed and app handoff recorded but app frame status was not published; " +
                "first_uncompleted_manager_stage=callback-consumer/publication",
            status.toJsonDiagnosticFieldsForTest()["reason"],
        )
    }

    @Test
    fun boundedTimeoutAfterNativeStartAcceptedAndNoJavaCallbackHasDistinctState() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "bounded wait expired",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0; passive_status_peek stalled_without_frame elapsedMs=30001",
            callbackEntryCount = 0,
            callbackEntryDetail = "no_callback_entry",
            fd = 41,
            userId = 116,
            channel = 0,
        )
        assertEquals("native_start_accepted_no_java_callback_after_bounded_wait", status.postStartState)
        assertEquals(41, status.fd)
        assertEquals(116, status.userId)
        assertEquals(0, status.channel)
    }

    @Test
    fun invalidPacketTimeoutAfterCallbackHasDistinctStateAndPreservesEvidence() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "bounded wait expired",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 2,
            callbackEntryDetail = "route=jni disposition=dispatched dispatchedCount=2 callbackUserId=116 dwBufSize=102944",
            invalidPacketDiagnostic = Mini2InvalidPacketDiagnostic(
                observedPacketSize = 102_944,
                elapsedMs = 40_001,
                allowedPacketSizes = setOf(203_720, 183_496),
                userId = 116,
                channel = 0,
                fd = 41,
                profileClass = "f3.j",
            ),
        )
        val diagnostic = status.invalidPacketDiagnostic ?: error("expected invalid packet diagnostic")

        assertEquals("native_start_accepted_callback_invalid_packet_size_timeout", status.postStartState)
        assertEquals(102_944, diagnostic.observedPacketSize)
        assertEquals(40_001L, diagnostic.elapsedMs)
    }

    @Test
    fun callbackObservedWithoutOfficialHandoffAfterTimeoutHasDistinctState() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "bounded wait expired",
            stageReport = "startStreamPreview resultCode=1 channel=0 streamingNew=true",
            callbackEntryCount = 1,
            callbackEntryDetail = "route=jni disposition=dispatched dispatchedCount=1 callbackUserId=116 dwBufSize=203720",
            fd = 41,
            userId = 116,
            channel = 0,
        )

        assertEquals(
            "native_start_accepted_callback_packet_observed_official_handoff_missing",
            status.postStartState,
        )
    }

    @Test
    fun rejectedCallbackEntryNeverProducesPacketObservedState() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "bounded wait expired",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 129,
            callbackEntryDetail =
                "route=jni disposition=rejected dropReason=declared_length_exceeds_available_bytes rejectedCount=129",
        )

        assertEquals("native_start_accepted_no_java_callback_after_bounded_wait", status.postStartState)
    }

    @Test
    fun dispatchedCallbackRejectedByClosedManagerReportsFirstUncompletedStageAndNoCelsius() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "stalled without frame callback",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 129,
            callbackEntryDetail = "route=jni disposition=dispatched dispatchedCount=129 callbackUserId=6 dwBufSize=203720",
            managerIngressDiagnostic = managerDiagnostic(reason = "stream_closed"),
        )

        val fields = status.toJsonDiagnosticFieldsForTest()
        assertEquals(
            "native callback observed but manager ingress rejected it; first_uncompleted_manager_stage=stream_closed",
            fields["reason"],
        )
        val ingress = fields["manager_ingress_diagnostic"] as Map<*, *>
        assertEquals(false, ingress["celsius_allowed"])
        assertEquals(false, ingress["full_matrix_celsius_allowed"])
    }

    @Test
    fun dispatchedWrongProfilePacketReportsSizeGateAsFirstUncompletedStage() {
        val status = Mini2RawStreamStatus(
            rawStreamStatus = "blocked_native_stream",
            reason = "stalled without frame callback",
            stageReport = "USB_StartStreamCallback=ok channel=0 lastError=0",
            callbackEntryCount = 1,
            callbackEntryDetail = "route=jni disposition=dispatched dispatchedCount=1 callbackUserId=6 dwBufSize=101320",
            managerIngressDiagnostic = managerDiagnostic(reason = "packet_size_not_allowed"),
        )

        assertEquals(
            "native callback observed but manager ingress rejected it; first_uncompleted_manager_stage=packet_size_not_allowed",
            status.toJsonDiagnosticFieldsForTest()["reason"],
        )
    }

    private fun managerDiagnostic(reason: String) = Mini2ManagerIngressDiagnostic(
        reason = reason,
        userId = 6,
        packetSize = 203_720,
        streamType = 103,
        frameNumber = 129,
        allowedPacketSizes = setOf(183_496, 203_720),
        streamClosedCount = if (reason == "stream_closed") 129 else 0,
        packetSizeNotAllowedCount = if (reason == "packet_size_not_allowed") 1 else 0,
        mailboxAcceptedCount = 0,
        processorAcceptedCount = 0,
        appHandoffCount = 0,
    )
}
