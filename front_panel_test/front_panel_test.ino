// TROLLfx Front Panel Test V0.5 DC Calibration
// Diagnostic firmware using the SpellTwister GPIO, LED and mux wiring.
// This sketch does not access calibration storage.
#include <Arduino.h>
#define ENCODER_DO_NOT_USE_INTERRUPTS
#include <Encoder.h>
#include <Adafruit_NeoPXL8.h>
#include <Mux.h>
#include <hardware/gpio.h>
#include <hardware/pwm.h>
#include <hardware/adc.h>
#include <math.h>
#include <string.h>

#include "pins.h"  // byte-for-byte upstream GPIO, LED and mux definitions

static constexpr uint8_t kChannelCount = 4;
static constexpr uint8_t kInputCount = 18;
static constexpr uint16_t kAdcMax = 4095;
static constexpr uint16_t kPwmTop = 2047;
static constexpr uint32_t kSamplePeriodUs = 100000;  // 10 Hz live meter report
static constexpr uint32_t black = 0x000000;
static constexpr uint32_t a_colour = 0xFFA500;
static constexpr uint32_t b_colour = 0x0000FF;
static constexpr uint32_t mix_colour = 0x7F3FFF;
static constexpr uint8_t kOutputPins[kChannelCount] = {PRI_OUT_A, SEC_OUT_A, PRI_OUT_B, SEC_OUT_B};
static constexpr uint8_t kTriggerPins[2] = {TRIG_OUT_A, TRIG_OUT_B};
static constexpr uint8_t kIndicatorLeds[kChannelCount] = {PRI_A_LED, SEC_A_LED, PRI_B_LED, SEC_B_LED};
static constexpr uint8_t kTriggerLeds[2] = {TRIG_A_LED, TRIG_B_LED};
static constexpr uint8_t kMuxSignals[2][8] = {
  {R_CV_A, R_POT_A, S_CV_A, S_POT_A, M_CV_A, SW_1_A, SW_2_A, EXP_CV_A},
  {R_CV_B, R_POT_B, S_CV_B, S_POT_B, M_CV_B, SW_1_B, SW_2_B, EXP_CV_B}
};
static const char *const kSwitchNames[4] = {"A_SW1", "A_SW2", "B_SW1", "B_SW2"};
static const char *const kInputNames[kInputCount] = {
  "A_TIME", "A_RATIO", "A_SHAPE", "B_TIME", "B_RATIO", "B_SHAPE",
  "A_RATIO_CV", "A_SHAPE_CV", "A_MOD_CV", "A_EXP_CV",
  "B_RATIO_CV", "B_SHAPE_CV", "B_MOD_CV", "B_EXP_CV",
  "A_SW1", "A_SW2", "B_SW1", "B_SW2"
};

struct InputStats { uint16_t low = kAdcMax, high = 0, latest = 0; };
enum LedMode : uint8_t { LED_LIVE, LED_STARTUP, LED_ONE, LED_RGB, LED_RING };

static int8_t ledPins[8] = LED_DATA;
static Adafruit_NeoPXL8 leds(NUM_LEDS, ledPins, NEO_GRB);
static admux::Mux muxA(admux::Pin(MUX_A, INPUT, admux::PinType::Analog), admux::Pinset(MUX_S0, MUX_S1, MUX_S2));
static admux::Mux muxB(admux::Pin(MUX_B, INPUT, admux::PinType::Analog), admux::Pinset(MUX_S0, MUX_S1, MUX_S2));
static Encoder encoder(ALGO_ENC_1, ALGO_ENC_2);
static uint16_t outputCode[kChannelCount] = {0, 0, 0, 0};
static uint8_t outputPercent[kChannelCount] = {0, 0, 0, 0};
static InputStats inputStats[kInputCount];
static uint16_t potReadings[6] = {0};
static uint16_t cvReadings[8] = {0};
static uint16_t switchReadings[4] = {0};
static bool syncEnabled = false;
static volatile uint32_t syncCounts[2] = {0, 0};
static volatile bool syncLedPending[2] = {false, false};
static uint32_t syncLedDeadline[2] = {0, 0};
static uint32_t nextSampleUs = 0;
static uint32_t lastLedRefreshMs = 0;
static uint32_t ledFrameMs = 0;
static uint8_t ledFrame = 0;
static uint8_t brightness = 255;
static uint8_t ledOneIndex = 0;
static uint8_t ledOneR = 255, ledOneG = 255, ledOneB = 255;
static uint8_t indicatorOverrideMask = 0;
static uint8_t indicatorOverride[kChannelCount] = {0};
static uint32_t indicatorOverrideUntil[kChannelCount] = {0};
static int64_t encoderPosition = 0;
static int64_t previousEncoderPosition = 0;
static uint8_t lastMovedInput = 0;
static uint8_t lastMovedRing = 0;
static bool previousEncoderButton = false, previousFollowButton = false;
static uint16_t previousSwitches[4] = {0, 0, 0, 0};
static bool switchBaselineReady = false;
static bool encoderButtonState = false, followButtonState = false;
static uint32_t feedbackUntilMs = 0;
static uint8_t feedbackPixel = FLW_LED;
static bool changeOnly = false;
static bool serialConnected = false;
static String previousTelemetry[8];
static LedMode ledMode = LED_LIVE;
static String commandLine;

static void printHelp() {
  Serial.println("PROTO=FP05");
  Serial.println("FrontPanel-Test-V0.5; outputs hold static DC codes; calibration storage untouched");
  Serial.println("SNAPSHOT | DC ch percent | DC? | TIME DIAG | DIAG | STATS | ADC DIRECT");
  Serial.println("LED STARTUP | LED ONE index r g b | LED RGB | LED RING | LED LIVE | BRIGHTNESS 0..255 | INDICATOR ch 0..255 | INDICATOR LIVE");
  Serial.println("SYNC ON | SYNC OFF | SYNC? | output channel 0 A_PRI, 1 A_SEC, 2 B_PRI, 3 B_SEC");
}

static void setOutputPercent(uint8_t channel, uint8_t percent) {
  if (channel >= kChannelCount || percent > 100) return;
  outputPercent[channel] = percent;
  outputCode[channel] = (uint16_t)(((uint32_t)percent * kPwmTop + 50u) / 100u);
  // The published analog stage inverts: slider/code up commands PWM duty down.
  pwm_set_gpio_level(kOutputPins[channel], (uint16_t)(kPwmTop - outputCode[channel]));
}

static void updateInput(uint8_t index, uint16_t raw) {
  if (index >= kInputCount) return;
  if (raw > kAdcMax) raw = kAdcMax;
  inputStats[index].latest = raw;
  if (raw < inputStats[index].low) inputStats[index].low = raw;
  if (raw > inputStats[index].high) inputStats[index].high = raw;
}

static uint16_t normalizedPot(uint8_t index) { return index < 6 ? (uint16_t)(kAdcMax - potReadings[index]) : 0; }
static uint8_t normalizedRingPosition(uint16_t raw) { return (uint8_t)(((uint32_t)(kAdcMax - raw) * NUM_RING_LEDS) / 4096u); }
static void detectLastMoved() {
  static uint16_t previous[kInputCount] = {0};
  static bool baselineReady = false;
  if (!baselineReady) { for (uint8_t i=0;i<kInputCount;++i) previous[i]=inputStats[i].latest; baselineReady=true; return; }
  for (uint8_t i = 0; i < kInputCount; ++i) {
    if (i >= 14) continue;
    uint16_t now = inputStats[i].latest;
    uint16_t delta = now > previous[i] ? now - previous[i] : previous[i] - now;
    if (delta >= 24) { lastMovedInput = i; lastMovedRing = normalizedRingPosition(now); previous[i] = now; }
  }
  if (!switchBaselineReady) { for(uint8_t i=0;i<4;++i)previousSwitches[i]=switchReadings[i];switchBaselineReady=true; }
  else for(uint8_t i=0;i<4;++i) if ((switchReadings[i]>kAdcMax/2)!=(previousSwitches[i]>kAdcMax/2)) {
    lastMovedInput=21+i; feedbackPixel=(i<2)?(i==0?PRI_A_LED:SEC_A_LED):(i==2?PRI_B_LED:SEC_B_LED);feedbackUntilMs=millis()+180;
    previousSwitches[i]=switchReadings[i];
  }
}

static void scanSideA() {
  // Match Waveformer::read_all(): EXP/pitch, direct time, shape pot/CV, ratio pot/CV, mod CV.
  cvReadings[3] = muxA.read(EXP_CV_A);
  potReadings[0] = analogRead(LIN_TIME_A);
  potReadings[2] = muxA.read(S_POT_A); cvReadings[1] = muxA.read(S_CV_A);
  potReadings[1] = muxA.read(R_POT_A); cvReadings[0] = muxA.read(R_CV_A);
  cvReadings[2] = muxA.read(M_CV_A);
  switchReadings[0] = muxA.read(SW_1_A); switchReadings[1] = muxA.read(SW_2_A);
}
static void scanSideB() {
  cvReadings[7] = muxB.read(EXP_CV_B);
  potReadings[3] = analogRead(LIN_TIME_B);
  potReadings[5] = muxB.read(S_POT_B); cvReadings[5] = muxB.read(S_CV_B);
  potReadings[4] = muxB.read(R_POT_B); cvReadings[4] = muxB.read(R_CV_B);
  cvReadings[6] = muxB.read(M_CV_B);
  switchReadings[2] = muxB.read(SW_1_B); switchReadings[3] = muxB.read(SW_2_B);
}
static void sampleInputs() {
  scanSideA(); scanSideB();
  for(uint8_t i=0;i<6;++i) updateInput(i,potReadings[i]);
  for (uint8_t i = 0; i < 8; ++i) updateInput(6 + i, cvReadings[i]);
  for (uint8_t i = 0; i < 4; ++i) updateInput(14 + i, switchReadings[i]);
  detectLastMoved();
}

static const char *modeA() {
  bool s1 = switchReadings[0] > kAdcMax / 2, s2 = switchReadings[1] > kAdcMax / 2;
  if (s1 && !s2) return "ENV";
  if (!s1 && s2) return "VCO";
  return "LFO";
}
static const char *modeB() {
  bool s1 = switchReadings[2] > kAdcMax / 2, s2 = switchReadings[3] > kAdcMax / 2;
  if (s1 && !s2) return "VCO";
  if (!s1 && s2) return "ENV";
  return "LFO";
}

static const char *movedName(uint8_t index) {
  if (index < kInputCount) return kInputNames[index];
  if (index == 18) return "ENCODER";
  if (index == 19) return "ENCODER_BUTTON";
  if (index == 20) return "FOLLOW_BUTTON";
  if (index >= 21 && index < 25) return kSwitchNames[index - 21];
  return "NONE";
}

static float outputSignalLevel(uint8_t channel) {
  return channel < kChannelCount ? (float)outputCode[channel] / (float)kPwmTop : 0.0f;
}

static void sendTelemetry(uint8_t slot, const String &line, bool force) {
  if (!(bool)Serial) { previousTelemetry[slot] = line; return; }
  if (force || !changeOnly || line != previousTelemetry[slot]) Serial.println(line);
  previousTelemetry[slot] = line;
}

static void reportTelemetry(bool force = false) {
  char line[192];
  snprintf(line, sizeof(line), "A TIME=%u SHAPE=%u RATIO=%u MODE=%s SW1=%u SW2=%u",
      normalizedPot(0), normalizedPot(2), normalizedPot(1), modeA(),
      switchReadings[0] > kAdcMax/2, switchReadings[1] > kAdcMax/2);
  sendTelemetry(0, String(line), force);
  snprintf(line, sizeof(line), "B TIME=%u SHAPE=%u RATIO=%u MODE=%s SW1=%u SW2=%u",
      normalizedPot(3), normalizedPot(5), normalizedPot(4), modeB(),
      switchReadings[2] > kAdcMax/2, switchReadings[3] > kAdcMax/2);
  sendTelemetry(1, String(line), force);
  snprintf(line, sizeof(line), "ENC=%ld BTN=%u FOLLOW=%u",
      (long)encoderPosition, encoderButtonState, followButtonState);
  sendTelemetry(2, String(line), force);
  snprintf(line, sizeof(line), "CV=%u,%u,%u,%u,%u,%u,%u,%u",
      cvReadings[0],cvReadings[1],cvReadings[2],cvReadings[3],cvReadings[4],cvReadings[5],cvReadings[6],cvReadings[7]);
  sendTelemetry(3, String(line), force);
  snprintf(line, sizeof(line), "OUT PCT=%u,%u,%u,%u CODE=%u,%u,%u,%u DUTY=%u,%u,%u,%u",
      outputPercent[0],outputPercent[1],outputPercent[2],outputPercent[3],
      outputCode[0],outputCode[1],outputCode[2],outputCode[3],
      kPwmTop-outputCode[0],kPwmTop-outputCode[1],kPwmTop-outputCode[2],kPwmTop-outputCode[3]);
  sendTelemetry(4, String(line), force);
  snprintf(line, sizeof(line), "TIMERAW=%u,%u", potReadings[0], potReadings[3]);
  sendTelemetry(5, String(line), force);
  snprintf(line, sizeof(line), "MOVED=%s", movedName(lastMovedInput));
  sendTelemetry(6, String(line), force);
  snprintf(line, sizeof(line), "SYNC=%lu,%lu", (unsigned long)syncCounts[0], (unsigned long)syncCounts[1]);
  sendTelemetry(7, String(line), force);
}

static void printSnapshot() {
  Serial.println("PROTO=FP05");
  reportTelemetry(true);
}

static void pollPanelControls() {
  encoderPosition = -encoder.read();  // Front-panel test: clockwise is increasing.
  if (encoderPosition != previousEncoderPosition) {
    lastMovedInput = 18;
    lastMovedRing = (uint8_t)(((encoderPosition / 4) % NUM_RING_LEDS + NUM_RING_LEDS) % NUM_RING_LEDS);
    previousEncoderPosition = encoderPosition;
  }
  bool encPressed = digitalRead(ALGO_BTN) == LOW;
  bool followPressed = digitalRead(FLW_BTN) == HIGH;
  if (encPressed && !previousEncoderButton) {
    lastMovedInput = 19; lastMovedRing = (uint8_t)(((encoderPosition/4)%NUM_RING_LEDS+NUM_RING_LEDS)%NUM_RING_LEDS);
    feedbackPixel=FLW_LED; feedbackUntilMs=millis()+180;
  }
  if (followPressed && !previousFollowButton) {
    lastMovedInput = 20; feedbackPixel=FLW_LED; feedbackUntilMs=millis()+180;
  }
  previousEncoderButton=encPressed; previousFollowButton=followPressed;
  encoderButtonState=encPressed; followButtonState=followPressed;
}

static uint32_t sideColour(uint8_t channel, uint8_t level) {
  uint8_t r = 0, g = 0, b = 0;
  if (channel < 2) { r = level; g = (uint8_t)(level * 0.55f); }
  else b = level;
  return leds.Color(r, g, b);
}

static void renderLeds(uint32_t nowMs) {
  leds.fill(black);
  if (ledMode == LED_STARTUP) {
    for (uint8_t j = 0; j < NUM_RING_LEDS; ++j) {
      int8_t d = ((int8_t)ledFrame - (int8_t)j + NUM_RING_LEDS) % NUM_RING_LEDS;
      if (d == 0) leds.setPixelColor(j, mix_colour);
      else if (d == 1) leds.setPixelColor(j, a_colour);
      else if (d == NUM_RING_LEDS - 1) leds.setPixelColor(j, b_colour);
    }
    if (nowMs - ledFrameMs >= 65) { ledFrameMs = nowMs; ++ledFrame; if (ledFrame >= NUM_RING_LEDS) { ledMode = LED_LIVE; ledFrame = 0; } }
  } else if (ledMode == LED_ONE) {
    leds.setPixelColor(ledOneIndex, leds.Color(ledOneR, ledOneG, ledOneB));
  } else if (ledMode == LED_RGB) {
    uint32_t c = (ledFrame % 3 == 0) ? leds.Color(255,0,0) : (ledFrame % 3 == 1) ? leds.Color(0,255,0) : leds.Color(0,0,255);
    for(uint8_t i=0;i<NUM_RING_LEDS;++i) leds.setPixelColor(i,c);
    if (nowMs - ledFrameMs >= 500) { ledFrameMs = nowMs; ++ledFrame; }
  } else if (ledMode == LED_RING) {
    leds.setPixelColor(ledFrame % NUM_RING_LEDS, mix_colour);
    if (nowMs - ledFrameMs >= 120) { ledFrameMs = nowMs; ++ledFrame; }
  } else {
    static const uint32_t cvColours[8] = {0x36D66B,0x08C7BA,0xE4D339,0xFF55C8,0x7DE65C,0x32D4ED,0xBA77FF,0xF06C43};
    uint32_t liveColour = lastMovedInput < 6 ? (lastMovedInput < 3 ? a_colour : b_colour) :
      lastMovedInput < 14 ? cvColours[lastMovedInput-6] :
      lastMovedInput == 18 ? leds.Color(160, 0, 255) : mix_colour;
    leds.setPixelColor(lastMovedRing, liveColour);
  }
  // Independent channel meters remain live during ring animations and USB loss.
  for (uint8_t i = 0; i < kChannelCount; ++i) {
    uint8_t level = (uint8_t)lroundf(outputSignalLevel(i) * 255.0f);
    if ((indicatorOverrideMask & (1u << i)) && (int32_t)(indicatorOverrideUntil[i]-nowMs)>0) level = indicatorOverride[i];
    else indicatorOverrideMask &= (uint8_t)~(1u << i);
    leds.setPixelColor(kIndicatorLeds[i], sideColour(i, level));
  }
  uint32_t nowUs = micros();
  for (uint8_t i = 0; i < 2; ++i) {
    if (syncLedPending[i]) { noInterrupts(); syncLedPending[i] = false; interrupts(); syncLedDeadline[i] = nowUs + 80000; }
    bool lit = (int32_t)(syncLedDeadline[i] - nowUs) > 0;
    leds.setPixelColor(kTriggerLeds[i], lit ? (i == 0 ? a_colour : b_colour) : black);
  }
  // Button and switch activity has priority over output pixel rendering.
  if ((int32_t)(feedbackUntilMs-nowMs)>0) leds.setPixelColor(feedbackPixel, leds.Color(255,255,255));
  // A manual single-pixel test overrides one pixel for a short interval.
  if (ledMode == LED_ONE && nowMs - ledFrameMs >= 1800) ledMode = LED_LIVE;
  if (ledMode == LED_ONE && ledOneIndex < NUM_LEDS) leds.setPixelColor(ledOneIndex, leds.Color(ledOneR,ledOneG,ledOneB));
  leds.show();
}

static void syncA() { ++syncCounts[0]; syncLedPending[0] = true; }
static void syncB() { ++syncCounts[1]; syncLedPending[1] = true; }

static void printStats() {
  for (uint8_t i = 0; i < kInputCount; ++i) {
    Serial.print("RANGE "); Serial.print(kInputNames[i]); Serial.print(" min="); Serial.print(inputStats[i].low);
    Serial.print(" max="); Serial.print(inputStats[i].high); Serial.print(" noise="); Serial.println(inputStats[i].high - inputStats[i].low);
  }
}

static void handleCommand(String line) {
  line.trim(); if (!line.length()) return;
  char op[20] = {0}, arg1[24] = {0};
  int a = 0, b = 0;
  if (sscanf(line.c_str(), "%19s", op) != 1) return;
  if (!strcmp(op, "HELP")) { printHelp(); return; }
  if (!strcmp(op, "INFO")) {
    Serial.print("INFO protocol=FP05 mode=DC outputs=static sync_enabled="); Serial.print(syncEnabled);
    Serial.print(" brightness="); Serial.print(brightness); Serial.print(" mux_a="); Serial.print(MUX_A);
    Serial.print(" mux_b="); Serial.println(MUX_B); return;
  }
  if (line == "SNAPSHOT") { Serial.println("OK snapshot follows"); sampleInputs(); pollPanelControls(); printSnapshot(); return; }
  if (line == "DC?") { Serial.println("OK DC state follows"); reportTelemetry(true); return; }
  if (!strcmp(op, "DC")) {
    if (sscanf(line.c_str(), "%*s %d %d", &a, &b) != 2 || a < 0 || a >= kChannelCount || b < 0 || b > 100) {
      Serial.println("ERR use DC channel(0..3) percent(0..100)"); return;
    }
    setOutputPercent((uint8_t)a, (uint8_t)b);
    Serial.print("OK DC channel="); Serial.print(a); Serial.print(" percent="); Serial.print(b);
    Serial.print(" code="); Serial.print(outputCode[a]); Serial.print(" duty="); Serial.println(kPwmTop-outputCode[a]);
    reportTelemetry(true); return;
  }
  if (line == "REPORT LIVE") { changeOnly=false; Serial.println("OK REPORT LIVE"); printSnapshot(); return; }
  if (line == "REPORT CHANGE") { changeOnly=true; Serial.println("OK REPORT CHANGE"); printSnapshot(); return; }
  if (line == "DIAG") {
    Serial.println("OK diagnostics follow"); printStats();
    uint16_t ar27=analogRead(LIN_TIME_A); adc_select_input(1); uint16_t sdk27=adc_read();
    uint16_t ar28=analogRead(LIN_TIME_B); adc_select_input(2); uint16_t sdk28=adc_read();
    Serial.print("ADC GPIO27 Arduino="); Serial.print(ar27); Serial.print(" SDK="); Serial.println(sdk27);
    Serial.print("ADC GPIO28 Arduino="); Serial.print(ar28); Serial.print(" SDK="); Serial.println(sdk28); return;
  }
  if (line == "TIME DIAG" || line == "ADC DIRECT") {
    sampleInputs();
    uint16_t ar27=analogRead(LIN_TIME_A); adc_select_input(1); uint16_t sdk27=adc_read();
    uint16_t ar28=analogRead(LIN_TIME_B); adc_select_input(2); uint16_t sdk28=adc_read();
    Serial.println("OK TIME diagnostics follow");
    Serial.print("TIME A_GPIO=27 A_SCAN="); Serial.print(potReadings[0]); Serial.print(" A_ARDUINO="); Serial.print(ar27); Serial.print(" A_SDK="); Serial.print(sdk27);
    Serial.print(" B_GPIO=28 B_SCAN="); Serial.print(potReadings[3]); Serial.print(" B_ARDUINO="); Serial.print(ar28); Serial.print(" B_SDK="); Serial.println(sdk28); return;
  }
  if (!strcmp(op, "ARM") || !strcmp(op, "DISARM")) { Serial.println("ERR DC outputs apply immediately; there is no arming state"); return; }
  if (!strcmp(op, "LED")) {
    if (line == "LED STARTUP") { ledMode=LED_STARTUP;ledFrame=0;ledFrameMs=millis();Serial.println("OK LED startup");return; }
    if (line == "LED RGB") { ledMode=LED_RGB;ledFrame=0;ledFrameMs=millis();Serial.println("OK LED RGB");return; }
    if (line == "LED RING") { ledMode=LED_RING;ledFrame=0;ledFrameMs=millis();Serial.println("OK LED ring");return; }
    if (line == "LED LIVE") { ledMode=LED_LIVE;Serial.println("OK LED live");return; }
    int r=0,g=0,bl=0;
    if (sscanf(line.c_str(), "%*s %23s %d %d %d %d", arg1, &a, &r, &g, &bl) == 5 && !strcmp(arg1,"ONE") && a>=0 && a<NUM_LEDS && r>=0 && r<=255 && g>=0 && g<=255 && bl>=0 && bl<=255) {
      ledMode=LED_ONE;ledFrameMs=millis();ledOneIndex=(uint8_t)a;ledOneR=(uint8_t)r;ledOneG=(uint8_t)g;ledOneB=(uint8_t)bl;Serial.println("OK LED one");return;
    }
    Serial.println("ERR LED STARTUP|RGB|RING|LIVE|ONE index r g b");return;
  }
  if (!strcmp(op, "BRIGHTNESS")) {
    if (sscanf(line.c_str(), "%*s %d", &a)!=1 || a<0 || a>255) { Serial.println("ERR BRIGHTNESS 0..255");return; }
    brightness=(uint8_t)a;leds.setBrightness(brightness);Serial.println("OK brightness");return;
  }
  if (!strcmp(op, "INDICATOR")) {
    if (line == "INDICATOR LIVE") { indicatorOverrideMask=0;Serial.println("OK indicators live");return; }
    if (sscanf(line.c_str(), "%*s %d %d", &a, &b)!=2 || a<0 || a>=kChannelCount || b<0 || b>255) { Serial.println("ERR INDICATOR ch 0..255");return; }
    indicatorOverrideMask|=(1u<<a);indicatorOverride[a]=(uint8_t)b;indicatorOverrideUntil[a]=millis()+1800;ledMode=LED_LIVE;Serial.println("OK indicator (temporary)");return;
  }
  if (line == "SYNC?") { Serial.println("OK sync query");Serial.print("SYNC=");Serial.print(syncCounts[0]);Serial.print(',');Serial.println(syncCounts[1]);return; }
  if (!strcmp(op, "SYNC")) {
    if (line == "SYNC ON") {
      if (!syncEnabled) { pinMode(SIG_IN_A,INPUT);pinMode(SIG_IN_B,INPUT);attachInterrupt(digitalPinToInterrupt(SIG_IN_A),syncA,RISING);attachInterrupt(digitalPinToInterrupt(SIG_IN_B),syncB,RISING);syncEnabled=true; }
      Serial.println("OK sync; conditioned SIG inputs only");return;
    }
    if (line == "SYNC OFF") { if(syncEnabled){detachInterrupt(digitalPinToInterrupt(SIG_IN_A));detachInterrupt(digitalPinToInterrupt(SIG_IN_B));syncEnabled=false;}Serial.println("OK sync off");return; }
    Serial.println("ERR SYNC ON|OFF|?");return;
  }
  if (line == "STATS") { printStats();return; }
  if (line == "RESET STATS") { for(uint8_t i=0;i<kInputCount;++i){inputStats[i].low=inputStats[i].latest;inputStats[i].high=inputStats[i].latest;}Serial.println("OK stats reset");return; }
  Serial.println("ERR unknown command; HELP");
}

static void setupPwm() {
  bool configured[8] = {false};
  for (uint8_t i=0;i<kChannelCount;++i) {
    uint slice=pwm_gpio_to_slice_num(kOutputPins[i]);
    if (!configured[slice]) { pwm_config cfg=pwm_get_default_config();pwm_config_set_wrap(&cfg,kPwmTop);pwm_config_set_clkdiv(&cfg,1.0f);pwm_init(slice,&cfg,true);configured[slice]=true; }
    gpio_set_function(kOutputPins[i],GPIO_FUNC_PWM);pwm_set_gpio_level(kOutputPins[i],0);
  }
  for(uint8_t i=0;i<2;++i){pinMode(kTriggerPins[i],OUTPUT);digitalWrite(kTriggerPins[i],LOW);}
}

void setup() {
  analogReadResolution(12);
  // RP2040 GPIO27/28 are ADC1/ADC2; preserve upstream's direct-GPIO usage.
  adc_gpio_init(LIN_TIME_A); adc_gpio_init(LIN_TIME_B);
  pinMode(ALGO_BTN,INPUT_PULLUP);pinMode(FLW_BTN,INPUT);
  pinMode(ALGO_ENC_1,INPUT_PULLUP);pinMode(ALGO_ENC_2,INPUT_PULLUP);
  Serial.begin(115200);
  leds.begin();leds.setBrightness(brightness);leds.fill(black);leds.show();
  setupPwm();
  nextSampleUs=micros();
  for(uint8_t i=0;i<kChannelCount;++i) setOutputPercent(i,0);
  ledMode=LED_STARTUP;ledFrame=0;ledFrameMs=millis();
  sampleInputs();
}

void loop() {
  bool connected = (bool)Serial;
  if (connected && !serialConnected) { serialConnected=true; sampleInputs(); pollPanelControls(); printSnapshot(); }
  else if (!connected) serialConnected=false;
  while(Serial.available()){
    char ch=(char)Serial.read();
    if(ch=='\n'||ch=='\r'){if(commandLine.length())handleCommand(commandLine);commandLine="";}
    else if(commandLine.length()<100)commandLine+=ch;
  }
  uint32_t nowMs=millis();
  pollPanelControls();
  uint32_t nowUs=micros();
  if((int32_t)(nowUs-nextSampleUs)>=0){nextSampleUs+=kSamplePeriodUs;sampleInputs();if((bool)Serial)reportTelemetry();}
  if(nowMs-lastLedRefreshMs>=33){lastLedRefreshMs=nowMs;renderLeds(nowMs);}
}
