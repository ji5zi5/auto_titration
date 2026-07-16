package kr.auto.titration.mobile.thermal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class F1FrameSafetyTest {
    @Test
    fun unknownPayloadIsRejectedWithoutPreviewOrRawEvidence() {
        val evidence = F1FrameSafety.validateCallbackPayload(
            bytes = ByteArray(64) { it.toByte() },
            width = 120,
            height = 160,
            yuvType = 99,
        )

        assertNull(evidence.previewPlane)
        assertNull(evidence.rawValues)
        assertTrue(evidence.rejectionReason.startsWith("unknown_f1_payload_format"))
    }

    @Test
    fun jpegPreviewRequiresExplicitDimensionsAndJpegBoundaryMarkers() {
        val jpeg = byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0x01, 0x02, 0xff.toByte(), 0xd9.toByte())
        val accepted = F1FrameSafety.validateCallbackPayload(jpeg, width = 120, height = 160, yuvType = 1)
        val rejectedWithoutDimensions = F1FrameSafety.validateCallbackPayload(jpeg, width = 0, height = 160, yuvType = 1)

        assertEquals("jpeg", accepted.previewPlane?.format)
        assertEquals(120, accepted.previewPlane?.width)
        assertNull("dimensionless callback is not a proven preview plane", rejectedWithoutDimensions.previewPlane)
        assertNull(accepted.rawValues)
    }

    @Test
    fun f1CleanupPlanDisablesPreviewThenDetachesWithoutF2Claims() {
        val commands = F1FrameSafety.officialCleanupCommands

        assertEquals(listOf(5, 14), commands.map { it.msgType })
        assertEquals(0, commands.first().enable)
        assertEquals("USB_SetPreviewEnable(false)", commands.first().name)
        assertEquals("USB_SetDevDetach", commands.last().name)
        assertFalse(commands.joinToString { it.name }.contains("F2", ignoreCase = true))
    }
}
