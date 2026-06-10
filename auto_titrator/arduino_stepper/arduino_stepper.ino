const int STEP_PIN = 2;
const int DIR_PIN = 3;
const int ENABLE_PIN = 4;

char state = 'c'; // a=좌회전, b=우회전, c=정지

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENABLE_PIN, OUTPUT);

  digitalWrite(ENABLE_PIN, HIGH); // 처음엔 정지

  Serial.begin(9600);
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();

    if (cmd == 'a') {
      state = 'a';
      digitalWrite(DIR_PIN, LOW);   // 좌회전
      digitalWrite(ENABLE_PIN, LOW);
    }
    else if (cmd == 'b') {
      state = 'b';
      digitalWrite(DIR_PIN, HIGH);  // 우회전
      digitalWrite(ENABLE_PIN, LOW);
    }
    else if (cmd == 'c') {
      state = 'c';
      digitalWrite(ENABLE_PIN, HIGH); // 정지
    }
  }

  if (state == 'a' || state == 'b') {
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(5000);  // 속도 조절
    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(5000);
  }
}
