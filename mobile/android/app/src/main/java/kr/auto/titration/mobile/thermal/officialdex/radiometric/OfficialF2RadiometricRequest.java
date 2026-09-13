package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import android.graphics.Rect;
import android.util.Size;

import java.io.File;
import java.util.Arrays;
import java.util.HashMap;

/**
 * Host-neutral capture snapshot for the exact child-loaded official F2 path.
 * No official SDK object crosses this request boundary.
 */
public final class OfficialF2RadiometricRequest {
    private final byte[] firJpegData;
    private final Size firJpegSize;
    private final int firJpegWidth;
    private final int firJpegHeight;
    private final byte[] visibleJpegData;
    private final byte[] rawData;
    private final byte[] rawAppendData;
    private final byte[] callbackHead;
    private final byte[] rawAppendLine2;
    private final Size originalSize;
    private final int originalWidth;
    private final int originalHeight;
    private final Size visibleSize;
    private final int visibleWidth;
    private final int visibleHeight;
    private final File calibrationFile;
    private final String calibrationIdentitySerialComponent;
    private final int agcMode;
    private final float maxEnvironmentTemp;
    private final float minEnvironmentTemp;
    private final boolean needsNewOfflineRawPic;
    private final File ispFile;
    private final OfficialF2PaletteSnapshot paletteSnapshot;
    private final HashMap<String, Object> imageAdjustments;
    private final Rect fusionRect;
    private final Size fusionSize;
    private final Rect measurementRoi;
    private final Integer measurementRoiLeft;
    private final Integer measurementRoiTop;
    private final Integer measurementRoiRight;
    private final Integer measurementRoiBottom;
    private final int videoCodingType;
    private final int packetSize;
    private final OfficialF2ModuleSubtype moduleSubtype;
    private final OfficialF2ModuleIdentity moduleIdentity;
    private final boolean forcePaletteMode14;

    private OfficialF2RadiometricRequest(Builder builder) {
        this.firJpegData = copy(builder.firJpegData);
        this.firJpegSize = builder.firJpegSize;
        this.firJpegWidth = builder.firJpegWidth;
        this.firJpegHeight = builder.firJpegHeight;
        this.visibleJpegData = copy(builder.visibleJpegData);
        this.rawData = copy(builder.rawData);
        this.rawAppendData = copy(builder.rawAppendData);
        this.callbackHead = copy(builder.callbackHead);
        this.rawAppendLine2 = copy(builder.rawAppendLine2);
        this.originalSize = builder.originalSize;
        this.originalWidth = builder.originalWidth;
        this.originalHeight = builder.originalHeight;
        this.visibleSize = builder.visibleSize;
        this.visibleWidth = builder.visibleWidth;
        this.visibleHeight = builder.visibleHeight;
        this.calibrationFile = builder.calibrationFile;
        this.calibrationIdentitySerialComponent = builder.calibrationIdentitySerialComponent;
        this.agcMode = builder.agcMode;
        this.maxEnvironmentTemp = builder.maxEnvironmentTemp;
        this.minEnvironmentTemp = builder.minEnvironmentTemp;
        this.needsNewOfflineRawPic = builder.needsNewOfflineRawPic;
        this.ispFile = builder.ispFile;
        this.paletteSnapshot = builder.paletteSnapshot;
        this.imageAdjustments = copy(builder.imageAdjustments);
        this.fusionRect = copy(builder.fusionRect);
        this.fusionSize = builder.fusionSize;
        this.measurementRoi = copy(builder.measurementRoi);
        this.measurementRoiLeft = builder.measurementRoiLeft;
        this.measurementRoiTop = builder.measurementRoiTop;
        this.measurementRoiRight = builder.measurementRoiRight;
        this.measurementRoiBottom = builder.measurementRoiBottom;
        this.videoCodingType = builder.videoCodingType;
        this.packetSize = builder.packetSize;
        this.moduleSubtype = builder.moduleSubtype;
        this.moduleIdentity = builder.moduleIdentity;
        this.forcePaletteMode14 = builder.forcePaletteMode14;
    }

    public byte[] getFirJpegData() {
        return copy(firJpegData);
    }

    public Size getFirJpegSize() {
        return firJpegSize;
    }

    public int getFirJpegWidth() {
        return firJpegWidth;
    }

    public int getFirJpegHeight() {
        return firJpegHeight;
    }

    /** Visible JPEG may be empty, but it must not be null. */
    public byte[] getVisibleJpegData() {
        return copy(visibleJpegData);
    }

    public byte[] getRawData() {
        return copy(rawData);
    }

    public byte[] getRawAppendData() {
        return copy(rawAppendData);
    }

    public byte[] getCallbackHead() {
        return copy(callbackHead);
    }

    public byte[] getRawAppendLine2() {
        return copy(rawAppendLine2);
    }

    public Size getOriginalSize() {
        return originalSize;
    }

    public int getOriginalWidth() {
        return originalWidth;
    }

    public int getOriginalHeight() {
        return originalHeight;
    }

    public Size getVisibleSize() {
        return visibleSize;
    }

    public int getVisibleWidth() {
        return visibleWidth;
    }

    public int getVisibleHeight() {
        return visibleHeight;
    }

    public File getCalibrationFile() {
        return calibrationFile;
    }

    public String getCalibrationIdentitySerialComponent() {
        return calibrationIdentitySerialComponent;
    }

    public int getAgcMode() {
        return agcMode;
    }

    public float getMaxEnvironmentTemp() {
        return maxEnvironmentTemp;
    }

    public float getMinEnvironmentTemp() {
        return minEnvironmentTemp;
    }

    public boolean isNeedsNewOfflineRawPic() {
        return needsNewOfflineRawPic;
    }

    public File getIspFile() {
        return ispFile;
    }

    public OfficialF2PaletteSnapshot getPaletteSnapshot() {
        return paletteSnapshot;
    }

    /** Optional W9 image-adjustment map; absence remains null. */
    public HashMap<String, Object> getImageAdjustments() {
        return copy(imageAdjustments);
    }

    public Rect getFusionRect() {
        return copy(fusionRect);
    }

    public Size getFusionSize() {
        return fusionSize;
    }

    public Rect getMeasurementRoi() {
        return copy(measurementRoi);
    }

    Integer getMeasurementRoiLeft() {
        return measurementRoiLeft;
    }

    Integer getMeasurementRoiTop() {
        return measurementRoiTop;
    }

    Integer getMeasurementRoiRight() {
        return measurementRoiRight;
    }

    Integer getMeasurementRoiBottom() {
        return measurementRoiBottom;
    }

    public int getVideoCodingType() {
        return videoCodingType;
    }

    public int getPacketSize() {
        return packetSize;
    }

    public OfficialF2ModuleSubtype getModuleSubtype() {
        return moduleSubtype;
    }

    public OfficialF2ModuleIdentity getModuleIdentity() {
        return moduleIdentity;
    }

    public boolean isForcePaletteMode14() {
        return forcePaletteMode14;
    }

    public static Builder builder() {
        return new Builder();
    }

    private static byte[] copy(byte[] value) {
        return value == null ? null : Arrays.copyOf(value, value.length);
    }

    private static Rect copy(Rect value) {
        return value == null ? null : new Rect(value);
    }

    private static HashMap<String, Object> copy(HashMap<String, Object> value) {
        return value == null ? null : new HashMap<>(value);
    }

    public static final class Builder {
        private byte[] firJpegData;
        private Size firJpegSize;
        private int firJpegWidth;
        private int firJpegHeight;
        private byte[] visibleJpegData;
        private byte[] rawData;
        private byte[] rawAppendData;
        private byte[] callbackHead;
        private byte[] rawAppendLine2;
        private Size originalSize;
        private int originalWidth;
        private int originalHeight;
        private Size visibleSize;
        private int visibleWidth;
        private int visibleHeight;
        private File calibrationFile;
        private String calibrationIdentitySerialComponent;
        private int agcMode;
        private float maxEnvironmentTemp;
        private float minEnvironmentTemp;
        private boolean needsNewOfflineRawPic;
        private File ispFile;
        private OfficialF2PaletteSnapshot paletteSnapshot;
        private HashMap<String, Object> imageAdjustments;
        private Rect fusionRect;
        private Size fusionSize;
        private Rect measurementRoi;
        private Integer measurementRoiLeft;
        private Integer measurementRoiTop;
        private Integer measurementRoiRight;
        private Integer measurementRoiBottom;
        private int videoCodingType;
        private int packetSize;
        private OfficialF2ModuleSubtype moduleSubtype;
        private OfficialF2ModuleIdentity moduleIdentity;
        private boolean forcePaletteMode14;

        private Builder() {
        }

        public Builder firJpegData(byte[] value) {
            this.firJpegData = copy(value);
            return this;
        }

        public Builder firJpegSize(Size value) {
            this.firJpegSize = value;
            this.firJpegWidth = value == null ? 0 : value.getWidth();
            this.firJpegHeight = value == null ? 0 : value.getHeight();
            return this;
        }

        /** JVM-testable host-neutral dimensions while preserving exact Size arg 2. */
        public Builder firJpegSize(int width, int height) {
            this.firJpegSize = new Size(width, height);
            this.firJpegWidth = width;
            this.firJpegHeight = height;
            return this;
        }

        public Builder visibleJpegData(byte[] value) {
            this.visibleJpegData = copy(value);
            return this;
        }

        public Builder rawData(byte[] value) {
            this.rawData = copy(value);
            return this;
        }

        public Builder rawAppendData(byte[] value) {
            this.rawAppendData = copy(value);
            return this;
        }

        public Builder callbackHead(byte[] value) {
            this.callbackHead = copy(value);
            return this;
        }

        public Builder rawAppendLine2(byte[] value) {
            this.rawAppendLine2 = copy(value);
            return this;
        }

        public Builder originalSize(Size value) {
            this.originalSize = value;
            this.originalWidth = value == null ? 0 : value.getWidth();
            this.originalHeight = value == null ? 0 : value.getHeight();
            return this;
        }

        public Builder originalSize(int width, int height) {
            this.originalSize = new Size(width, height);
            this.originalWidth = width;
            this.originalHeight = height;
            return this;
        }

        public Builder visibleSize(Size value) {
            this.visibleSize = value;
            this.visibleWidth = value == null ? 0 : value.getWidth();
            this.visibleHeight = value == null ? 0 : value.getHeight();
            return this;
        }

        public Builder visibleSize(int width, int height) {
            this.visibleSize = new Size(width, height);
            this.visibleWidth = width;
            this.visibleHeight = height;
            return this;
        }

        public Builder calibrationFile(File value) {
            this.calibrationFile = value;
            return this;
        }

        public Builder calibrationIdentitySerialComponent(String value) {
            this.calibrationIdentitySerialComponent = value;
            return this;
        }

        public Builder agcMode(int value) {
            this.agcMode = value;
            return this;
        }

        public Builder maxEnvironmentTemp(float value) {
            this.maxEnvironmentTemp = value;
            return this;
        }

        public Builder minEnvironmentTemp(float value) {
            this.minEnvironmentTemp = value;
            return this;
        }

        public Builder needsNewOfflineRawPic(boolean value) {
            this.needsNewOfflineRawPic = value;
            return this;
        }

        public Builder ispFile(File value) {
            this.ispFile = value;
            return this;
        }

        public Builder paletteSnapshot(OfficialF2PaletteSnapshot value) {
            this.paletteSnapshot = value;
            return this;
        }

        public Builder imageAdjustments(HashMap<String, Object> value) {
            this.imageAdjustments = copy(value);
            return this;
        }

        public Builder fusionRect(Rect value) {
            this.fusionRect = copy(value);
            return this;
        }

        public Builder fusionSize(Size value) {
            this.fusionSize = value;
            return this;
        }

        public Builder measurementRoi(Rect value) {
            this.measurementRoi = copy(value);
            this.measurementRoiLeft = value == null ? null : value.left;
            this.measurementRoiTop = value == null ? null : value.top;
            this.measurementRoiRight = value == null ? null : value.right;
            this.measurementRoiBottom = value == null ? null : value.bottom;
            return this;
        }

        /** Android Rect semantics: right/bottom are exclusive. */
        public Builder measurementRoi(int left, int top, int right, int bottom) {
            this.measurementRoi = new Rect(left, top, right, bottom);
            this.measurementRoiLeft = left;
            this.measurementRoiTop = top;
            this.measurementRoiRight = right;
            this.measurementRoiBottom = bottom;
            return this;
        }

        public Builder videoCodingType(int value) {
            this.videoCodingType = value;
            return this;
        }

        public Builder packetSize(int value) {
            this.packetSize = value;
            return this;
        }

        public Builder moduleSubtype(OfficialF2ModuleSubtype value) {
            this.moduleSubtype = value;
            return this;
        }

        public Builder moduleIdentity(OfficialF2ModuleIdentity value) {
            this.moduleIdentity = value;
            return this;
        }

        public Builder forcePaletteMode14(boolean value) {
            this.forcePaletteMode14 = value;
            return this;
        }

        public OfficialF2RadiometricRequest build() {
            return new OfficialF2RadiometricRequest(this);
        }
    }
}
