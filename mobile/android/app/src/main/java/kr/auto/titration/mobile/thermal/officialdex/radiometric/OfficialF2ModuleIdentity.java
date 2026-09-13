package kr.auto.titration.mobile.thermal.officialdex.radiometric;

/**
 * Host-neutral USB module identity copied into child-loaded UsbModuleInfo via
 * the exact official setters before radiometric work starts.
 */
public final class OfficialF2ModuleIdentity {
    private final String moduleId;
    private final String serialNumber;
    private final int devType;
    private final String deviceType;
    private final String deviceName;
    private final String firmwareVersion;
    private final String hardwareVersion;
    private final String firmwareCode;

    private OfficialF2ModuleIdentity(Builder builder) {
        this.moduleId = nonNull(builder.moduleId);
        this.serialNumber = nonNull(builder.serialNumber);
        this.devType = builder.devType;
        this.deviceType = nonNull(builder.deviceType);
        this.deviceName = nonNull(builder.deviceName);
        this.firmwareVersion = nonNull(builder.firmwareVersion);
        this.hardwareVersion = nonNull(builder.hardwareVersion);
        this.firmwareCode = nonNull(builder.firmwareCode);
    }

    public String getModuleId() {
        return moduleId;
    }

    public String getSerialNumber() {
        return serialNumber;
    }

    public int getDevType() {
        return devType;
    }

    public String getDeviceType() {
        return deviceType;
    }

    public String getDeviceName() {
        return deviceName;
    }

    public String getFirmwareVersion() {
        return firmwareVersion;
    }

    public String getHardwareVersion() {
        return hardwareVersion;
    }

    public String getFirmwareCode() {
        return firmwareCode;
    }

    public static Builder builder() {
        return new Builder();
    }

    private static String nonNull(String value) {
        return value == null ? "" : value;
    }

    public static final class Builder {
        private String moduleId = "";
        private String serialNumber = "";
        private int devType = 1;
        private String deviceType = "";
        private String deviceName = "";
        private String firmwareVersion = "";
        private String hardwareVersion = "";
        private String firmwareCode = "";

        private Builder() {
        }

        public Builder moduleId(String moduleId) {
            this.moduleId = moduleId;
            return this;
        }

        public Builder serialNumber(String serialNumber) {
            this.serialNumber = serialNumber;
            return this;
        }

        public Builder devType(int devType) {
            this.devType = devType;
            return this;
        }

        public Builder deviceType(String deviceType) {
            this.deviceType = deviceType;
            return this;
        }

        public Builder deviceName(String deviceName) {
            this.deviceName = deviceName;
            return this;
        }

        public Builder firmwareVersion(String firmwareVersion) {
            this.firmwareVersion = firmwareVersion;
            return this;
        }

        public Builder hardwareVersion(String hardwareVersion) {
            this.hardwareVersion = hardwareVersion;
            return this;
        }

        public Builder firmwareCode(String firmwareCode) {
            this.firmwareCode = firmwareCode;
            return this;
        }

        public OfficialF2ModuleIdentity build() {
            return new OfficialF2ModuleIdentity(this);
        }
    }
}
