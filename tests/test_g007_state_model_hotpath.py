from pathlib import Path
import unittest

ROOT = Path("mobile/android/app/src/main/java")


class G007StateModelHotPathTests(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_i3_c_only_dispatches_official_private_or_upload_stream_info_and_has_no_raw_passthrough(self):
        text = self.read("i3/b.kt")
        c_body = text.split("override fun c(", 1)[1].split("@Suppress", 1)[0]
        self.assertIn("is PrivateStreamInfo -> d(streamInfo.a(), callback)", c_body)
        self.assertIn("is UploadStreamInfo -> e(streamInfo.a(), callback)", c_body)
        self.assertNotIn("else ->", c_body)
        self.assertNotIn("rawAppendData)", c_body)

    def test_i3_raw_append_width_uses_official_profile_size_chain_without_fallback(self):
        text = self.read("i3/b.kt")
        self.assertNotIn("rawAppendWidth", text)
        self.assertEqual(text.count("previewInfoData, Z2.a.a.p().g().width)"), 2)
        self.assertNotIn("runCatching", text)
        self.assertNotIn("?: 192", text)
        self.assertNotIn("getOrDefault", text)

    def test_z2_state_models_have_official_defaults_and_no_host_test_setters(self):
        z2a = self.read("Z2/a.java")
        z2g = self.read("Z2/g.kt")
        for text in (z2a, z2g):
            self.assertNotIn("ForHostTest", text)
            self.assertNotIn("setDefaults", text)
        self.assertNotIn("rawAppendWidth", self.read("f3/g.kt"))
        self.assertIn("private boolean q = false", z2a)
        self.assertIn("private f3.k p = new f3.a()", z2a)
        self.assertIn("public final f3.k p(){return p;}", z2a)
        self.assertIn("public final void u(f3.k profile)", z2a)
        self.assertIn("public final boolean q(){return q;}", z2a)
        for token in [
            "private var b: Boolean = false",
            "private var c: Boolean = false",
            "private var d: Boolean = false",
            "private var e: Boolean? = null",
            "private var f: UsbModuleType = UsbModuleType.NONE",
            "private var g: UsbModuleType = UsbModuleType.NONE",
            "private var o: UsbModuleInfo = UsbModuleInfo()",
            "private var C: ThermometryBasicBean = ThermometryBasicBean()",
            "private var D: Size = Size(0, 0)",
            "private var F: ByteArray = ByteArray(0)",
            "private var I: String = \"80\"",
            "private val M: MutableList<SceneModeBean> = ArrayList()",
            "private val N: MutableList<SceneModeBean> = ArrayList()",
            "private val O: MutableList<SceneModeBean> = ArrayList()",
            "fun v(): Boolean = c",
            "fun M(): Int = L",
            "fun U(): UsbModuleInfo = o",
            "fun K(): ThermometryBasicBean = C",
        ]:
            self.assertIn(token, z2g)

    def test_z3_c_uses_official_singleton_graph_and_no_host_stamp_accessor(self):
        z3c = self.read("z3/c.kt")
        self.assertNotIn("ForHostTest", z3c)
        self.assertNotIn("lastFrameNumStamp", z3c)
        for token in [
            "private var b: Bitmap? = null",
            "private var c: HCUSBCameraSDKBy.IFR_POINT? = null",
            "private lateinit var d: x3.a",
            "private lateinit var e: w3.k",
            "private lateinit var f: w3.k",
            "private var g: y3.b? = null",
            "private var j: Float = 30.0f",
            "private var k: Float = 10.0f",
            "@Volatile private var m: Int = -1",
            "@Volatile private var n: Int = -1",
            "private var q: Boolean = true",
            "private var u: Int = 960",
            "private var v: Int = 720",
            "fun r(frameNumStamp: Int) { m = frameNumStamp }",
            "fun e(): Int = m",
        ]:
            self.assertIn(token, z3c)

    def test_f3_profile_contract_and_j_hierarchy_match_dex(self):
        contract = self.read("f3/k.kt")
        for signature in [
            "fun a(): Size",
            "fun b(value: Int)",
            "fun c(): Size",
            "fun d(value: Int)",
            "fun e(): List<Int>",
            "fun f(): Int",
            "fun g(): Size",
            "fun h(value: Boolean)",
            "fun i(): Boolean",
            "fun j(): Size",
            "fun k(): Int",
            "fun l(): Int",
            "fun m(): Boolean",
            "fun n(): Boolean",
            "fun o(value: Int)",
        ]:
            self.assertIn(signature, contract)
        self.assertIn("open class i : k", self.read("f3/i.kt"))
        self.assertIn("open class f : i()", self.read("f3/f.kt"))
        self.assertIn("open class g : f()", self.read("f3/g.kt"))
        self.assertIn("open class h : g()", self.read("f3/h.kt"))
        self.assertIn("class j : h()", self.read("f3/j.kt"))

    def test_module_type_uses_nested_official_enum_identity_model_with_compat_aliases_only(self):
        text = self.read("hik/common/yyrj/uicommon/data/ModuleType.kt")
        self.assertIn("interface ModuleType", text)
        self.assertIn("enum class F1ModuleType : ModuleType { F1, F1B }", text)
        self.assertIn("enum class F2ModuleType : ModuleType { F2, F23, F2V2, F0 }", text)
        self.assertIn("typealias ModuleTypeF2ModuleType = ModuleType.F2ModuleType", text)
        self.assertNotIn("enum class ModuleTypeF2ModuleType", text)

    def test_l5_branch_table_contains_official_warning_and_clamp_boundaries(self):
        text = self.read("L5/d.kt")
        for token in ["marker(value, -30f, -25f, 153f, 160f)", "marker(value, -30f, 95f, 663f, 685f)", "marker(value, -30f, 95f, 408f, 420f)", "marker(value, -30f, 95f, 357f, 370f)", "value < lowWarn && value >= lowLimit -> '~'", "value > highWarn && value <= highLimit -> '~'"]:
            self.assertIn(token, text)

    def test_official_beans_expose_required_constructor_field_getter_shapes(self):
        usb = self.read("com/hik/modulelib/UsbModuleInfo.kt")
        for field in ["deviceID", "deviceName", "deviceType", "hardwareVersion", "firmwareVersion", "devType", "moduleID", "serialNumber", "firmwareCode", "languageType", "deviceClass", "manufacturer", "deviceAssembleType", "secondHardwareVersion"]:
            self.assertIn(f"private var {field}", usb)
        for getter in ["getDeviceName", "getModuleID", "getSerialNumber"]:
            self.assertIn(f"fun {getter}()", usb)
        thermo = self.read("com/hik/modulelib/bean/ThermometryBasicBean.kt")
        for field in ["enableCenterTem", "enableHighTem", "enableLowTem", "enableAvgTem", "reflectiveTemp", "reflectiveEnable", "temperatureRange", "temperatureUnit", "emissivity", "distance", "alert", "alarm", "alarmEnable", "externalOpticsTransmit", "externalOpticsWindowCorrection", "calibrationCoefficientEnabled", "calibrationCoefficient", "thermometryStreamOverlay", "thermometryInfoDisplayPosition"]:
            self.assertIn(f"private var {field}", thermo)
        for getter in ["getEnableHighTem", "getEnableLowTem", "getEnableAvgTem", "getEnableCenterTem"]:
            self.assertIn(f"fun {getter}(): Boolean", thermo)
        self.assertIn("private var externalOpticsWindowCorrection: Int = 1100", thermo)
        self.assertIn("private var calibrationCoefficient: Int = 2", thermo)
        temp = self.read("com/hik/viewercommon/data/bean/TempCallbackBean.kt")
        osd = self.read("com/hik/viewercommon/data/bean/OsdBgCallbackBean.kt")
        self.assertIn("private var rawWithAppendData: ByteArray = ByteArray(0)", temp)
        self.assertIn("fun getRawWithAppendData(): ByteArray", temp)
        self.assertIn("private val kLongestSize: Float", osd)
        self.assertIn("fun getKLongestSize(): Float", osd)

    def test_d3b_uses_official_append_offsets_and_profile_packet_sizes_are_locked(self):
        d3b = self.read("d3/b.kt")
        for token in ["append.copyOfRange(0, rawWidth * 2)", "append.copyOfRange(rawWidth * 2, rawWidth * 4)", "first.copyOfRange(262, 264)", "first.copyOfRange(264, 266)", "first.copyOfRange(2, 4)", "first.copyOfRange(40, 42)", "first.copyOfRange(10, 12)", "first.copyOfRange(26, 28)", "second.copyOfRange(16, 20)"]:
            self.assertIn(token, d3b)
        f3j = self.read("f3/j.kt")
        self.assertIn("203720", f3j)
        self.assertIn("183496", f3j)


if __name__ == "__main__":
    unittest.main()
