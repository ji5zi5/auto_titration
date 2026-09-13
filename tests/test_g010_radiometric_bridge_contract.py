import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/radiometric/OfficialF2RadiometricBridge.java"
RUNTIME = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/radiometric/OfficialF2ReflectionRuntime.java"
ARTIFACTS = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/OfficialDexArtifacts.java"
RADIOMETRIC_DIR = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/radiometric"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class G010RadiometricBridgeContractTest(unittest.TestCase):
    def test_exact_descriptor_and_argument_count_are_pinned(self):
        src = text(BRIDGE)
        self.assertIn("D3F_E_EXPLICIT_ARGUMENT_COUNT = OfficialF2RendererCall.EXACT_ARGUMENT_COUNT", src)
        self.assertIn("d3.f.e requires exactly 21 arguments", text(RADIOMETRIC_DIR / "OfficialF2RadiometricRuntime.java"))
        self.assertIn("([BLandroid/util/Size;[B[B[BLcom/hik/f2module/IFR_INFO$OFFLINE_TEMP_MEASURE_CFG;", src)
        self.assertIn("Landroid/graphics/Rect;Landroid/util/Size;Lhik/common/yyrj/uicommon/data/ModuleType;)[B", src)
        self.assertEqual(1, src.count("// 1  firJpegData"))
        self.assertEqual(1, src.count("// 21 ModuleType"))

    def test_official_order_has_no_extra_visible_size_or_formula_path(self):
        src = text(BRIDGE)
        ordered = [
            "valid.firJpegData",
            "valid.firJpegSize",
            "valid.visibleJpegData",
            "valid.rawData",
            "valid.rawAppendData",
            "offlineConfig.getOfflineTempMeasureCfg()",
            "extendGeneralInfo",
            "valid.rawAppendLine2",
            "valid.originalSize",
            "valid.visibleSize",
            "valid.calibrationFile",
            "valid.agcMode",
            "valid.maxEnvironmentTemp",
            "valid.minEnvironmentTemp",
            "valid.needsNewOfflineRawPic",
            "valid.ispFile",
            "paletteBean",
            "valid.imageAdjustments",
            "valid.fusionRect",
            "valid.fusionSize",
            "moduleType",
        ]
        last = -1
        body = src[src.index("return new Object[]") : src.index("private static Object paletteArgument")]
        for item in ordered:
            idx = body.index(item)
            self.assertGreater(idx, last, item)
            last = idx
        self.assertNotIn("visibleOutputSize", src)
        self.assertNotIn("displaySize", src)

    def test_child_loader_analyzer_and_release_contract_are_static_pinned(self):
        runtime = text(RUNTIME)
        bridge = text(BRIDGE)
        for needle in [
            "OfficialDexLoader.load(appContext)",
            "com.hikvision.microjita.AnalyzerII",
            "com.hikvision.microjita.bean.AnalyzerInfoPic",
            "\"\",\n            false,\n            analyzerInfoPic",
            "releaseAnalyzer()",
            "com.guardexpert.microsensorsdk.core.util.FloatConverter",
            "intd3ToFloat",
        ]:
            self.assertTrue(needle in runtime or needle in bridge, needle)
        self.assertIn("finally {", bridge)
        self.assertIn("analyzerPrepared && runtime != null", bridge)

    def test_palette_snapshot_contract_and_no_fake_celsius_matrix(self):
        joined = "\n".join(text(p) for p in RADIOMETRIC_DIR.glob("*.java"))
        bridge = text(BRIDGE)
        self.assertIn("PALETTE_SNAPSHOT_MESSAGE", bridge)
        self.assertIn("PreviewManagerII.Q() returned null", bridge)
        self.assertIn("snapshot == null", bridge)
        self.assertIn("AbsenceProof.PREVIEW_MANAGER_Q_RETURNED_NULL", bridge)
        self.assertIn("return null;", bridge)
        self.assertIn("runtime.createPaletteBean(snapshot)", bridge)
        self.assertIn("Present PaletteBean snapshot must be rebuilt child-side", bridge)
        self.assertIn("paletteBean,                       // 17 nullable PaletteBean from PreviewManagerII.Q snapshot", bridge)
        self.assertNotIn("CUSTOM_PALETTE_UNSUPPORTED_MESSAGE", joined)
        self.assertNotIn("officialDefaultPaletteOnly", joined)
        for forbidden in ["getTempsVect", "grayToTemperature", "temperatureToGray", "temperatureMatrix", "fullMatrix"]:
            self.assertNotIn(forbidden, joined)

    def test_required_official_child_classes_are_registered(self):
        artifacts = text(ARTIFACTS)
        for class_name in [
            "d3.f",
            "d2.a",
            "k3.b",
            "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG",
            "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
            "hik.common.yyrj.uicommon.data.ModuleType$F2ModuleType",
            "com.hikvision.microjita.AnalyzerII",
            "com.guardexpert.microsensorsdk.core.util.FloatConverter",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats",
        ]:
            self.assertIn(class_name, artifacts)


if __name__ == "__main__":
    unittest.main()
