package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import android.graphics.Rect;
import android.util.Size;

import kr.auto.titration.mobile.thermal.officialdex.OfficialDexArtifacts;

import org.junit.Assert;
import org.junit.Test;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

public final class OfficialF2RadiometricBridgeContractTest {
    @Test
    public void exactD3fEContractRebuildsPresentCustomPaletteAndUsesTwentyOneArguments() throws Exception {
        File calibration = calibrationFile("SN-EXACT");
        OfficialF2RadiometricRequest request = requestBuilder(calibration, "SN-EXACT")
            .measurementRoi((Rect) null)
            .build();
        RecordingRuntime runtime = new RecordingRuntime();

        OfficialF2RadiometricResult result = new OfficialF2RadiometricBridge().renderAndMeasure(runtime, request);

        Assert.assertArrayEquals(new byte[] {9, 8, 7}, result.getRadiometricJpeg());
        Assert.assertEquals(OfficialF2RuleScope.FULLSCREEN, result.getMeasuredScope());
        Assert.assertNotNull(result.getGlobalTemperatureStats());
        Assert.assertEquals(1, runtime.renderCalls);
        Assert.assertNotNull(runtime.createdPalette);
        Assert.assertEquals(1, runtime.createPaletteCalls);
        Assert.assertSame(request.getPaletteSnapshot(), runtime.lastPaletteSnapshot);
        Assert.assertSame(runtime.createdPalette, runtime.lastRendererArgs[16]);
        Assert.assertEquals(21, runtime.lastRendererArgs.length);
        Assert.assertArrayEquals(new byte[] {1, 2, 3}, (byte[]) runtime.lastRendererArgs[0]);
        Assert.assertTrue(runtime.lastRendererArgs[1] instanceof Size);
        Assert.assertArrayEquals(new byte[] {4}, (byte[]) runtime.lastRendererArgs[2]);
        Assert.assertArrayEquals(new byte[] {5, 6}, (byte[]) runtime.lastRendererArgs[3]);
        Assert.assertArrayEquals(new byte[] {7, 8}, (byte[]) runtime.lastRendererArgs[4]);
        Assert.assertSame(runtime.offlineCfg, runtime.lastRendererArgs[5]);
        Assert.assertArrayEquals(new byte[] {42}, (byte[]) runtime.lastRendererArgs[6]);
        Assert.assertArrayEquals(new byte[] {10}, (byte[]) runtime.lastRendererArgs[7]);
        Assert.assertTrue(runtime.lastRendererArgs[8] instanceof Size);
        Assert.assertTrue(runtime.lastRendererArgs[9] instanceof Size);
        Assert.assertSame(calibration, runtime.lastRendererArgs[10]);
        Assert.assertEquals(3, runtime.lastRendererArgs[11]);
        Assert.assertEquals(40.5f, (Float) runtime.lastRendererArgs[12], 0f);
        Assert.assertEquals(10.25f, (Float) runtime.lastRendererArgs[13], 0f);
        Assert.assertEquals(Boolean.TRUE, runtime.lastRendererArgs[14]);
        Assert.assertNull(runtime.lastRendererArgs[15]);
        Assert.assertTrue(runtime.lastRendererArgs[17] instanceof HashMap);
        Assert.assertTrue(runtime.lastRendererArgs[18] instanceof Rect);
        Assert.assertTrue(runtime.lastRendererArgs[19] instanceof Size);
        Assert.assertSame(runtime.moduleType, runtime.lastRendererArgs[20]);
        Assert.assertEquals(0, runtime.lastRuleSpec.getId());
        Assert.assertEquals("Global", runtime.lastRuleSpec.getName());
    }

    @Test
    public void standardF2WithPreviewManagerQNullProofPassesNullPaletteArg17AndSucceeds() throws Exception {
        RecordingRuntime runtime = new RecordingRuntime();
        OfficialF2RadiometricRequest request = requestBuilder(calibrationFile("SN-QNULL"), "SN-QNULL")
            .moduleSubtype(OfficialF2ModuleSubtype.F2)
            .paletteSnapshot(OfficialF2PaletteSnapshot.absent(
                OfficialF2PaletteSnapshot.AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL
            ))
            .build();

        OfficialF2RadiometricResult result = new OfficialF2RadiometricBridge().renderAndMeasure(runtime, request);

        Assert.assertArrayEquals(new byte[] {9, 8, 7}, result.getRadiometricJpeg());
        Assert.assertEquals(1, runtime.renderCalls);
        Assert.assertEquals(0, runtime.createPaletteCalls);
        Assert.assertNull(runtime.lastRendererArgs[16]);
        Assert.assertEquals(21, runtime.lastRendererArgs.length);
        Assert.assertSame(runtime.moduleType, runtime.lastRendererArgs[20]);
    }

    @Test
    public void missingPaletteSnapshotDoesNotInventPaletteOrDefaultAbsentProof() throws Exception {
        RecordingRuntime runtime = new RecordingRuntime();
        OfficialF2RadiometricException thrown = Assert.assertThrows(
            OfficialF2RadiometricException.class,
            () -> new OfficialF2RadiometricBridge().renderAndMeasure(
                runtime,
                requestBuilder(calibrationFile("SN-NOPAL"), "SN-NOPAL")
                    .paletteSnapshot(null)
                    .build()
            )
        );

        Assert.assertTrue(thrown.getMessage().contains("PreviewManagerII.Q() returned null"));
        Assert.assertEquals(0, runtime.createPaletteCalls);
        Assert.assertEquals(0, runtime.renderCalls);
        Assert.assertNull(runtime.lastRendererArgs);
    }

    @Test
    public void analyzerLifecycleStatsAndFloatConverterUseExactScalarD3Path() throws Exception {
        RecordingRuntime runtime = new RecordingRuntime();

        OfficialF2RadiometricResult result = new OfficialF2RadiometricBridge()
            .renderAndMeasure(runtime, requestBuilder(calibrationFile("SN-FLOAT"), "SN-FLOAT").build());

        Assert.assertEquals(Arrays.asList(
            "bootstrap", "parseOfflineConfig", "resolveModuleType", "createPaletteBean",
            "renderRadiometricJpeg", "prepareAnalyzer", "initAnalyzer", "buildMeasureRule",
            "measure", "intd3ToFloat:111", "intd3ToFloat:222", "intd3ToFloat:333",
            "intd3ToFloat:444", "releaseAnalyzer"
        ), runtime.events);
        Assert.assertEquals(11.1f, result.getRuleTemperatureStats().getMaxCelsius(), 0.0001f);
        Assert.assertEquals(22.2f, result.getRuleTemperatureStats().getMinCelsius(), 0.0001f);
        Assert.assertEquals(33.3f, result.getRuleTemperatureStats().getCenterCelsius(), 0.0001f);
        Assert.assertEquals(44.4f, result.getRuleTemperatureStats().getAverageCelsius(), 0.0001f);
    }

    @Test
    public void geometryUsesOfficialGlobalIdentityAndExclusiveAndroidRoiBounds() throws Exception {
        RecordingRuntime fullscreen = new RecordingRuntime();
        new OfficialF2RadiometricBridge().renderAndMeasure(
            fullscreen,
            requestBuilder(calibrationFile("SN-FULL"), "SN-FULL").measurementRoi((Rect) null).build()
        );
        Assert.assertEquals(OfficialF2RuleScope.FULLSCREEN, fullscreen.lastRuleSpec.getScope());
        Assert.assertEquals(0, fullscreen.lastRuleSpec.getId());
        Assert.assertEquals("Global", fullscreen.lastRuleSpec.getName());
        Assert.assertEquals(Arrays.asList(0, 0, 191, 255), Arrays.asList(
            fullscreen.lastRuleSpec.getX0(), fullscreen.lastRuleSpec.getY0(),
            fullscreen.lastRuleSpec.getX1(), fullscreen.lastRuleSpec.getY1()
        ));

        RecordingRuntime roi = new RecordingRuntime();
        new OfficialF2RadiometricBridge().renderAndMeasure(
            roi,
            requestBuilder(calibrationFile("SN-ROI"), "SN-ROI").measurementRoi(2, 3, 8, 9).build()
        );
        Assert.assertEquals(OfficialF2RuleScope.RECTANGLE, roi.lastRuleSpec.getScope());
        Assert.assertEquals(Arrays.asList(2, 3, 7, 8), Arrays.asList(
            roi.lastRuleSpec.getX0(), roi.lastRuleSpec.getY0(), roi.lastRuleSpec.getX1(), roi.lastRuleSpec.getY1()
        ));
    }

    @Test
    public void releaseRunsWhenPostAcquisitionInitOrMeasureFails() throws Exception {
        RecordingRuntime initFailure = new RecordingRuntime();
        initFailure.initReturn = false;
        OfficialF2RadiometricException initThrown = Assert.assertThrows(
            OfficialF2RadiometricException.class,
            () -> new OfficialF2RadiometricBridge().renderAndMeasure(
                initFailure,
                requestBuilder(calibrationFile("SN-INIT"), "SN-INIT").build()
            )
        );
        Assert.assertTrue(initThrown.getMessage().contains("AnalyzerII.init"));
        Assert.assertTrue(initFailure.events.contains("releaseAnalyzer"));

        RecordingRuntime measureFailure = new RecordingRuntime();
        measureFailure.measurement = new OfficialF2MeasurementD3(false, null, null, null, 0);
        OfficialF2RadiometricException measureThrown = Assert.assertThrows(
            OfficialF2RadiometricException.class,
            () -> new OfficialF2RadiometricBridge().renderAndMeasure(
                measureFailure,
                requestBuilder(calibrationFile("SN-MEASURE"), "SN-MEASURE").build()
            )
        );
        Assert.assertTrue(measureThrown.getMessage().contains("AnalyzerII.measure"));
        Assert.assertTrue(measureFailure.events.contains("releaseAnalyzer"));
    }

    @Test
    public void validationFailsClosedForModuleIdentityAndCalibrationProvenance() throws Exception {
        Assert.assertThrows(OfficialF2RadiometricException.class, () ->
            new OfficialF2RadiometricBridge().renderAndMeasure(
                new RecordingRuntime(),
                requestBuilder(calibrationFile("SN-BLANK"), "SN-BLANK")
                    .moduleIdentity(completeIdentity(""))
                    .build()
            )
        );
        Assert.assertThrows(OfficialF2RadiometricException.class, () ->
            new OfficialF2RadiometricBridge().renderAndMeasure(
                new RecordingRuntime(),
                requestBuilder(calibrationFile("SN-FILE-A"), "SN-FILE-B").build()
            )
        );
        Assert.assertThrows(OfficialF2RadiometricException.class, () ->
            new OfficialF2RadiometricBridge().renderAndMeasure(
                new RecordingRuntime(),
                requestBuilder(calibrationFile("SN-PROV"), "SN-PROV")
                    .calibrationIdentitySerialComponent("OTHER")
                    .build()
            )
        );
    }

    @Test
    public void resolvedProfileRejectsMismatchedCodingAndPacketBeforeRuntimeBootstrap() throws Exception {
        RecordingRuntime codingRuntime = new RecordingRuntime();
        OfficialF2RadiometricException codingFailure = Assert.assertThrows(
            OfficialF2RadiometricException.class,
            () -> new OfficialF2RadiometricBridge().renderAndMeasure(
                codingRuntime,
                requestBuilder(calibrationFile("SN-CODING"), "SN-CODING")
                    .videoCodingType(8)
                    .build()
            )
        );
        Assert.assertTrue(codingFailure.getMessage().contains("mismatches resolved profile f3.j"));
        Assert.assertTrue(codingRuntime.events.isEmpty());

        RecordingRuntime packetRuntime = new RecordingRuntime();
        OfficialF2RadiometricException packetFailure = Assert.assertThrows(
            OfficialF2RadiometricException.class,
            () -> new OfficialF2RadiometricBridge().renderAndMeasure(
                packetRuntime,
                requestBuilder(calibrationFile("SN-PACKET"), "SN-PACKET")
                    .packetSize(101320)
                    .build()
            )
        );
        Assert.assertTrue(packetFailure.getMessage().contains("not allowed by resolved profile f3.j"));
        Assert.assertTrue(packetRuntime.events.isEmpty());
    }

    @Test
    public void exactF3JProfileCodingAndPacketReachRuntimeUnchanged() throws Exception {
        RecordingRuntime runtime = new RecordingRuntime();

        new OfficialF2RadiometricBridge().renderAndMeasure(
            runtime,
            requestBuilder(calibrationFile("SN-F3J"), "SN-F3J")
                .videoCodingType(12)
                .packetSize(183496)
                .build()
        );

        Assert.assertEquals("0953060001", runtime.bootstrapIdentity.getModuleId());
        Assert.assertEquals(12, runtime.bootstrapVideoCodingType);
        Assert.assertEquals(183496, runtime.bootstrapPacketSize);
    }

    @Test
    public void nonReentrantCallFailsClosedAndOuterCallStillReleases() throws Exception {
        RecordingRuntime runtime = new RecordingRuntime();
        AtomicReference<Throwable> nestedFailure = new AtomicReference<>();
        OfficialF2RadiometricRequest outerRequest = requestBuilder(calibrationFile("SN-OUTER"), "SN-OUTER").build();
        OfficialF2RadiometricRequest innerRequest = requestBuilder(calibrationFile("SN-INNER"), "SN-INNER").build();
        runtime.onRender = () -> {
            try {
                new OfficialF2RadiometricBridge().renderAndMeasure(new RecordingRuntime(), innerRequest);
            } catch (Throwable throwable) {
                nestedFailure.set(throwable);
            }
        };

        new OfficialF2RadiometricBridge().renderAndMeasure(runtime, outerRequest);

        Assert.assertTrue(nestedFailure.get() instanceof OfficialF2RadiometricException);
        Assert.assertTrue(nestedFailure.get().getMessage().contains("non-reentrant"));
        Assert.assertTrue(runtime.events.contains("releaseAnalyzer"));
    }

    @Test
    public void childLoaderIdentitiesAndNoMatrixSurfaceArePinned() {
        for (String name : Arrays.asList(
            "d3.f", "k3.b", "d2.a",
            "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG",
            "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
            "hik.common.yyrj.uicommon.data.ModuleType$F2ModuleType",
            "com.hikvision.microjita.AnalyzerII",
            "com.hikvision.microjita.bean.AnalyzerInfoPic",
            "com.guardexpert.microsensorsdk.core.util.FloatConverter",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureRule",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats"
        )) {
            Assert.assertTrue("missing " + name, OfficialDexArtifacts.REQUIRED_OFFICIAL_CLASSES.contains(name));
        }
        Assert.assertEquals(21, OfficialF2RadiometricBridge.D3F_E_EXPLICIT_ARGUMENT_COUNT);
        for (Method method : OfficialF2RadiometricResult.class.getDeclaredMethods()) {
            Assert.assertFalse(method.getName().toLowerCase().contains("matrix"));
        }
    }

    private static OfficialF2RadiometricRequest.Builder requestBuilder(File calibration, String serial) {
        HashMap<String, Object> adjustments = new HashMap<>();
        adjustments.put("contrast", 5);
        return OfficialF2RadiometricRequest.builder()
            .firJpegData(new byte[] {1, 2, 3})
            .firJpegSize(192, 256)
            .visibleJpegData(new byte[] {4})
            .rawData(new byte[] {5, 6})
            .rawAppendData(new byte[] {7, 8})
            .callbackHead(new byte[] {9})
            .rawAppendLine2(new byte[] {10})
            .originalSize(192, 256)
            .visibleSize(96, 128)
            .calibrationFile(calibration)
            .calibrationIdentitySerialComponent(serial)
            .agcMode(3)
            .maxEnvironmentTemp(40.5f)
            .minEnvironmentTemp(10.25f)
            .needsNewOfflineRawPic(true)
            .paletteSnapshot(OfficialF2PaletteSnapshot.present(
                2, 2, new String[] {"#ff0000", "#00ff00"}, 6, 40.5f, 10.25f,
                1, 3, 90.0f, -20.0f, 4095, 17, 255, 2, 3000, 100, 16383, 0
            ))
            .imageAdjustments(adjustments)
            .fusionRect(new Rect(1, 2, 3, 4))
            .fusionSize(new Size(10, 20))
            .videoCodingType(12)
            .packetSize(203720)
            .moduleSubtype(OfficialF2ModuleSubtype.F2)
            .moduleIdentity(completeIdentity(serial));
    }

    private static OfficialF2ModuleIdentity completeIdentity(String serial) {
        return OfficialF2ModuleIdentity.builder()
            .moduleId("0953060001")
            .serialNumber(serial)
            .devType(1)
            .deviceType("F2")
            .deviceName("Mini2")
            .firmwareVersion("APP_010203_20200101")
            .hardwareVersion("HW")
            .firmwareCode("CODE")
            .build();
    }

    private static File calibrationFile(String serial) throws IOException {
        File file = File.createTempFile("HM-Calibration_" + serial + "_", ".dat");
        file.deleteOnExit();
        return file;
    }

    private static final class RecordingRuntime implements OfficialF2RadiometricRuntime {
        final List<String> events = new ArrayList<>();
        final Object offlineCfg = new Object();
        final Object moduleType = new Object();
        final Object createdPalette = new Object();
        final Object measureRule = new Object();
        Object[] lastRendererArgs;
        OfficialF2RuleSpec lastRuleSpec;
        int renderCalls;
        boolean initReturn = true;
        Runnable onRender;
        OfficialF2MeasurementD3 measurement = new OfficialF2MeasurementD3(true, 111, 222, 333, 444);
        int createPaletteCalls;
        OfficialF2PaletteSnapshot lastPaletteSnapshot;
        OfficialF2ModuleIdentity bootstrapIdentity;
        int bootstrapVideoCodingType;
        int bootstrapPacketSize;

        @Override public void bootstrap(OfficialF2ModuleIdentity identity, int videoCodingType, int packetSize) {
            events.add("bootstrap");
            bootstrapIdentity = identity;
            bootstrapVideoCodingType = videoCodingType;
            bootstrapPacketSize = packetSize;
        }
        @Override public OfficialF2ParsedOfflineConfig parseOfflineConfig(OfficialF2ParserCall call) { events.add("parseOfflineConfig"); return new OfficialF2ParsedOfflineConfig(offlineCfg, new byte[] {42}); }
        @Override public Object createPaletteBean(OfficialF2PaletteSnapshot snapshot) { events.add("createPaletteBean"); createPaletteCalls++; lastPaletteSnapshot = snapshot; return snapshot != null && snapshot.isPresent() ? createdPalette : null; }
        @Override public Object resolveModuleType(OfficialF2ModuleSubtype subtype) { events.add("resolveModuleType"); return moduleType; }
        @Override public byte[] renderRadiometricJpeg(OfficialF2RendererCall call) { events.add("renderRadiometricJpeg"); renderCalls++; lastRendererArgs = call.getExactArguments(); if (onRender != null) onRender.run(); return new byte[] {9, 8, 7}; }
        @Override public void prepareAnalyzer() { events.add("prepareAnalyzer"); }
        @Override public boolean initAnalyzer(byte[] radiometricJpeg) { events.add("initAnalyzer"); Assert.assertArrayEquals(new byte[] {9, 8, 7}, radiometricJpeg); return initReturn; }
        @Override public Object buildMeasureRule(OfficialF2RuleSpec ruleSpec) { events.add("buildMeasureRule"); lastRuleSpec = ruleSpec; return measureRule; }
        @Override public OfficialF2MeasurementD3 measure(Object measureRule) { events.add("measure"); Assert.assertSame(this.measureRule, measureRule); return measurement; }
        @Override public float intd3ToFloat(int value) { events.add("intd3ToFloat:" + value); return value / 10.0f; }
        @Override public void releaseAnalyzer() { events.add("releaseAnalyzer"); }
    }
}
