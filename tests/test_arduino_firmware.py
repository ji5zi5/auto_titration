from pathlib import Path
import unittest


FIRMWARE_PATH = Path("auto_titrator/arduino_stepper/arduino_stepper.ino")


class ArduinoFirmwareTests(unittest.TestCase):
    def test_firmware_file_exists(self):
        self.assertTrue(FIRMWARE_PATH.exists())

    def test_actual_pump_firmware_is_simple_abc_control(self):
        source = FIRMWARE_PATH.read_text(encoding="utf-8")

        for expected in [
            "const int STEP_PIN = 2;",
            "const int DIR_PIN = 3;",
            "const int ENABLE_PIN = 4;",
            "Serial.begin(9600)",
            "cmd == 'a'",
            "cmd == 'b'",
            "cmd == 'c'",
            "digitalWrite(DIR_PIN, LOW)",
            "digitalWrite(DIR_PIN, HIGH)",
            "delayMicroseconds(5000)",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, source)


    def test_firmware_matches_original_working_abc_sketch_without_volume_math(self):
        source = FIRMWARE_PATH.read_text(encoding="utf-8")

        for expected in [
            "char state = 'c'; // a=좌회전, b=우회전, c=정지",
            "digitalWrite(ENABLE_PIN, HIGH); // 처음엔 정지",
            "digitalWrite(DIR_PIN, LOW);   // 좌회전",
            "digitalWrite(DIR_PIN, HIGH);  // 우회전",
            "digitalWrite(ENABLE_PIN, HIGH); // 정지",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, source)

        for removed in [
            "SYRINGE_INNER_DIAMETER_MM",
            "LEAD_SCREW_MM_PER_REV",
            "ML_PER_STEP",
            "stepCount",
            "cmd == 's'",
            "cmd == 'r'",
            "printStatus",
            "steps=",
            " ml=",
        ]:
            with self.subTest(removed=removed):
                self.assertNotIn(removed, source)

    def test_firmware_has_no_debug_echo_or_extra_status_protocol(self):
        source = FIRMWARE_PATH.read_text(encoding="utf-8")

        for removed in [
            "READY 9600",
            "Serial.print(\"CMD \")",
            "UNKNOWN",
        ]:
            with self.subTest(removed=removed):
                self.assertNotIn(removed, source)

    def test_pump_firmware_does_not_keep_overbuilt_serial_protocol(self):
        source = FIRMWARE_PATH.read_text(encoding="utf-8")

        for removed in [
            "RUN_RATE",
            "SET_ML_PER_STEP",
            "SET_STEPS_PER_ML",
            "SET_MAX_TOTAL_STEPS",
            "SET_MAX_VOLUME_ML",
            "EMERGENCY_STOP",
            "CLEAR_FAULT",
            "parsePositiveFloat",
            "String line",
        ]:
            with self.subTest(removed=removed):
                self.assertNotIn(removed, source)

    def test_simple_firmware_stays_short_enough_for_manual_explanation(self):
        line_count = len(FIRMWARE_PATH.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(line_count, 120)


if __name__ == "__main__":
    unittest.main()
