import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = ROOT / ".omx/analysis/microjita-androguard-exact"
BRIDGE = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/radiometric/OfficialF2RadiometricBridge.java"
RUNTIME = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/radiometric/OfficialF2ReflectionRuntime.java"
RUNTIME_CONTRACT = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/radiometric/OfficialF2RadiometricRuntime.java"
ARTIFACTS = ROOT / "mobile/android/app/src/main/java/kr/auto/titration/mobile/thermal/officialdex/OfficialDexArtifacts.java"

D3F_E_AG = OFFICIAL / "d3/f/f e ([BSize[B[B[BIFR_INFO$OFFLINE_TEMP_MEASURE_CFG[B[BSizeSizeFileIFFZFilePaletteBeanHashMapRectSizeModuleType)[B.ag"
ANALYZER_MEASURE_AG = OFFICIAL / "com/hikvision/microjita/AnalyzerII/AnalyzerII measure (MeasureRule)Pair.ag"
ANALYZER_RELEASE_AG = OFFICIAL / "com/hikvision/microjita/AnalyzerII/AnalyzerII release ()V.ag"
FLOAT_CONVERTER_AG = OFFICIAL / "com/hikvision/microjita/util/FloatConverterII/FloatConverterII intd3ToFloat (J)F.ag"
MICROJITA_MEASURE_AG = OFFICIAL / "com/guardexpert/microsensorsdk/MicroJITA/MicroJITA measure (MeasurementStatsMeasureRuleMicroSmartSensorDataExtension$JPEG)Z.ag"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def official_parameter_types(ag_text: str) -> list[str]:
    params = []
    for line in ag_text.splitlines():
        match = re.match(r"# - v\d+:(.+)$", line.strip())
        if match:
            params.append(match.group(1))
    return params


def production_renderer_argument_comments() -> list[str]:
    src = text(BRIDGE)
    body = src[src.index("return new Object[]") : src.index("private static Object paletteArgument")]
    comments = []
    for line in body.splitlines():
        if "//" in line:
            comments.append(line.split("//", 1)[1].strip())
    return comments


class G009OfficialDescriptorContractTests(unittest.TestCase):
    def test_d3f_e_descriptor_is_parsed_from_official_ag_and_matches_reflection_contract(self):
        ag = text(D3F_E_AG)
        params = official_parameter_types(ag)
        self.assertEqual(21, len(params))
        self.assertEqual(
            [
                "byte[]",
                "android.util.Size",
                "byte[]",
                "byte[]",
                "byte[]",
                "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG",
                "byte[]",
                "byte[]",
                "android.util.Size",
                "android.util.Size",
                "java.io.File",
                "int",
                "float",
                "float",
                "boolean",
                "java.io.File",
                "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
                "java.util.HashMap",
                "android.graphics.Rect",
                "android.util.Size",
                "hik.common.yyrj.uicommon.data.ModuleType",
            ],
            params,
        )
        runtime = text(RUNTIME)
        for token in [
            'reflect.initializedType("d3.f")',
            'reflect.method(\n            d3fClass,\n            "e"',
            "offlineCfgClass",
            "paletteBeanClass",
            "moduleTypeClass",
        ]:
            self.assertIn(token, runtime)
        comments = production_renderer_argument_comments()
        self.assertEqual(21, len(comments))
        self.assertTrue(comments[0].startswith("1  firJpegData: [B"))
        self.assertTrue(comments[20].startswith("21 ModuleType"))
        self.assertIn("EXACT_ARGUMENT_COUNT = 21", text(RUNTIME_CONTRACT))

    def test_analyzer_measure_release_and_float_converter_are_artifact_driven(self):
        analyzer_measure = text(ANALYZER_MEASURE_AG)
        self.assertIn("new-instance         v0, Lcom/guardexpert/microsensorsdk/core/microsmartsensordata/MeasurementStats;", analyzer_measure)
        self.assertIn("invoke-static        v0, v8, v3, Lcom/guardexpert/microsensorsdk/MicroJITA;->measure", analyzer_measure)
        self.assertIn("new-instance         v8, Lkotlin/Pair;", analyzer_measure)
        self.assertIn("invoke-direct        v8, v1, v0, Lkotlin/Pair;-><init>", analyzer_measure)

        microjita_measure = text(MICROJITA_MEASURE_AG)
        self.assertIn("MicroJITASWIG;->measure", microjita_measure)
        self.assertIn("return               v0", microjita_measure)

        analyzer_release = text(ANALYZER_RELEASE_AG)
        self.assertIn("MicroJITA;->destroy", analyzer_release)
        self.assertIn("sput-object          v0, Lcom/hikvision/microjita/AnalyzerII;->struIRImage", analyzer_release)

        converter = text(FLOAT_CONVERTER_AG)
        self.assertRegex(converter, r"long-to-float\s+v1, v1")
        self.assertRegex(converter, r"div-float/2addr\s+v1, v2")
        self.assertRegex(converter, r"return\s+v1")

    def test_production_runtime_uses_official_measurementstats_and_floatconverter_methods(self):
        runtime = text(RUNTIME)
        for token in [
            'reflect.method(analyzerClass, "measure", measureRuleClass)',
            'reflect.method(analyzerClass, "release")',
            '"com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats"',
            '"com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementPoint"',
            'reflect.method(pointClass, "getITemperatured3")',
            'reflect.method(statsClass, "getIAvgTemperatured3")',
            '"com.guardexpert.microsensorsdk.core.util.FloatConverter"',
            'reflect.method(converterClass, "intd3ToFloat", int.class)',
        ]:
            self.assertIn(token, runtime)

    def test_required_official_classes_include_descriptor_surface(self):
        artifacts = text(ARTIFACTS)
        for class_name in [
            "d3.f",
            "com.hik.f2module.IFR_INFO$OFFLINE_TEMP_MEASURE_CFG",
            "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
            "hik.common.yyrj.uicommon.data.ModuleType$F2ModuleType",
            "com.hikvision.microjita.AnalyzerII",
            "com.guardexpert.microsensorsdk.core.util.FloatConverter",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementPoint",
        ]:
            self.assertIn(class_name, artifacts)


if __name__ == "__main__":
    unittest.main()
