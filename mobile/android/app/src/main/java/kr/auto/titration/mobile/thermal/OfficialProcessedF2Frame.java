package kr.auto.titration.mobile.thermal;

import com.hik.viewercommon.data.bean.PreviewStreamInfo;

public final class OfficialProcessedF2Frame {
    public final long frameCounter;
    public final int packetSize;
    public final int width;
    public final int height;
    public final PreviewStreamInfo previewStreamInfo;
    public final boolean isOffStreamInfo;
    public final String processorBucket;

    public OfficialProcessedF2Frame(long frameCounter, int packetSize, int width, int height,
                                    PreviewStreamInfo previewStreamInfo, boolean isOffStreamInfo,
                                    String processorBucket) {
        this.frameCounter = frameCounter;
        this.packetSize = packetSize;
        this.width = width;
        this.height = height;
        this.previewStreamInfo = previewStreamInfo;
        this.isOffStreamInfo = isOffStreamInfo;
        this.processorBucket = processorBucket;
    }
}
