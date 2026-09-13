package kr.auto.titration.mobile.thermal.officialdex.radiometric;

import android.content.Context;
import android.graphics.Rect;
import android.util.Size;

import kr.auto.titration.mobile.thermal.HikmicroF2Profile;
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution;
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolver;
import kr.auto.titration.mobile.thermal.officialdex.OfficialDexLoadException;
import kr.auto.titration.mobile.thermal.officialdex.OfficialDexLoadResult;
import kr.auto.titration.mobile.thermal.officialdex.OfficialDexLoader;

import java.io.File;
import java.lang.reflect.Array;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.ByteOrder;
import java.util.HashMap;

/** Exact child-loader implementation behind the package-private runtime seam. */
final class OfficialF2ReflectionRuntime implements OfficialF2RadiometricRuntime {
    private final Context appContext;
    private final OfficialF2Reflection reflect;

    private Object analyzer;
    private Object analyzerInfoPic;
    private Method analyzerInit;
    private Method analyzerMeasure;
    private Method analyzerRelease;

    private OfficialF2ReflectionRuntime(Context appContext, OfficialF2Reflection reflect) {
        this.appContext = appContext;
        this.reflect = reflect;
    }

    static OfficialF2ReflectionRuntime load(Context appContext) throws OfficialDexLoadException {
        OfficialDexLoadResult loadResult = OfficialDexLoader.load(appContext);
        return new OfficialF2ReflectionRuntime(
            appContext,
            new OfficialF2Reflection(loadResult.getClassLoader())
        );
    }

    @Override
    public void bootstrap(OfficialF2ModuleIdentity identity, int videoCodingType, int packetSize)
        throws Exception {
        Class<?> d2aClass = reflect.initializedType("d2.a");
        reflect.method(d2aClass, "b", Context.class).invoke(null, appContext);

        Class<?> usbModuleInfoClass = reflect.initializedType("com.hik.modulelib.UsbModuleInfo");
        Object usbModuleInfo = newDefaultUsbModuleInfo(usbModuleInfoClass);
        // MainActivity exact setter order before Z2.g.a.c1(...).
        reflect.method(usbModuleInfoClass, "setModuleID", String.class)
            .invoke(usbModuleInfo, identity.getModuleId());
        reflect.method(usbModuleInfoClass, "setSerialNumber", String.class)
            .invoke(usbModuleInfo, identity.getSerialNumber());
        reflect.method(usbModuleInfoClass, "setDevType", int.class)
            .invoke(usbModuleInfo, identity.getDevType());
        reflect.method(usbModuleInfoClass, "setDeviceType", String.class)
            .invoke(usbModuleInfo, identity.getDeviceType());
        reflect.method(usbModuleInfoClass, "setDeviceName", String.class)
            .invoke(usbModuleInfo, identity.getDeviceName());
        reflect.method(usbModuleInfoClass, "setFirmwareVersion", String.class)
            .invoke(usbModuleInfo, identity.getFirmwareVersion());
        reflect.method(usbModuleInfoClass, "setHardwareVersion", String.class)
            .invoke(usbModuleInfo, identity.getHardwareVersion());
        reflect.method(usbModuleInfoClass, "setFirmwareCode", String.class)
            .invoke(usbModuleInfo, identity.getFirmwareCode());

        Class<?> z2gClass = reflect.initializedType("Z2.g");
        Object z2g = reflect.staticField(z2gClass, "a");
        Class<?> usbModuleTypeClass = reflect.initializedType(
            "com.hik.viewercommon.data.bean.UsbModuleType"
        );
        Object f2UsbModuleType = reflect.singleton(
            "com.hik.viewercommon.data.bean.UsbModuleType$F2",
            "INSTANCE"
        );
        reflect.method(z2gClass, "d1", usbModuleTypeClass).invoke(z2g, f2UsbModuleType);
        reflect.method(z2gClass, "D0", usbModuleTypeClass).invoke(z2g, f2UsbModuleType);
        reflect.method(z2gClass, "c1", usbModuleInfoClass).invoke(z2g, usbModuleInfo);

        HikmicroF2ProfileResolution resolution = HikmicroF2ProfileResolver.INSTANCE.resolve(
            identity.getModuleId(),
            identity.getFirmwareVersion()
        );
        HikmicroF2Profile profile = resolution.getProfile();
        if (profile == null) {
            throw new IllegalStateException(
                "Official F2 session profile unresolved: " + resolution.getReason()
            );
        }
        if (videoCodingType != profile.getThermalCoding()
            || !profile.getAllowedPacketSizes().contains(packetSize)) {
            throw new IllegalStateException(
                "Radiometric runtime profile mismatch profile=" + profile.getOfficialClassName()
                    + " coding=" + videoCodingType + " packetSize=" + packetSize
            );
        }
        Class<?> profileClass = reflect.initializedType(profile.getOfficialClassName());
        Object runtimeProfile = profileClass.getDeclaredConstructor().newInstance();
        Class<?> f3kClass = reflect.initializedType("f3.k");
        reflect.method(f3kClass, "d", int.class).invoke(runtimeProfile, videoCodingType);
        if (packetSize > 0) {
            reflect.method(f3kClass, "b", int.class).invoke(runtimeProfile, packetSize);
        }
        Class<?> z2aClass = reflect.initializedType("Z2.a");
        Object z2a = reflect.staticField(z2aClass, "a");
        reflect.method(z2aClass, "u", f3kClass).invoke(z2a, runtimeProfile);
    }

    private Object newDefaultUsbModuleInfo(Class<?> usbModuleInfoClass) throws Exception {
        Class<?> markerClass = reflect.type("kotlin.jvm.internal.DefaultConstructorMarker");
        Constructor<?> constructor = usbModuleInfoClass.getDeclaredConstructor(
            String.class,
            String.class,
            String.class,
            String.class,
            String.class,
            int.class,
            String.class,
            String.class,
            String.class,
            int.class,
            int.class,
            int.class,
            int.class,
            String.class,
            int.class,
            markerClass
        );
        constructor.setAccessible(true);
        // Exact Kotlin default-constructor shape used by MainActivity: mask 16383.
        return constructor.newInstance(
            null,
            null,
            null,
            null,
            null,
            0,
            null,
            null,
            null,
            0,
            0,
            0,
            0,
            null,
            16383,
            null
        );
    }

    @Override
    public OfficialF2ParsedOfflineConfig parseOfflineConfig(OfficialF2ParserCall call)
        throws Exception {
        Class<?> uploadClass = reflect.initializedType(
            call.getVideoCodingType() == 12
                ? "com.hik.f2module.IFR_INFO$USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_12_LITE"
                : "com.hik.f2module.IFR_INFO$USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE"
        );
        Object upload = uploadClass.getDeclaredConstructor().newInstance();
        Class<?> k3bClass = reflect.initializedType("k3.b");
        Object k3b = reflect.staticField(k3bClass, "a");
        Method parse = reflect.method(
            k3bClass,
            "d",
            k3bClass,
            Object.class,
            byte[].class,
            ByteOrder.class,
            int.class,
            Object.class
        );

        // W9 exact callback-head parse: k3.b.d(k3.b.a, upload, head, null, 4, null).
        parse.invoke(
            null,
            k3b,
            upload,
            call.getCallbackHead(),
            call.getByteOrder(),
            call.getDefaultMask(),
            call.getMarker()
        );
        byte[] tempMeasureCfg = byteArrayField(uploadClass, upload, "tempMeasureCfg");
        if (tempMeasureCfg.length == 0) {
            throw new OfficialF2RadiometricException("Official tempMeasureCfg parsed empty");
        }
        byte[] extendGeneralInfo = call.getVideoCodingType() == 12
            ? byteArrayField(uploadClass, upload, "extendGeneralInto")
            : new byte[0];

        Class<?> offlineCfgClass = reflect.initializedType(
            "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG"
        );
        Object offlineCfg = offlineCfgClass.getDeclaredConstructor().newInstance();
        // W9 exact nested parse: k3.b.d(k3.b.a, cfg, tempMeasureCfg, null, 4, null).
        parse.invoke(
            null,
            k3b,
            offlineCfg,
            tempMeasureCfg,
            call.getByteOrder(),
            call.getDefaultMask(),
            call.getMarker()
        );
        if (call.isForcePaletteMode14()) {
            Field paletteMode = offlineCfgClass.getDeclaredField("paletteMode");
            paletteMode.setAccessible(true);
            paletteMode.setByte(offlineCfg, (byte) 14);
        }
        return new OfficialF2ParsedOfflineConfig(offlineCfg, extendGeneralInfo);
    }

    @Override
    public Object createPaletteBean(OfficialF2PaletteSnapshot snapshot) throws Exception {
        if (snapshot == null || !snapshot.isPresent()) {
            return null;
        }
        Class<?> paletteBeanClass = reflect.initializedType(
            "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean"
        );
        Object paletteBean = paletteBeanClass.getDeclaredConstructor().newInstance();
        setIntField(paletteBeanClass, paletteBean, "paletteMode", snapshot.getPaletteMode());
        setIntField(paletteBeanClass, paletteBean, "customPseudoColorHexArrSize", snapshot.getCustomPseudoColorHexArrSize());
        setObjectField(paletteBeanClass, paletteBean, "customPseudoColorHexArr", snapshot.getCustomPseudoColorHexArr());
        setIntField(paletteBeanClass, paletteBean, "pseudoColor", snapshot.getPseudoColor());
        setFloatField(paletteBeanClass, paletteBean, "maxTmp", snapshot.getMaxTmp());
        setFloatField(paletteBeanClass, paletteBean, "minTmp", snapshot.getMinTmp());
        setIntField(paletteBeanClass, paletteBean, "ispMode", snapshot.getIspMode());
        setIntField(paletteBeanClass, paletteBean, "agcMode", snapshot.getAgcMode());
        setFloatField(paletteBeanClass, paletteBean, "wideTempUpThreshold", snapshot.getWideTempUpThreshold());
        setFloatField(paletteBeanClass, paletteBean, "wideTempDownThreshold", snapshot.getWideTempDownThreshold());
        setIntField(paletteBeanClass, paletteBean, "rawGrayMax", snapshot.getRawGrayMax());
        setIntField(paletteBeanClass, paletteBean, "rawGrayMin", snapshot.getRawGrayMin());
        setIntField(paletteBeanClass, paletteBean, "agcGrayMax", snapshot.getAgcGrayMax());
        setIntField(paletteBeanClass, paletteBean, "agcGrayMin", snapshot.getAgcGrayMin());
        setIntField(paletteBeanClass, paletteBean, "colorAlarmMax", snapshot.getColorAlarmMax());
        setIntField(paletteBeanClass, paletteBean, "colorAlarmMin", snapshot.getColorAlarmMin());
        setIntField(paletteBeanClass, paletteBean, "colorAlarm14bitMax", snapshot.getColorAlarm14bitMax());
        setIntField(paletteBeanClass, paletteBean, "colorAlarm14bitMin", snapshot.getColorAlarm14bitMin());
        return paletteBean;
    }

    private static void setIntField(Class<?> owner, Object receiver, String fieldName, int value)
        throws Exception {
        Field field = owner.getDeclaredField(fieldName);
        field.setAccessible(true);
        field.setInt(receiver, value);
    }

    private static void setFloatField(Class<?> owner, Object receiver, String fieldName, float value)
        throws Exception {
        Field field = owner.getDeclaredField(fieldName);
        field.setAccessible(true);
        field.setFloat(receiver, value);
    }

    private static void setObjectField(Class<?> owner, Object receiver, String fieldName, Object value)
        throws Exception {
        Field field = owner.getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(receiver, value);
    }

    @Override
    @SuppressWarnings({"unchecked", "rawtypes"})
    public Object resolveModuleType(OfficialF2ModuleSubtype subtype) throws Exception {
        Class<?> f2ModuleTypeClass = reflect.initializedType(
            "hik.common.yyrj.uicommon.data.ModuleType$F2ModuleType"
        );
        return Enum.valueOf(
            (Class<? extends Enum>) f2ModuleTypeClass.asSubclass(Enum.class),
            subtype.name()
        );
    }

    @Override
    public byte[] renderRadiometricJpeg(OfficialF2RendererCall call) throws Exception {
        Class<?> d3fClass = reflect.initializedType("d3.f");
        Object d3f = reflect.staticField(d3fClass, "a");
        Class<?> offlineCfgClass = reflect.initializedType(
            "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG"
        );
        Class<?> paletteBeanClass = reflect.initializedType(
            "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean"
        );
        Class<?> moduleTypeClass = reflect.initializedType(
            "hik.common.yyrj.uicommon.data.ModuleType"
        );
        Method method = reflect.method(
            d3fClass,
            "e",
            byte[].class,
            Size.class,
            byte[].class,
            byte[].class,
            byte[].class,
            offlineCfgClass,
            byte[].class,
            byte[].class,
            Size.class,
            Size.class,
            File.class,
            int.class,
            float.class,
            float.class,
            boolean.class,
            File.class,
            paletteBeanClass,
            HashMap.class,
            Rect.class,
            Size.class,
            moduleTypeClass
        );
        return (byte[]) reflect.invoke(method, d3f, call.getExactArguments());
    }

    @Override
    public void prepareAnalyzer() throws Exception {
        Class<?> analyzerClass = reflect.initializedType("com.hikvision.microjita.AnalyzerII");
        analyzer = reflect.staticField(analyzerClass, "INSTANCE");
        Class<?> analyzerInfoPicClass = reflect.initializedType(
            "com.hikvision.microjita.bean.AnalyzerInfoPic"
        );
        analyzerInfoPic = analyzerInfoPicClass.getDeclaredConstructor().newInstance();
        analyzerInit = reflect.method(
            analyzerClass,
            "init",
            String.class,
            boolean.class,
            analyzerInfoPicClass,
            byte[].class
        );
        Class<?> measureRuleClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureRule"
        );
        analyzerMeasure = reflect.method(analyzerClass, "measure", measureRuleClass);
        analyzerRelease = reflect.method(analyzerClass, "release");
    }

    @Override
    public boolean initAnalyzer(byte[] radiometricJpeg) throws Exception {
        return (Boolean) reflect.invoke(
            analyzerInit,
            analyzer,
            "",
            false,
            analyzerInfoPic,
            radiometricJpeg
        );
    }

    @Override
    public Object buildMeasureRule(OfficialF2RuleSpec ruleSpec) throws Exception {
        Class<?> d3fClass = reflect.initializedType("d3.f");
        Object d3f = reflect.staticField(d3fClass, "a");
        Class<?> regionTypeClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.RegionType"
        );
        Class<?> regionClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.mRegion"
        );
        Class<?> baseInfoClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.RuleBaseInfo"
        );
        Class<?> expertClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureExpertParams"
        );
        Class<?> coordinateClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.Coordinate2D"
        );
        Class<?> coordinateArrayClass = Array.newInstance(coordinateClass, 0).getClass();
        Method createRule = reflect.method(
            d3fClass,
            "c",
            int.class,
            String.class,
            regionTypeClass,
            regionClass,
            baseInfoClass,
            expertClass,
            coordinateArrayClass
        );

        Object region = regionClass.getDeclaredConstructor().newInstance();
        Object baseInfo = baseInfoClass.getDeclaredConstructor().newInstance();
        Object expert = expertClass.getDeclaredConstructor().newInstance();
        reflect.method(expertClass, "setDefault").invoke(expert);
        String regionField = ruleSpec.getScope() == OfficialF2RuleScope.FULLSCREEN
            ? "RuleTypeFullScreen"
            : "RuleTypeRectangle";
        Object regionType = reflect.staticField(regionTypeClass, regionField);
        Object coordinates = coordinateArray(coordinateClass, ruleSpec);
        return reflect.invoke(
            createRule,
            d3f,
            ruleSpec.getId(),
            ruleSpec.getName(),
            regionType,
            region,
            baseInfo,
            expert,
            coordinates
        );
    }

    private Object coordinateArray(Class<?> coordinateClass, OfficialF2RuleSpec ruleSpec)
        throws Exception {
        Object coordinates = Array.newInstance(coordinateClass, 2);
        Array.set(
            coordinates,
            0,
            coordinate(coordinateClass, ruleSpec.getX0(), ruleSpec.getY0())
        );
        Array.set(
            coordinates,
            1,
            coordinate(coordinateClass, ruleSpec.getX1(), ruleSpec.getY1())
        );
        return coordinates;
    }

    private Object coordinate(Class<?> coordinateClass, int x, int y) throws Exception {
        Object coordinate = coordinateClass.getDeclaredConstructor().newInstance();
        reflect.method(coordinateClass, "setU32X", long.class).invoke(coordinate, (long) x);
        reflect.method(coordinateClass, "setU32Y", long.class).invoke(coordinate, (long) y);
        return coordinate;
    }

    @Override
    public OfficialF2MeasurementD3 measure(Object measureRule) throws Exception {
        Object pair = reflect.invoke(analyzerMeasure, analyzer, measureRule);
        if (pair == null) {
            throw new OfficialF2RadiometricException(
                "Official AnalyzerII.measure returned null pair"
            );
        }
        Method getFirst = pair.getClass().getDeclaredMethod("getFirst");
        Method getSecond = pair.getClass().getDeclaredMethod("getSecond");
        getFirst.setAccessible(true);
        getSecond.setAccessible(true);
        boolean success = Boolean.TRUE.equals(reflect.invoke(getFirst, pair));
        if (!success) {
            return new OfficialF2MeasurementD3(false, null, null, null, 0);
        }
        Object stats = reflect.invoke(getSecond, pair);
        if (stats == null) {
            throw new OfficialF2RadiometricException("Official MeasurementStats was null");
        }
        Class<?> statsClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats"
        );
        Class<?> pointClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementPoint"
        );
        Method getTempD3 = reflect.method(pointClass, "getITemperatured3");
        int max = pointD3(statsClass, stats, "getStruMaxMeasurePt", getTempD3);
        int min = pointD3(statsClass, stats, "getStruMinMeasurePt", getTempD3);
        int center = pointD3(statsClass, stats, "getStruCenMeasurePt", getTempD3);
        int average = (Integer) reflect.invoke(
            reflect.method(statsClass, "getIAvgTemperatured3"),
            stats
        );
        return new OfficialF2MeasurementD3(true, max, min, center, average);
    }

    private int pointD3(Class<?> statsClass, Object stats, String getter, Method getTempD3)
        throws Exception {
        Object point = reflect.invoke(reflect.method(statsClass, getter), stats);
        if (point == null) {
            throw new OfficialF2RadiometricException("Official " + getter + " returned null");
        }
        return (Integer) reflect.invoke(getTempD3, point);
    }

    @Override
    public float intd3ToFloat(int value) throws Exception {
        Class<?> converterClass = reflect.initializedType(
            "com.guardexpert.microsensorsdk.core.util.FloatConverter"
        );
        return (Float) reflect.invoke(
            reflect.method(converterClass, "intd3ToFloat", int.class),
            null,
            value
        );
    }

    @Override
    public void releaseAnalyzer() throws Exception {
        try {
            if (analyzer != null && analyzerRelease != null) {
                reflect.invoke(analyzerRelease, analyzer);
            }
        } finally {
            analyzer = null;
            analyzerInfoPic = null;
            analyzerInit = null;
            analyzerMeasure = null;
            analyzerRelease = null;
        }
    }

    private static byte[] byteArrayField(Class<?> owner, Object receiver, String fieldName)
        throws Exception {
        Field field = owner.getDeclaredField(fieldName);
        field.setAccessible(true);
        byte[] value = (byte[]) field.get(receiver);
        if (value == null) {
            throw new OfficialF2RadiometricException(
                "Official field " + fieldName + " was null"
            );
        }
        return value;
    }

}
