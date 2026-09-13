# 웹 펌프 제어용 Arduino 펌웨어

웹의 `밀기`, `되감기`, `정지` 버튼은 모터 동작뿐 아니라 Arduino의 확인 응답도 검사한다.

Arduino IDE에서 이 폴더의 `arduino_stepper.ino`를 열어 업로드한다. 같은 폴더의
`command_parser.h`도 함께 있어야 한다.

## Serial Monitor 확인

- 통신 속도: `9600 baud`
- `c` 전송: `PUMP STOPPED COMMAND`
- `b` 전송: `PUMP RUNNING b 0` — 기존과 같은 밀기 방향, `c`까지 계속 동작
- `a` 전송: `PUMP RUNNING a 0` — 기존과 같은 되감기 방향, `c`까지 계속 동작
- `STEP 5` 전송: `STEP ACCEPTED 5` 뒤 `PUMP STOPPED PULSE_COMPLETE` — `b` 방향 5스텝

확인 뒤에는 Serial Monitor를 닫아야 Windows 수집기가 COM 포트를 사용할 수 있다.

`arduino_stepper_original_working/arduino_stepper_original_working.ino`는 모터의 기본
회전 시험용이다. `a`, `b`, `c`에 따라 모터는 움직이지만 확인 응답과 펌웨어 안전 제한이
없으므로 웹 제어에는 사용할 수 없다.
