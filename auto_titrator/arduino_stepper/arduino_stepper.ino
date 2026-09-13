#include "command_parser.h"

const int STEP_PIN = 2;
const int DIR_PIN = 3;
const int ENABLE_PIN = 4;

// Absolute safety ceiling in milliseconds. This is a time bound, not a pump
// calibration or a claimed volume. Host software may arm a shorter deadline
// with "G <milliseconds>\\n", but firmware never accepts a longer one.
const unsigned long ABSOLUTE_MAX_RUN_TIME_MS = 120000UL;
const unsigned long PROTOCOL_UNSIGNED_LONG_MAX = 4294967295UL;
const unsigned long MAX_PULSE_STEPS = 200UL;
const unsigned long DEFAULT_STEP_RATE = 100UL;
const unsigned long MIN_STEP_RATE = 1UL;
const unsigned long MAX_STEP_RATE = 100UL;
const byte COMMAND_BUFFER_SIZE = 32;
// Preserve the original working direction contract: b dispenses, a retracts.
// STEP uses the same b direction as continuous dispensing.
const char PULSE_DIRECTION = 'b';

char state = 'c'; // a=좌회전, b=우회전, p=펄스, c/STOP=정지
char commandBuffer[COMMAND_BUFFER_SIZE];
byte commandLength = 0;
bool discardingOverflowCommand = false;
bool overflowCommandIsRate = false;
bool discardingInterruptedCommand = false;
unsigned long runStartedMs = 0;
unsigned long activeRunLimitMs = 0;
unsigned long armedRunLimitMs = 0;
unsigned long pulseStepsRemaining = 0;
unsigned long pendingStepRate = DEFAULT_STEP_RATE;
unsigned long activeStepRate = DEFAULT_STEP_RATE;
unsigned long lastStepEdgeMicros = 0;
bool stepSignalHigh = false;

void stopPump(const char* reason) {
  state = 'c';
  activeRunLimitMs = 0;
  armedRunLimitMs = 0;
  pulseStepsRemaining = 0;
  pendingStepRate = DEFAULT_STEP_RATE;
  activeStepRate = DEFAULT_STEP_RATE;
  stepSignalHigh = false;
  digitalWrite(STEP_PIN, LOW);
  digitalWrite(ENABLE_PIN, HIGH);
  Serial.print("PUMP STOPPED ");
  Serial.println(reason);
}

void startPump(char direction) {
  // Plain legacy a/b remains operator-controlled and runs until c. Automatic
  // mode first sends G, so only guarded runs receive a firmware deadline.
  activeRunLimitMs = armedRunLimitMs;
  armedRunLimitMs = 0;
  pulseStepsRemaining = 0;
  activeStepRate = activeRunLimitMs > 0 ? pendingStepRate : DEFAULT_STEP_RATE;
  pendingStepRate = DEFAULT_STEP_RATE;
  runStartedMs = millis();
  lastStepEdgeMicros = micros();
  stepSignalHigh = false;
  digitalWrite(STEP_PIN, LOW);
  state = direction;
  digitalWrite(DIR_PIN, direction == 'a' ? LOW : HIGH);
  digitalWrite(ENABLE_PIN, LOW);
  Serial.print("PUMP RUNNING ");
  Serial.print(direction);
  Serial.print(' ');
  Serial.println(activeRunLimitMs);
}

void acknowledgeRunningPump() {
  Serial.print("PUMP RUNNING ");
  Serial.print(state);
  Serial.print(' ');
  Serial.println(activeRunLimitMs);
}

void startPulse(unsigned long stepCount) {
  activeRunLimitMs = 0;
  armedRunLimitMs = 0;
  pulseStepsRemaining = stepCount;
  pendingStepRate = DEFAULT_STEP_RATE;
  activeStepRate = DEFAULT_STEP_RATE;
  state = 'p';
  digitalWrite(DIR_PIN, PULSE_DIRECTION == 'a' ? LOW : HIGH);
  digitalWrite(ENABLE_PIN, LOW);
  Serial.print("STEP ACCEPTED ");
  Serial.println(stepCount);
}

void rejectPulse() {
  state = 'c';
  activeRunLimitMs = 0;
  armedRunLimitMs = 0;
  pulseStepsRemaining = 0;
  digitalWrite(ENABLE_PIN, HIGH);
  Serial.println("STEP REJECTED");
}

void processRateCommand(const char* valueStart) {
  unsigned long requestedRate = 0;
  if (state != 'c'
      || !parseBoundedUnsignedLong(valueStart, MAX_STEP_RATE, &requestedRate)
      || requestedRate < MIN_STEP_RATE) {
    // Rejection must not stop motion, refresh its start time, alter its active
    // deadline, or replace a previously accepted pending rate.
    Serial.println("RATE REJECTED");
    return;
  }

  pendingStepRate = requestedRate;
  Serial.print("RATE ACCEPTED ");
  Serial.println(requestedRate);
}

void processLineCommand() {
  commandBuffer[commandLength] = '\0';
  if (strcmp(commandBuffer, "STOP") == 0) {
    stopPump("COMMAND");
  } else if (strcmp(commandBuffer, "RATE") == 0) {
    processRateCommand("");
  } else if (commandLength >= 5 && strncmp(commandBuffer, "RATE ", 5) == 0) {
    processRateCommand(commandBuffer + 5);
  } else if (commandLength > 5 && strncmp(commandBuffer, "STEP ", 5) == 0) {
    const char* valueStart = commandBuffer + 5;
    unsigned long requestedSteps = 0;
    if (!parseBoundedUnsignedLong(valueStart, MAX_PULSE_STEPS, &requestedSteps)
        || requestedSteps == 0) {
      rejectPulse();
    } else {
      startPulse(requestedSteps);
    }
  } else if (commandLength > 2 && commandBuffer[0] == 'G' && commandBuffer[1] == ' ') {
    const char* valueStart = commandBuffer + 2;
    unsigned long requestedMs = 0;
    if (!parseBoundedUnsignedLong(
            valueStart, PROTOCOL_UNSIGNED_LONG_MAX, &requestedMs)
        || requestedMs == 0) {
      armedRunLimitMs = 0;
      Serial.println("GUARD REJECTED");
    } else {
      armedRunLimitMs = min(requestedMs, ABSOLUTE_MAX_RUN_TIME_MS);
      Serial.print("GUARD ARMED ");
      Serial.println(armedRunLimitMs);
    }
  } else if (strcmp(commandBuffer, "Q") == 0) {
    Serial.print("PUMP FW 2 PULSE ");
    Serial.print(PULSE_DIRECTION);
    Serial.println(" GUARD 1");
  } else if (strcmp(commandBuffer, "V") == 0) {
    Serial.println("PUMP SPEED 1");
  } else if (commandLength > 0) {
    Serial.println("COMMAND REJECTED");
  }
  commandLength = 0;
}

bool bufferedCommandIsRate() {
  return commandLength >= 4 && strncmp(commandBuffer, "RATE", 4) == 0;
}

void readSerialCommands() {
  while (Serial.available()) {
    char cmd = Serial.read();

    // The legacy emergency-stop byte always has priority, including during a
    // partial or overflowed line command. Therefore malformed RATE text that
    // contains a literal lowercase c is intentionally treated as STOP.
    if (cmd == 'c') {
      const bool interruptedLine = commandLength > 0
          || discardingOverflowCommand
          || discardingInterruptedCommand;
      commandLength = 0;
      discardingOverflowCommand = false;
      overflowCommandIsRate = false;
      stopPump("COMMAND");
      discardingInterruptedCommand = interruptedLine;
      continue;
    }

    if (discardingInterruptedCommand) {
      if (cmd == '\n' || cmd == '\r') {
        discardingInterruptedCommand = false;
      }
      continue;
    }

    if (discardingOverflowCommand) {
      if (cmd == '\n' || cmd == '\r') {
        Serial.println(overflowCommandIsRate ? "RATE REJECTED" : "COMMAND REJECTED");
        discardingOverflowCommand = false;
        overflowCommandIsRate = false;
      }
      continue;
    }

    if ((cmd == 'a' || cmd == 'b') && commandLength == 0) {
      if (state == cmd) {
        // A duplicated HTTP/serial start must be idempotent and must never
        // refresh runStartedMs or extend the active safety deadline.
        acknowledgeRunningPump();
      } else if (state == 'a' || state == 'b' || state == 'p') {
        // Direction changes require an explicit stop and a fresh guarded run.
        stopPump("START_REJECTED_ACTIVE");
      } else {
        startPump(cmd);
      }
    } else if (cmd == '\n' || cmd == '\r') {
      if (commandLength > 0) {
        processLineCommand();
      }
    } else if (commandLength < COMMAND_BUFFER_SIZE - 1) {
      commandBuffer[commandLength++] = cmd;
    } else {
      overflowCommandIsRate = bufferedCommandIsRate();
      discardingOverflowCommand = true;
      commandLength = 0;
    }
  }
}

void performStep() {
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(5000);  // 속도 조절
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(5000);
}

void performSlowStep() {
  const unsigned long halfPeriodMicros = 500000UL / activeStepRate;
  const unsigned long nowMicros = micros();
  if ((unsigned long)(nowMicros - lastStepEdgeMicros) < halfPeriodMicros) {
    return;
  }

  stepSignalHigh = !stepSignalHigh;
  digitalWrite(STEP_PIN, stepSignalHigh ? HIGH : LOW);
  lastStepEdgeMicros = nowMicros;
}

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENABLE_PIN, OUTPUT);

  digitalWrite(ENABLE_PIN, HIGH); // 처음엔 정지

  Serial.begin(9600);
}

void loop() {
  readSerialCommands();

  if ((state == 'a' || state == 'b')
      && activeRunLimitMs > 0
      && (unsigned long)(millis() - runStartedMs) >= activeRunLimitMs) {
    stopPump("ABSOLUTE_TIMEOUT");
  }

  if (state == 'p') {
    performStep();
    pulseStepsRemaining--;
    if (pulseStepsRemaining == 0) {
      stopPump("PULSE_COMPLETE");
    }
  } else if (state == 'a' || state == 'b') {
    if (activeStepRate == DEFAULT_STEP_RATE) {
      // Keep the original known-working full-speed pulse timing unchanged.
      performStep();
    } else {
      // Slow guarded dosing remains responsive to c/STOP between pulse edges.
      performSlowStep();
    }
  }
}
