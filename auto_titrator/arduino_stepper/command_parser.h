#ifndef AUTO_TITRATOR_COMMAND_PARSER_H
#define AUTO_TITRATOR_COMMAND_PARSER_H

#include <limits.h>

// Accept only a non-empty sequence of ASCII decimal digits. Signs, leading or
// trailing whitespace, tabs, and mixed text are rejected before conversion.
inline bool isStrictUnsignedDecimalText(const char* text) {
  if (!text || *text == '\0') {
    return false;
  }
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    if (*cursor < '0' || *cursor > '9') {
      return false;
    }
  }
  return true;
}

// Parse decimal text without allowing the accumulator to wrap. The explicit
// bound also makes this behave identically on an AVR's 32-bit unsigned long
// and on a 64-bit host used by the firmware tests.
inline bool parseBoundedUnsignedLong(
    const char* text,
    unsigned long maximum,
    unsigned long* parsedValue) {
  if (!isStrictUnsignedDecimalText(text) || !parsedValue) {
    return false;
  }

  unsigned long value = 0;
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    const unsigned long digit = static_cast<unsigned long>(*cursor - '0');
    if (digit > maximum || value > (maximum - digit) / 10UL) {
      return false;
    }
    value = value * 10UL + digit;
  }
  *parsedValue = value;
  return true;
}

#endif
