package kr.auto.titration.mobile.thermal;

import com.hik.viewercommon.data.bean.PreviewInfoDataBean;
import com.hik.viewercommon.data.bean.PreviewStreamInfo;
import kr.auto.titration.mobile.thermal.officialdex.radiometric.OfficialF2PaletteSnapshot;

public final class OfficialProcessedF2Frame {
    public enum RendererTimestampProvenance {
        NONE,
        EXACT,
        NEAREST
    }

    public final long frameCounter;
    public final int packetSize;
    public final int width;
    public final int height;
    public final PreviewStreamInfo previewStreamInfo;
    public final boolean isOffStreamInfo;
    public final String processorBucket;
    public final long lifecycleGeneration;
    public final int processedFrameNumStamp;
    public final OfficialF2PaletteSnapshot paletteSnapshot;
    public final String paletteSnapshotSource;
    public final PreviewInfoDataBean offlinePreviewInfoData;
    public final int offlineFrameNumStamp;
    public final byte[] rendererJpegData;
    public final String rendererJpegSource;
    public final int rendererJpegWidth;
    public final int rendererJpegHeight;
    public final int rendererSelectedFrameNumStamp;
    public final RendererTimestampProvenance rendererTimestampProvenance;

    public OfficialProcessedF2Frame(long frameCounter, int packetSize, int width, int height,
                                    PreviewStreamInfo previewStreamInfo, boolean isOffStreamInfo,
                                    String processorBucket) {
        this(frameCounter, packetSize, width, height, previewStreamInfo, isOffStreamInfo,
                processorBucket, -1L, -1, null, "palette_snapshot_unavailable",
                null, -1, null, null, 0, 0, -1, RendererTimestampProvenance.NONE);
    }

    public OfficialProcessedF2Frame(long frameCounter, int packetSize, int width, int height,
                                    PreviewStreamInfo previewStreamInfo, boolean isOffStreamInfo,
                                    String processorBucket, long lifecycleGeneration,
                                    int processedFrameNumStamp,
                                    OfficialF2PaletteSnapshot paletteSnapshot,
                                    String paletteSnapshotSource,
                                    PreviewInfoDataBean offlinePreviewInfoData,
                                    int offlineFrameNumStamp, byte[] rendererJpegData,
                                    String rendererJpegSource, int rendererJpegWidth,
                                    int rendererJpegHeight, int rendererSelectedFrameNumStamp,
                                    RendererTimestampProvenance rendererTimestampProvenance) {
        this.frameCounter = frameCounter;
        this.packetSize = packetSize;
        this.width = width;
        this.height = height;
        this.previewStreamInfo = previewStreamInfo;
        this.isOffStreamInfo = isOffStreamInfo;
        this.processorBucket = processorBucket;
        this.lifecycleGeneration = lifecycleGeneration;
        this.processedFrameNumStamp = processedFrameNumStamp;
        this.paletteSnapshot = paletteSnapshot;
        this.paletteSnapshotSource = paletteSnapshotSource;
        this.offlinePreviewInfoData = offlinePreviewInfoData;
        this.offlineFrameNumStamp = offlineFrameNumStamp;
        this.rendererJpegData = copy(rendererJpegData);
        this.rendererJpegSource = rendererJpegSource;
        this.rendererJpegWidth = rendererJpegWidth;
        this.rendererJpegHeight = rendererJpegHeight;
        this.rendererSelectedFrameNumStamp = rendererSelectedFrameNumStamp;
        this.rendererTimestampProvenance = rendererTimestampProvenance == null
                ? RendererTimestampProvenance.NONE
                : rendererTimestampProvenance;
    }

    public OfficialProcessedF2Frame withOfflineCapture(PreviewInfoDataBean offlinePreviewInfoData,
                                                       int offlineFrameNumStamp,
                                                       byte[] rendererJpegData,
                                                       String rendererJpegSource,
                                                       int rendererJpegWidth,
                                                       int rendererJpegHeight,
                                                       int rendererSelectedFrameNumStamp,
                                                       RendererTimestampProvenance rendererTimestampProvenance) {
        return new OfficialProcessedF2Frame(
                frameCounter,
                packetSize,
                width,
                height,
                previewStreamInfo,
                isOffStreamInfo,
                processorBucket,
                lifecycleGeneration,
                processedFrameNumStamp,
                paletteSnapshot,
                paletteSnapshotSource,
                offlinePreviewInfoData,
                offlineFrameNumStamp,
                rendererJpegData,
                rendererJpegSource,
                rendererJpegWidth,
                rendererJpegHeight,
                rendererSelectedFrameNumStamp,
                rendererTimestampProvenance);
    }

    private static byte[] copy(byte[] value) {
        if (value == null || value.length == 0) return value == null ? null : new byte[0];
        byte[] copy = new byte[value.length];
        System.arraycopy(value, 0, copy, 0, value.length);
        return copy;
    }
}
