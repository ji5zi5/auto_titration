package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import android.content.Context;
import android.graphics.Rect;
import android.util.Size;

import kr.auto.titration.mobile.thermal.HikmicroF2Profile;
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution;
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolver;
import kr.auto.titration.mobile.thermal.officialdex.OfficialDexLoadException;

import java.io.File;
import java.util.HashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Exact official F2 radiometric JPEG + scalar stats bridge.
 *
 * The only production path is:
 * child loader -> d3.f.a.e(exact 21 args) -> returned radiometric JPEG ->
 * child AnalyzerII.INSTANCE -> AnalyzerInfoPic -> init("", false, ...) ->
 * exact child MeasureRule -> measure -> MeasurementStats d3 scalars -> exact
 * child FloatConverter.intd3ToFloat. Full Celsius matrices and fallback formulas
 * are intentionally absent.
 */
public final class OfficialF2RadiometricBridge {
    public static final String D3F_E_DESCRIPTOR =
        "([BLandroid/util/Size;[B[B[BLcom/hik/f2module/IFR_INFO$OFFLINE_TEMP_MEASURE_CFG;" +
            "[B[BLandroid/util/Size;Landroid/util/Size;Ljava/io/File;IFFZLjava/io/File;" +
            "Lcom/hikmicro/analyzer/sdk/palette/bean/PaletteBean;Ljava/util/HashMap;" +
            "Landroid/graphics/Rect;Landroid/util/Size;Lhik/common/yyrj/uicommon/data/ModuleType;)[B";

    public static final int D3F_E_EXPLICIT_ARGUMENT_COUNT = OfficialF2RendererCall.EXACT_ARGUMENT_COUNT;
    public static final String PALETTE_SNAPSHOT_MESSAGE =
        "PaletteBean snapshot must be present or explicitly absent because PreviewManagerII.Q() returned null";

    private static final AtomicBoolean IN_USE = new AtomicBoolean(false);

    public OfficialF2RadiometricResult renderAndMeasure(
        Context context,
        OfficialF2RadiometricRequest request
    ) throws OfficialF2RadiometricException {
        return renderSingleFlight(() -> {
            Context appContext = validateContext(context);
            return OfficialF2ReflectionRuntime.load(appContext);
        }, request);
    }

    /** Package-private injectable seam for lifecycle/descriptor/geometry tests. */
    OfficialF2RadiometricResult renderAndMeasure(
        OfficialF2RadiometricRuntime runtime,
        OfficialF2RadiometricRequest request
    ) throws OfficialF2RadiometricException {
        if (runtime == null) {
            throw failClosed("OfficialF2RadiometricRuntime is required");
        }
        return renderSingleFlight(() -> runtime, request);
    }

    private OfficialF2RadiometricResult renderSingleFlight(
        RuntimeFactory runtimeFactory,
        OfficialF2RadiometricRequest request
    ) throws OfficialF2RadiometricException {
        if (!IN_USE.compareAndSet(false, true)) {
            throw failClosed("Official F2 radiometric bridge is single-flight and non-reentrant");
        }

        OfficialF2RadiometricRuntime runtime = null;
        boolean analyzerPrepared = false;
        OfficialF2RadiometricException failure = null;
        OfficialF2RadiometricException releaseFailure = null;
        OfficialF2RadiometricResult result = null;

        try {
            ValidatedRequest valid = ValidatedRequest.from(request);
            runtime = runtimeFactory.create();
            runtime.bootstrap(valid.moduleIdentity, valid.videoCodingType, valid.packetSize);

            OfficialF2ParsedOfflineConfig offlineConfig = runtime.parseOfflineConfig(
                new OfficialF2ParserCall(
                    valid.callbackHead,
                    valid.videoCodingType,
                    valid.forcePaletteMode14
                )
            );
            Object moduleType = runtime.resolveModuleType(valid.moduleSubtype);
            Object paletteBean = paletteArgument(runtime, valid.paletteSnapshot);
            byte[] radiometricJpeg = runtime.renderRadiometricJpeg(
                new OfficialF2RendererCall(exactD3fEArguments(valid, offlineConfig, paletteBean, moduleType))
            );
            if (radiometricJpeg == null || radiometricJpeg.length == 0) {
                throw failClosed("Official d3.f.e returned empty radiometric JPEG");
            }

            runtime.prepareAnalyzer();
            analyzerPrepared = true;
            if (!runtime.initAnalyzer(radiometricJpeg)) {
                throw failClosed("Official AnalyzerII.init failed closed");
            }

            Object measureRule = runtime.buildMeasureRule(measureRuleSpec(valid));
            OfficialF2MeasurementD3 measurement = runtime.measure(measureRule);
            if (!measurement.isSuccess()) {
                throw failClosed("Official AnalyzerII.measure returned false");
            }

            OfficialF2TemperatureStats ruleStats = convertStats(runtime, measurement);
            OfficialF2TemperatureStats globalStats =
                valid.measureScope == OfficialF2RuleScope.FULLSCREEN ? ruleStats : null;
            result = new OfficialF2RadiometricResult(
                radiometricJpeg,
                valid.measureScope,
                ruleStats,
                globalStats
            );
        } catch (OfficialF2RadiometricException e) {
            failure = e;
        } catch (OfficialDexLoadException e) {
            failure = failClosed("Official dex load failed closed", e);
        } catch (ReflectiveOperationException e) {
            failure = failClosed("Official F2 radiometric reflection failed closed", e);
        } catch (LinkageError | RuntimeException e) {
            failure = failClosed("Official F2 radiometric runtime failed closed", e);
        } catch (Exception e) {
            failure = failClosed("Official F2 radiometric bridge failed closed", e);
        } finally {
            if (analyzerPrepared && runtime != null) {
                try {
                    runtime.releaseAnalyzer();
                } catch (Exception | LinkageError e) {
                    releaseFailure = failClosed("Official AnalyzerII.release failed closed", e);
                }
            }
            IN_USE.set(false);
        }

        if (failure != null) {
            if (releaseFailure != null) {
                failure.addSuppressed(releaseFailure);
            }
            throw failure;
        }
        if (releaseFailure != null) {
            throw releaseFailure;
        }
        if (result == null) {
            throw failClosed("Official F2 radiometric bridge produced no result");
        }
        return result;
    }

    private static Object[] exactD3fEArguments(
        ValidatedRequest valid,
        OfficialF2ParsedOfflineConfig offlineConfig,
        Object paletteBean,
        Object moduleType
    ) throws OfficialF2RadiometricException {
        byte[] extendGeneralInfo = offlineConfig.getExtendGeneralInfo();
        if (extendGeneralInfo == null) {
            throw failClosed("Official extendGeneralInto was null");
        }
        return new Object[] {
            valid.firJpegData,                 // 1  firJpegData: [B
            valid.firJpegSize,                 // 2  firJpegSize: Size
            valid.visibleJpegData,             // 3  visJpegData: [B
            valid.rawData,                     // 4  byteArrRawData: [B
            valid.rawAppendData,               // 5  byteArrRawAppendData: [B
            offlineConfig.getOfflineTempMeasureCfg(), // 6 OFFLINE_TEMP_MEASURE_CFG (child)
            extendGeneralInfo,                 // 7  extendGeneralInto: [B
            valid.rawAppendLine2,              // 8  byteArrRawAppendLine2_Hoz: [B
            valid.originalSize,                // 9  orignalSize: Size
            valid.visibleSize,                 // 10 visSize: Size
            valid.calibrationFile,             // 11 calibrationFile: File
            valid.agcMode,                     // 12 agcMode: int
            valid.maxEnvironmentTemp,          // 13 maxEnvironmentTemp: float
            valid.minEnvironmentTemp,          // 14 minEnvironmentTemp: float
            valid.needsNewOfflineRawPic,       // 15 needsNewOfflineRawPic: boolean
            valid.ispFile,                     // 16 ispFile: File
            paletteBean,                       // 17 nullable PaletteBean from PreviewManagerII.Q snapshot
            valid.imageAdjustments,            // 18 HashMap image adjustments
            valid.fusionRect,                  // 19 Rect fusion crop
            valid.fusionSize,                  // 20 Size fusion output
            moduleType                         // 21 ModuleType (child F2ModuleType)
        };
    }

    private static Object paletteArgument(
        OfficialF2RadiometricRuntime runtime,
        OfficialF2PaletteSnapshot snapshot
    ) throws Exception {
        if (snapshot == null) {
            throw failClosed(PALETTE_SNAPSHOT_MESSAGE);
        }
        if (!snapshot.isPresent()) {
            if (snapshot.getAbsenceProof()
                != OfficialF2PaletteSnapshot.AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL) {
                throw failClosed(PALETTE_SNAPSHOT_MESSAGE);
            }
            return null;
        }
        Object paletteBean = runtime.createPaletteBean(snapshot);
        if (paletteBean == null) {
            throw failClosed("Present PaletteBean snapshot must be rebuilt child-side");
        }
        return paletteBean;
    }

    private static OfficialF2RuleSpec measureRuleSpec(ValidatedRequest valid) {
        if (valid.measurementRoi == null) {
            return new OfficialF2RuleSpec(
                OfficialF2RuleScope.FULLSCREEN,
                0,
                "Global",
                0,
                0,
                valid.measurementWidth - 1,
                valid.measurementHeight - 1
            );
        }
        return new OfficialF2RuleSpec(
            OfficialF2RuleScope.RECTANGLE,
            1,
            "roi",
            valid.measurementRoiLeft,
            valid.measurementRoiTop,
            valid.measurementRoiRight - 1,
            valid.measurementRoiBottom - 1
        );
    }

    private static OfficialF2TemperatureStats convertStats(
        OfficialF2RadiometricRuntime runtime,
        OfficialF2MeasurementD3 measurement
    ) throws Exception {
        return new OfficialF2TemperatureStats(
            convertNullableD3(runtime, measurement.getMaxD3()),
            convertNullableD3(runtime, measurement.getMinD3()),
            convertNullableD3(runtime, measurement.getCenterD3()),
            runtime.intd3ToFloat(measurement.getAverageD3())
        );
    }

    private static Float convertNullableD3(OfficialF2RadiometricRuntime runtime, Integer value)
        throws Exception {
        return value == null ? null : runtime.intd3ToFloat(value);
    }

    private static Context validateContext(Context context) throws OfficialF2RadiometricException {
        if (context == null) {
            throw failClosed("Context is required");
        }
        Context appContext = context.getApplicationContext() != null ? context.getApplicationContext() : context;
        if (appContext == null) {
            throw failClosed("Application context is required");
        }
        return appContext;
    }

    private static OfficialF2RadiometricException failClosed(String message) {
        return new OfficialF2RadiometricException(message);
    }

    private static OfficialF2RadiometricException failClosed(String message, Throwable cause) {
        return new OfficialF2RadiometricException(message, cause);
    }

    private interface RuntimeFactory {
        OfficialF2RadiometricRuntime create() throws Exception;
    }

    private static final class ValidatedRequest {
        final byte[] firJpegData;
        final Size firJpegSize;
        final byte[] visibleJpegData;
        final byte[] rawData;
        final byte[] rawAppendData;
        final byte[] callbackHead;
        final byte[] rawAppendLine2;
        final Size originalSize;
        final Size visibleSize;
        final File calibrationFile;
        final int agcMode;
        final float maxEnvironmentTemp;
        final float minEnvironmentTemp;
        final boolean needsNewOfflineRawPic;
        final File ispFile;
        final OfficialF2PaletteSnapshot paletteSnapshot;
        final HashMap<String, Object> imageAdjustments;
        final Rect fusionRect;
        final Size fusionSize;
        final Rect measurementRoi;
        final int measurementRoiLeft;
        final int measurementRoiTop;
        final int measurementRoiRight;
        final int measurementRoiBottom;
        final int measurementWidth;
        final int measurementHeight;
        final OfficialF2RuleScope measureScope;
        final int videoCodingType;
        final int packetSize;
        final OfficialF2ModuleSubtype moduleSubtype;
        final OfficialF2ModuleIdentity moduleIdentity;
        final boolean forcePaletteMode14;

        private ValidatedRequest(OfficialF2RadiometricRequest request) throws OfficialF2RadiometricException {
            firJpegData = requireNonEmpty(request.getFirJpegData(), "firJpegData");
            firJpegSize = requireSize(
                request.getFirJpegSize(),
                request.getFirJpegWidth(),
                request.getFirJpegHeight(),
                "firJpegSize"
            );
            visibleJpegData = requireNotNull(request.getVisibleJpegData(), "visibleJpegData");
            rawData = requireNonEmpty(request.getRawData(), "rawData");
            rawAppendData = requireNonEmpty(request.getRawAppendData(), "rawAppendData");
            callbackHead = requireNonEmpty(request.getCallbackHead(), "callbackHead");
            rawAppendLine2 = requireNotNull(request.getRawAppendLine2(), "rawAppendLine2");
            originalSize = requireSize(
                request.getOriginalSize(),
                request.getOriginalWidth(),
                request.getOriginalHeight(),
                "originalSize"
            );
            visibleSize = requireSize(
                request.getVisibleSize(),
                request.getVisibleWidth(),
                request.getVisibleHeight(),
                "visSize"
            );
            calibrationFile = requireReadableFile(request.getCalibrationFile(), "calibrationFile");
            agcMode = request.getAgcMode();
            maxEnvironmentTemp = requireFinite(request.getMaxEnvironmentTemp(), "maxEnvironmentTemp");
            minEnvironmentTemp = requireFinite(request.getMinEnvironmentTemp(), "minEnvironmentTemp");
            needsNewOfflineRawPic = request.isNeedsNewOfflineRawPic();
            ispFile = request.getIspFile();
            if (ispFile != null && !ispFile.isFile()) {
                throw failClosed("ispFile does not exist: " + ispFile);
            }
            paletteSnapshot = request.getPaletteSnapshot();
            imageAdjustments = request.getImageAdjustments();
            fusionRect = request.getFusionRect();
            fusionSize = request.getFusionSize();
            measurementRoi = request.getMeasurementRoi();
            measurementWidth = request.getOriginalWidth();
            measurementHeight = request.getOriginalHeight();
            if (request.getMeasurementRoiLeft() == null
                && request.getMeasurementRoiTop() == null
                && request.getMeasurementRoiRight() == null
                && request.getMeasurementRoiBottom() == null) {
                measurementRoiLeft = 0;
                measurementRoiTop = 0;
                measurementRoiRight = 0;
                measurementRoiBottom = 0;
                measureScope = OfficialF2RuleScope.FULLSCREEN;
            } else {
                measurementRoiLeft = requireRoiCoordinate(request.getMeasurementRoiLeft(), "measurementRoi.left");
                measurementRoiTop = requireRoiCoordinate(request.getMeasurementRoiTop(), "measurementRoi.top");
                measurementRoiRight = requireRoiCoordinate(request.getMeasurementRoiRight(), "measurementRoi.right");
                measurementRoiBottom = requireRoiCoordinate(request.getMeasurementRoiBottom(), "measurementRoi.bottom");
                validateRectInside(
                    measurementRoiLeft,
                    measurementRoiTop,
                    measurementRoiRight,
                    measurementRoiBottom,
                    measurementWidth,
                    measurementHeight,
                    "measurementRoi"
                );
                measureScope = OfficialF2RuleScope.RECTANGLE;
            }
            videoCodingType = request.getVideoCodingType();
            if (videoCodingType <= 0) {
                throw failClosed("videoCodingType is required");
            }
            packetSize = request.getPacketSize();
            moduleSubtype = requireNotNull(request.getModuleSubtype(), "moduleSubtype");
            moduleIdentity = requireCompleteModuleIdentity(request.getModuleIdentity());
            requireMatchingResolvedProfile(moduleIdentity, videoCodingType, packetSize);
            requireCalibrationBoundToModule(request.getCalibrationIdentitySerialComponent(), moduleIdentity, calibrationFile);
            forcePaletteMode14 = request.isForcePaletteMode14();
        }

        static ValidatedRequest from(OfficialF2RadiometricRequest request) throws OfficialF2RadiometricException {
            if (request == null) {
                throw failClosed("OfficialF2RadiometricRequest is required");
            }
            return new ValidatedRequest(request);
        }

        private static HikmicroF2Profile requireMatchingResolvedProfile(
            OfficialF2ModuleIdentity identity,
            int videoCodingType,
            int packetSize
        ) throws OfficialF2RadiometricException {
            HikmicroF2ProfileResolution resolution = HikmicroF2ProfileResolver.INSTANCE.resolve(
                identity.getModuleId(),
                identity.getFirmwareVersion()
            );
            HikmicroF2Profile profile = resolution.getProfile();
            if (profile == null) {
                throw failClosed("Official F2 session profile unresolved: " + resolution.getReason());
            }
            if (videoCodingType != profile.getThermalCoding()) {
                throw failClosed(
                    "videoCodingType=" + videoCodingType + " mismatches resolved profile "
                        + profile.getOfficialClassName() + " coding=" + profile.getThermalCoding()
                );
            }
            if (!profile.getAllowedPacketSizes().contains(packetSize)) {
                throw failClosed(
                    "packetSize=" + packetSize + " not allowed by resolved profile "
                        + profile.getOfficialClassName() + " " + profile.getAllowedPacketSizes()
                );
            }
            return profile;
        }


        private static OfficialF2ModuleIdentity requireCompleteModuleIdentity(
            OfficialF2ModuleIdentity identity
        ) throws OfficialF2RadiometricException {
            requireNotNull(identity, "moduleIdentity");
            requireNonBlank(identity.getModuleId(), "moduleIdentity.moduleId");
            requireNonBlank(identity.getSerialNumber(), "moduleIdentity.serialNumber");
            requireNonBlank(identity.getDeviceType(), "moduleIdentity.deviceType");
            requireNonBlank(identity.getDeviceName(), "moduleIdentity.deviceName");
            requireNonBlank(identity.getFirmwareVersion(), "moduleIdentity.firmwareVersion");
            requireNonBlank(identity.getHardwareVersion(), "moduleIdentity.hardwareVersion");
            requireNonBlank(identity.getFirmwareCode(), "moduleIdentity.firmwareCode");
            if (identity.getDevType() <= 0) {
                throw failClosed("moduleIdentity.devType must be positive");
            }
            return identity;
        }

        private static void requireCalibrationBoundToModule(
            String calibrationIdentitySerialComponent,
            OfficialF2ModuleIdentity identity,
            File calibrationFile
        ) throws OfficialF2RadiometricException {
            String serial = requireNonBlank(
                calibrationIdentitySerialComponent,
                "calibrationIdentitySerialComponent"
            );
            if (!serial.equals(identity.getSerialNumber())) {
                throw failClosed("Calibration identity serial must match module identity serial");
            }
            if (!calibrationFile.getName().contains(serial)) {
                throw failClosed("Calibration file name must include the module identity serial");
            }
        }

        private static String requireNonBlank(String value, String name)
            throws OfficialF2RadiometricException {
            if (value == null || value.trim().isEmpty()) {
                throw failClosed(name + " is required and must be non-blank");
            }
            return value;
        }

        private static byte[] requireNotNull(byte[] value, String name) throws OfficialF2RadiometricException {
            if (value == null) {
                throw failClosed(name + " is required");
            }
            return value;
        }

        private static byte[] requireNonEmpty(byte[] value, String name) throws OfficialF2RadiometricException {
            if (value == null || value.length == 0) {
                throw failClosed(name + " is required and must be non-empty");
            }
            return value;
        }

        private static <T> T requireNotNull(T value, String name) throws OfficialF2RadiometricException {
            if (value == null) {
                throw failClosed(name + " is required");
            }
            return value;
        }

        private static Size requireSize(Size value, int width, int height, String name)
            throws OfficialF2RadiometricException {
            if (value == null || width <= 0 || height <= 0) {
                throw failClosed(name + " is required and must be positive");
            }
            return value;
        }

        private static File requireReadableFile(File file, String name) throws OfficialF2RadiometricException {
            if (file == null || !file.isFile() || !file.canRead()) {
                throw failClosed(name + " is required and must be readable");
            }
            return file;
        }

        private static float requireFinite(float value, String name) throws OfficialF2RadiometricException {
            if (!Float.isFinite(value)) {
                throw failClosed(name + " must be finite");
            }
            return value;
        }

        private static int requireRoiCoordinate(Integer value, String name)
            throws OfficialF2RadiometricException {
            if (value == null) {
                throw failClosed(name + " is required");
            }
            return value;
        }

        private static void validateRectInside(
            int left,
            int top,
            int right,
            int bottom,
            int width,
            int height,
            String name
        ) throws OfficialF2RadiometricException {
            if (right <= left || bottom <= top) {
                throw failClosed(name + " must be non-empty");
            }
            if (left < 0 || top < 0 || right > width || bottom > height) {
                throw failClosed(name + " must be inside measurement size");
            }
        }
    }
}
