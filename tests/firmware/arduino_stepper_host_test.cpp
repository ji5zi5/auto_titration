#include <deque>
#include <iostream>
#include <sstream>
#include <string>
#include <cstring>
#include <cstdlib>

typedef unsigned char byte;

const int LOW = 0;
const int HIGH = 1;
const int OUTPUT = 1;

unsigned long fakeMillis = 0;
unsigned long fakeMicros = 0;
unsigned long delayCallCount = 0;
int pinValues[16] = {};

unsigned long millis() { return fakeMillis; }
unsigned long micros() { return fakeMicros; }
void pinMode(int, int) {}
void digitalWrite(int pin, int value) { pinValues[pin] = value; }
void delayMicroseconds(unsigned long duration) {
  ++delayCallCount;
  fakeMicros += duration;
  fakeMillis = fakeMicros / 1000UL;
}

template <typename T>
T min(T left, T right) {
  return left < right ? left : right;
}

struct FakeSerial {
  std::deque<char> input;
  std::ostringstream output;

  void begin(unsigned long) {}
  int available() const { return static_cast<int>(input.size()); }
  char read() {
    const char value = input.front();
    input.pop_front();
    return value;
  }
  void print(const char* value) { output << value; }
  void print(char value) { output << value; }
  void print(unsigned long value) { output << value; }
  void println(const char* value) { output << value << '\n'; }
  void println(unsigned long value) { output << value << '\n'; }

  void feed(const std::string& value) {
    input.insert(input.end(), value.begin(), value.end());
  }
  std::string takeOutput() {
    const std::string value = output.str();
    output.str("");
    output.clear();
    return value;
  }
};

FakeSerial Serial;

#include "auto_titrator/arduino_stepper/arduino_stepper.ino"

#define CHECK(condition) \
  do { \
    if (!(condition)) { \
      std::cerr << "check failed at line " << __LINE__ << ": " #condition "\n"; \
      return 1; \
    } \
  } while (false)

void feedAndRead(const std::string& command) {
  Serial.feed(command);
  readSerialCommands();
}

int main() {
  setup();

  feedAndRead("Q\nV\n");
  CHECK(Serial.takeOutput() == "PUMP FW 2 PULSE b GUARD 1\nPUMP SPEED 1\n");

  feedAndRead("RATE 1\nRATE 100\n");
  CHECK(Serial.takeOutput() == "RATE ACCEPTED 1\nRATE ACCEPTED 100\n");
  CHECK(pendingStepRate == 100UL);

  feedAndRead("RATE 20\n");
  CHECK(pendingStepRate == 20UL);
  CHECK(Serial.takeOutput() == "RATE ACCEPTED 20\n");
  feedAndRead("G 4294967295\nG 4294967296\n");
  CHECK(Serial.takeOutput() == "GUARD ARMED 120000\nGUARD REJECTED\n");
  CHECK(armedRunLimitMs == 0UL);
  feedAndRead("G 500\nb");
  CHECK(state == 'b');
  CHECK(activeStepRate == 20UL);
  CHECK(activeRunLimitMs == 500UL);
  CHECK(pendingStepRate == DEFAULT_STEP_RATE);
  Serial.takeOutput();

  const unsigned long originalStart = runStartedMs;
  const unsigned long originalDeadline = activeRunLimitMs;
  delayCallCount = 0;
  const unsigned long slowEdgeStart = lastStepEdgeMicros;
  fakeMicros = slowEdgeStart + 24999UL;
  loop();
  CHECK(delayCallCount == 0UL);
  CHECK(pinValues[STEP_PIN] == LOW);
  fakeMicros = slowEdgeStart + 25000UL;
  loop();
  CHECK(pinValues[STEP_PIN] == HIGH);
  fakeMicros = slowEdgeStart + 49999UL;
  loop();
  CHECK(pinValues[STEP_PIN] == HIGH);
  fakeMicros = slowEdgeStart + 50000UL;
  loop();
  CHECK(pinValues[STEP_PIN] == LOW);

  fakeMillis = 10UL;
  feedAndRead("b");
  CHECK(runStartedMs == originalStart);
  CHECK(activeRunLimitMs == originalDeadline);
  Serial.takeOutput();

  feedAndRead("RATE 30\nRATE 999999999999999999999999999999999999999\n");
  CHECK(Serial.takeOutput() == "RATE REJECTED\nRATE REJECTED\n");
  CHECK(state == 'b');
  CHECK(activeStepRate == 20UL);
  CHECK(runStartedMs == originalStart);
  CHECK(activeRunLimitMs == originalDeadline);

  feedAndRead("RATE 2cb\n");
  CHECK(Serial.takeOutput() == "PUMP STOPPED COMMAND\n");
  CHECK(state == 'c');
  CHECK(pinValues[ENABLE_PIN] == HIGH);

  feedAndRead("cb");
  CHECK(Serial.takeOutput() == "PUMP STOPPED COMMAND\nPUMP RUNNING b 0\n");
  CHECK(state == 'b');
  feedAndRead("c");
  Serial.takeOutput();

  feedAndRead("RATE 20\nG 500\nb");
  Serial.takeOutput();
  feedAndRead("RATE 999999999999999999999999999999999999999cbb\n");
  CHECK(Serial.takeOutput() == "PUMP STOPPED COMMAND\n");
  CHECK(state == 'c');

  feedAndRead("RATE 1\nG 2000\nb");
  CHECK(activeStepRate == 1UL);
  const unsigned long minimumRateEdgeStart = lastStepEdgeMicros;
  delayCallCount = 0;
  fakeMicros = minimumRateEdgeStart + 499999UL;
  loop();
  CHECK(delayCallCount == 0UL);
  CHECK(pinValues[STEP_PIN] == LOW);
  fakeMicros = minimumRateEdgeStart + 500000UL;
  loop();
  CHECK(pinValues[STEP_PIN] == HIGH);
  feedAndRead("c");
  Serial.takeOutput();

  fakeMillis = 100UL;
  feedAndRead("b");
  const unsigned long manualStart = runStartedMs;
  CHECK(activeRunLimitMs == 0UL);
  Serial.takeOutput();

  fakeMillis = 200UL;
  feedAndRead("b");
  CHECK(runStartedMs == manualStart);
  CHECK(activeRunLimitMs == 0UL);
  Serial.takeOutput();

  delayCallCount = 0;
  fakeMicros += 1000UL;
  loop();
  CHECK(delayCallCount == 2UL);
  feedAndRead("c");
  CHECK(state == 'c');
  CHECK(pendingStepRate == DEFAULT_STEP_RATE);
  Serial.takeOutput();

  feedAndRead("RATE 1\nG 50\nb");
  CHECK(activeStepRate == 1UL);
  CHECK(activeRunLimitMs == 50UL);
  pinValues[STEP_PIN] = HIGH;
  stepSignalHigh = true;
  fakeMillis = runStartedMs + 50UL;
  loop();
  CHECK(state == 'c');
  CHECK(pinValues[ENABLE_PIN] == HIGH);
  CHECK(pinValues[STEP_PIN] == LOW);
  CHECK(pendingStepRate == DEFAULT_STEP_RATE);
  CHECK(activeStepRate == DEFAULT_STEP_RATE);
  CHECK(activeRunLimitMs == 0UL);
  CHECK(armedRunLimitMs == 0UL);
  CHECK(pulseStepsRemaining == 0UL);
  Serial.takeOutput();

  feedAndRead("RATE 1\nSTOP\n");
  CHECK(pendingStepRate == DEFAULT_STEP_RATE);
  CHECK(activeStepRate == DEFAULT_STEP_RATE);
  CHECK(pinValues[ENABLE_PIN] == HIGH);
  CHECK(pinValues[STEP_PIN] == LOW);
  CHECK(activeRunLimitMs == 0UL);
  CHECK(armedRunLimitMs == 0UL);
  CHECK(pulseStepsRemaining == 0UL);
  Serial.takeOutput();

  feedAndRead("RATE 25\n");
  CHECK(pendingStepRate == 25UL);
  Serial.takeOutput();
  feedAndRead("RATE 0\nRATE 101\nRATE -1\nRATE 9999999999999999999999999\nRATE\n");
  CHECK(Serial.takeOutput() ==
        "RATE REJECTED\nRATE REJECTED\nRATE REJECTED\nRATE REJECTED\nRATE REJECTED\n");
  CHECK(state == 'c');
  CHECK(pendingStepRate == 25UL);

  feedAndRead("b");
  CHECK(activeRunLimitMs == 0UL);
  CHECK(activeStepRate == DEFAULT_STEP_RATE);
  CHECK(pendingStepRate == DEFAULT_STEP_RATE);
  Serial.takeOutput();
  feedAndRead("cRATE 25\nSTEP 2\n");
  CHECK(state == 'p');
  CHECK(activeStepRate == DEFAULT_STEP_RATE);
  CHECK(pulseStepsRemaining == 2UL);
  Serial.takeOutput();

  loop();
  CHECK(pulseStepsRemaining == 1UL);
  loop();
  CHECK(state == 'c');
  CHECK(pendingStepRate == DEFAULT_STEP_RATE);
  CHECK(pinValues[ENABLE_PIN] == HIGH);

  unsigned long parsed = 0;
  CHECK(parseBoundedUnsignedLong("100", 100UL, &parsed) && parsed == 100UL);
  CHECK(!parseBoundedUnsignedLong("101", 100UL, &parsed));
  CHECK(!parseBoundedUnsignedLong("9999999999999999999999999", 100UL, &parsed));
  CHECK(!parseBoundedUnsignedLong("-1", 100UL, &parsed));
  CHECK(parseBoundedUnsignedLong("4294967295", 4294967295UL, &parsed));
  CHECK(parsed == 4294967295UL);
  CHECK(!parseBoundedUnsignedLong("4294967296", 4294967295UL, &parsed));

  return 0;
}
