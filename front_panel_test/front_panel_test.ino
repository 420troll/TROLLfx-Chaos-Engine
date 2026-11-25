// TROLLfx Front Panel Test V0.1
// Diagnostic firmware using the SpellTwister GPIO, LED and mux wiring.
// This sketch intentionally has no EEPROM/NVM access.
#include <Arduino.h>
#define ENCODER_DO_NOT_USE_INTERRUPTS
#include <Encoder.h>
#include <Adafruit_NeoPXL8.h>
#include <Mux.h>
#include <hardware/gpio.h>
#include <hardware/pwm.h>
#include <math.h>
#include <string.h>

#include "pins.h"  // byte-for-byte upstream GPIO, LED and mux definitions

static constexpr uint8_t kChannelCount = 4;
static constexpr uint8_t kInputCount = 18;
static constexpr uint16_t kAdcMax = 4095;
static constexpr uint16_t kPwmTop = 2047;
static constexpr uint32_t kSamplePeriodUs = 100000;  // 10 Hz live meter report
static constexpr uint32_t kWaveUpdateUs = 1000;      // 1 kHz waveform update
static constexpr uint32_t kTriggerPulseUs = 10000;
static constexpr uint32_t black = 0x000000;
static constexpr uint32_t a_colour = 0xFFA500;
static constexpr uint32_t b_colour = 0x0000FF;
static constexpr uint32_t mix_colour = 0x7F3FFF;
static constexpr uint8_t kOutputPins[kChannelCount] = {PRI_OUT_A, SEC_OUT_A, PRI_OUT_B, SEC_OUT_B};
static constexpr uint8_t kTriggerPins[2] = {TRIG_OUT_A, TRIG_OUT_B};
static constexpr uint8_t kIndicatorLeds[kChannelCount] = {PRI_A_LED, SEC_A_LED, PRI_B_LED, SEC_B_LED};
static constexpr uint8_t kTriggerLeds[2] = {TRIG_A_LED, TRIG_B_LED};
static constexpr uint8_t kPotPins[2] = {LIN_TIME_A, LIN_TIME_B};
static constexpr uint8_t kMuxPins[2] = {MUX_A, MUX_B};
static constexpr uint8_t kMuxSignals[2][8] = {
  {R_CV_A, R_POT_A, S_CV_A, S_POT_A, M_CV_A, SW_1_A, SW_2_A, EXP_CV_A},
  {R_CV_B, R_POT_B, S_CV_B, S_POT_B, M_CV_B, SW_1_B, SW_2_B, EXP_CV_B}
};
static const char *const kPotNames[6] = {"A_TIME", "A_RATIO", "A_SHAPE", "B_TIME", "B_RATIO", "B_SHAPE"};
static const char *const kCvNames[8] = {"A_RATIO_CV", "A_SHAPE_CV", "A_MOD_CV", "A_EXP_CV", "B_RATIO_CV", "B_SHAPE_CV", "B_MOD_CV", "B_EXP_CV"};
static const char *const kSwitchNames[4] = {"A_SW1", "A_SW2", "B_SW1", "B_SW2"};
static const char *const kInputNames[kInputCount] = {
  "A_TIME", "A_RATIO", "A_SHAPE", "B_TIME", "B_RATIO", "B_SHAPE",
  "A_RATIO_CV", "A_SHAPE_CV", "A_MOD_CV", "A_EXP_CV",
  "B_RATIO_CV", "B_SHAPE_CV", "B_MOD_CV", "B_EXP_CV",
  "A_SW1", "A_SW2", "B_SW1", "B_SW2"
};

enum WaveShape : uint8_t { WAVE_STOP, WAVE_SINE, WAVE_TRIANGLE, WAVE_RAMP, WAVE_SQUARE };
struct WaveChannel {
  WaveShape shape = WAVE_STOP;
  float hz = 1.0f;
  float phase = 0.0f;
  uint16_t code = 0;
};
struct InputStats { uint16_t low = kAdcMax, high = 0, latest = 0; };
enum LedMode : uint8_t { LED_LIVE, LED_STARTUP, LED_ONE, LED_RGB, LED_RING };

static int8_t ledPins[8] = LED_DATA;
static Adafruit_NeoPXL8 leds(NUM_LEDS, ledPins, NEO_GRB);
static admux::Mux muxA(admux::Pin(MUX_A, INPUT, admux::PinType::Analog), admux::Pinset(MUX_S0, MUX_S1, MUX_S2));
static admux::Mux muxB(admux::Pin(MUX_B, INPUT, admux::PinType::Analog), admux::Pinset(MUX_S0, MUX_S1, MUX_S2));
static Encoder encoder(ALGO_ENC_1, ALGO_ENC_2);
static WaveChannel waveChannels[kChannelCount];
static InputStats inputStats[kInputCount];
static uint16_t potReadings[6] = {0};
static uint16_t cvReadings[8] = {0};
static uint16_t switchReadings[4] = {0};
static bool analogArmed = false;
static bool triggerArmed = false;
static bool syncEnabled = false;
static volatile uint32_t syncCounts[2] = {0, 0};
static volatile bool syncLedPending[2] = {false, false};
static uint32_t triggerDeadline[2] = {0, 0};
static uint32_t syncLedDeadline[2] = {0, 0};
static uint32_t nextSampleUs = 0;
static uint32_t nextWaveUs = 0;
static uint32_t lastLedRefreshMs = 0;
static uint32_t autoNextMs = 0;
static uint32_t autoStepMs = 3000;
static uint32_t ledFrameMs = 0;
static uint8_t ledFrame = 0;
static uint8_t brightness = 80;
static uint8_t ledOneIndex = 0;
static uint8_t ledOneR = 255, ledOneG = 255, ledOneB = 255;
static uint8_t indicatorOverrideMask = 0;
static uint8_t indicatorOverride[kChannelCount] = {0};
static int64_t encoderPosition = 0;
static uint8_t autoChannel = 0;
static WaveShape autoShape = WAVE_SINE;
static float autoHz = 1.0f;
static bool autoCycle = false;
static LedMode ledMode = LED_LIVE;
static String commandLine;

static void printHelp() {
  Serial.println("READY FrontPanel-Test-V0.1; analog=DISARMED trigger=DISARMED");
  Serial.println("ARM ANALOG | ARM TRIG | ARM ALL | DISARM | INFO | STATS | RESET STATS");
  Serial.println("WAVE ch sine|triangle|ramp|square 0.5|1|2|5 | STOP ch|ALL | AUTO ON [shape hz seconds] | AUTO OFF");
  Serial.println("LED STARTUP | LED ONE index r g b | LED RGB | LED RING | LED LIVE | BRIGHTNESS 0..255 | INDICATOR ch 0..255 | INDICATOR LIVE");
  Serial.println("SYNC ON | SYNC OFF | SYNC? | ch: 0 A_PRI, 1 A_SEC, 2 B_PRI, 3 B_SEC; no command writes calibration storage");
}

static WaveShape parseShape(const char *shape) {
  if (!strcmp(shape, "sine")) return WAVE_SINE;
  if (!strcmp(shape, "triangle")) return WAVE_TRIANGLE;
  if (!strcmp(shape, "ramp")) return WAVE_RAMP;
  if (!strcmp(shape, "square")) return WAVE_SQUARE;
  return WAVE_STOP;
}

static const char *shapeName(WaveShape shape) {
  switch (shape) {
    case WAVE_SINE: return "sine";
    case WAVE_TRIANGLE: return "triangle";
    case WAVE_RAMP: return "ramp";
    case WAVE_SQUARE: return "square";
    default: return "stop";
  }
}

static float waveUnit(WaveShape shape, float phase) {
  switch (shape) {
    case WAVE_SINE: return 0.5f + 0.5f * sinf(phase * 6.28318530718f);
    case WAVE_TRIANGLE: return phase < 0.5f ? phase * 2.0f : 2.0f - phase * 2.0f;
    case WAVE_RAMP: return phase;
    case WAVE_SQUARE: return phase < 0.5f ? 0.0f : 1.0f;
    default: return 0.0f;
  }
}

static void setPwmCode(uint8_t channel, uint16_t code) {
  if (channel >= kChannelCount) return;
  if (code > kPwmTop) code = kPwmTop;
  waveChannels[channel].code = code;
  pwm_set_gpio_level(kOutputPins[channel], analogArmed ? code : 0);
}

static void setWave(uint8_t channel, WaveShape shape, float hz) {
  if (channel >= kChannelCount) return;
  waveChannels[channel].shape = shape;
  waveChannels[channel].hz = hz;
  waveChannels[channel].phase = 0.0f;
  if (shape == WAVE_STOP) setPwmCode(channel, 0);
}

static void stopAuto() { autoCycle = false; }

static void setArming(bool analog, bool trigger) {
  analogArmed = analog;
  triggerArmed = trigger;
  for (uint8_t i = 0; i < kChannelCount; ++i) pwm_set_gpio_level(kOutputPins[i], analogArmed ? waveChannels[i].code : 0);
  if (!triggerArmed) {
    for (uint8_t i = 0; i < 2; ++i) { digitalWrite(kTriggerPins[i], LOW); triggerDeadline[i] = 0; }
  }
  Serial.print("OK analog="); Serial.print(analogArmed ? "ARMED" : "DISARMED");
  Serial.print(" trigger="); Serial.println(triggerArmed ? "ARMED" : "DISARMED");
}

static void updateInput(uint8_t index, uint16_t raw) {
  if (index >= kInputCount) return;
  if (raw > kAdcMax) raw = kAdcMax;
  inputStats[index].latest = raw;
  if (raw < inputStats[index].low) inputStats[index].low = raw;
  if (raw > inputStats[index].high) inputStats[index].high = raw;
}

static void sampleInputs() {
  uint8_t stat = 0;
  potReadings[0] = analogRead(LIN_TIME_A);
  potReadings[3] = analogRead(LIN_TIME_B);
  updateInput(stat++, potReadings[0]);

  potReadings[1] = muxA.read(R_POT_A);
  potReadings[2] = muxA.read(S_POT_A);
  potReadings[4] = muxB.read(R_POT_B);
  potReadings[5] = muxB.read(S_POT_B);
  updateInput(1, potReadings[1]); updateInput(2, potReadings[2]);
  updateInput(3, potReadings[3]); updateInput(4, potReadings[4]); updateInput(5, potReadings[5]);

  cvReadings[0] = muxA.read(R_CV_A); cvReadings[1] = muxA.read(S_CV_A);
  cvReadings[2] = muxA.read(M_CV_A); cvReadings[3] = muxA.read(EXP_CV_A);
  cvReadings[4] = muxB.read(R_CV_B); cvReadings[5] = muxB.read(S_CV_B);
  cvReadings[6] = muxB.read(M_CV_B); cvReadings[7] = muxB.read(EXP_CV_B);
  for (uint8_t i = 0; i < 8; ++i) updateInput(6 + i, cvReadings[i]);

  switchReadings[0] = muxA.read(SW_1_A); switchReadings[1] = muxA.read(SW_2_A);
  switchReadings[2] = muxB.read(SW_1_B); switchReadings[3] = muxB.read(SW_2_B);
  for (uint8_t i = 0; i < 4; ++i) updateInput(14 + i, switchReadings[i]);
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

static void printReading(uint16_t raw, const InputStats &stats) {
  Serial.print("{\"r\":"); Serial.print(raw);
  Serial.print(",\"p\":"); Serial.print((uint16_t)((uint32_t)raw * 100 / kAdcMax));
  Serial.print(",\"lo\":"); Serial.print(stats.low);
  Serial.print(",\"hi\":"); Serial.print(stats.high);
  Serial.print(",\"n\":"); Serial.print(stats.high - stats.low); Serial.print('}');
}

static void reportLive() {
  Serial.print("LIVE {\"ms\":"); Serial.print(millis()); Serial.print(",\"pots\":[");
  for (uint8_t i = 0; i < 6; ++i) { if (i) Serial.print(','); Serial.print("{\"name\":\""); Serial.print(kPotNames[i]); Serial.print("\","); printReading(potReadings[i], inputStats[i]); Serial.print('}'); }
  Serial.print("],\"cvs\":[");
  for (uint8_t i = 0; i < 8; ++i) { if (i) Serial.print(','); Serial.print("{\"name\":\""); Serial.print(kCvNames[i]); Serial.print("\","); printReading(cvReadings[i], inputStats[6 + i]); Serial.print('}'); }
  Serial.print("],\"switches\":[");
  for (uint8_t i = 0; i < 4; ++i) { if (i) Serial.print(','); Serial.print("{\"name\":\""); Serial.print(kSwitchNames[i]); Serial.print("\","); printReading(switchReadings[i], inputStats[14 + i]); Serial.print('}'); }
  encoderPosition = encoder.read();
  Serial.print("],\"encoder\":"); Serial.print((long)encoderPosition);
  Serial.print(",\"encoder_button\":"); Serial.print(digitalRead(ALGO_BTN) == LOW ? 1 : 0);
  Serial.print(",\"follow_button\":"); Serial.print(digitalRead(FLW_BTN) == HIGH ? 1 : 0);
  Serial.print(",\"mode_a\":\""); Serial.print(modeA()); Serial.print("\",\"mode_b\":\""); Serial.print(modeB());
  Serial.print("\",\"sync_a\":"); Serial.print(syncCounts[0]); Serial.print(",\"sync_b\":"); Serial.print(syncCounts[1]);
  Serial.print(",\"ring\":"); Serial.print(((encoderPosition / 4) % NUM_RING_LEDS + NUM_RING_LEDS) % NUM_RING_LEDS);
  Serial.print(",\"analog_armed\":"); Serial.print(analogArmed ? "true" : "false");
  Serial.print(",\"trigger_armed\":"); Serial.print(triggerArmed ? "true" : "false"); Serial.println("}");
}

static uint32_t sideColour(uint8_t channel, uint8_t level) {
  uint8_t r = 0, g = 0, b = 0;
  if (channel < 2) { r = level; g = (channel == 0) ? (uint8_t)(level * 0.55f) : 0; }
  else b = level;
  return leds.Color(r, g, b);
}

static void renderLeds(uint32_t nowMs) {
  if (ledMode == LED_STARTUP) {
    leds.fill(black);
    for (uint8_t j = 0; j < NUM_RING_LEDS; ++j) {
      int8_t d = ((int8_t)ledFrame - (int8_t)j + NUM_RING_LEDS) % NUM_RING_LEDS;
      if (d == 0) leds.setPixelColor(j, mix_colour);
      else if (d == 1) leds.setPixelColor(j, a_colour);
      else if (d == NUM_RING_LEDS - 1) leds.setPixelColor(j, b_colour);
    }
    if (nowMs - ledFrameMs >= 65) { ledFrameMs = nowMs; ++ledFrame; if (ledFrame >= NUM_RING_LEDS) { ledMode = LED_LIVE; ledFrame = 0; } }
  } else if (ledMode == LED_ONE) {
    leds.fill(black); leds.setPixelColor(ledOneIndex, leds.Color(ledOneR, ledOneG, ledOneB));
  } else if (ledMode == LED_RGB) {
    uint32_t c = (ledFrame % 3 == 0) ? leds.Color(255,0,0) : (ledFrame % 3 == 1) ? leds.Color(0,255,0) : leds.Color(0,0,255);
    leds.fill(c);
    if (nowMs - ledFrameMs >= 500) { ledFrameMs = nowMs; ++ledFrame; }
  } else if (ledMode == LED_RING) {
    leds.fill(black); leds.setPixelColor(ledFrame % NUM_RING_LEDS, mix_colour);
    if (nowMs - ledFrameMs >= 120) { ledFrameMs = nowMs; ++ledFrame; }
  } else {
    leds.fill(black);
    const uint8_t ringIndex = (uint8_t)(((encoderPosition / 4) % NUM_RING_LEDS + NUM_RING_LEDS) % NUM_RING_LEDS);
    leds.setPixelColor(ringIndex, mix_colour);
    for (uint8_t i = 0; i < kChannelCount; ++i) {
      uint8_t level = 0;
      if (waveChannels[i].shape != WAVE_STOP) level = (uint8_t)(50 + waveChannels[i].code * 205u / kPwmTop);
      if (indicatorOverrideMask & (1u << i)) level = indicatorOverride[i];
      leds.setPixelColor(kIndicatorLeds[i], sideColour(i, level));
    }
    uint32_t nowUs = micros();
    for (uint8_t i = 0; i < 2; ++i) {
      if (syncLedPending[i]) { noInterrupts(); syncLedPending[i] = false; interrupts(); syncLedDeadline[i] = nowUs + 80000; }
      bool lit = ((int32_t)(syncLedDeadline[i] - nowUs) > 0) || ((int32_t)(triggerDeadline[i] - nowUs) > 0);
      leds.setPixelColor(kTriggerLeds[i], lit ? (i == 0 ? a_colour : b_colour) : black);
    }
  }
  leds.show();
}

static void updateWaves(uint32_t nowUs) {
  static uint32_t lastUs = nowUs;
  uint32_t elapsedUs = nowUs - lastUs; lastUs = nowUs;
  if (elapsedUs > 10000) elapsedUs = 10000;
  for (uint8_t i = 0; i < kChannelCount; ++i) {
    WaveChannel &w = waveChannels[i];
    if (w.shape == WAVE_STOP) { if (analogArmed) pwm_set_gpio_level(kOutputPins[i], 0); continue; }
    w.phase += w.hz * (float)elapsedUs / 1000000.0f;
    bool wrapped = w.phase >= 1.0f;
    if (wrapped) w.phase -= floorf(w.phase);
    float unit = waveUnit(w.shape, w.phase);
    w.code = (uint16_t)lroundf(unit * kPwmTop);
    pwm_set_gpio_level(kOutputPins[i], analogArmed ? w.code : 0);
    if (wrapped && triggerArmed) {
      uint8_t side = (i < 2) ? 0 : 1;
      digitalWrite(kTriggerPins[side], HIGH);
      triggerDeadline[side] = nowUs + kTriggerPulseUs;
    }
  }
  for (uint8_t i = 0; i < 2; ++i) {
    if (triggerDeadline[i] && (int32_t)(nowUs - triggerDeadline[i]) >= 0) {
      digitalWrite(kTriggerPins[i], LOW); triggerDeadline[i] = 0;
    }
  }
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
  char op[20] = {0}, arg1[24] = {0}, arg2[24] = {0};
  int a = 0, b = 0, c = 0;
  if (sscanf(line.c_str(), "%19s", op) != 1) return;
  if (!strcmp(op, "HELP")) { printHelp(); return; }
  if (!strcmp(op, "INFO")) {
    Serial.print("INFO analog_armed="); Serial.print(analogArmed); Serial.print(" trigger_armed="); Serial.print(triggerArmed);
    Serial.print(" sync_enabled="); Serial.print(syncEnabled); Serial.print(" brightness="); Serial.print(brightness);
    Serial.print(" mux_a="); Serial.print(MUX_A); Serial.print(" mux_b="); Serial.println(MUX_B); return;
  }
  if (!strcmp(op, "ARM")) {
    if (line == "ARM ANALOG") { setArming(true, triggerArmed); return; }
    if (line == "ARM TRIG") { setArming(analogArmed, true); return; }
    if (line == "ARM ALL") { setArming(true, true); return; }
    Serial.println("ERR use ARM ANALOG|TRIG|ALL"); return;
  }
  if (!strcmp(op, "DISARM")) { stopAuto(); setArming(false, false); return; }
  if (!strcmp(op, "WAVE")) {
    float hz = 0.0f;
    int n = sscanf(line.c_str(), "%*s %d %23s %f", &a, arg1, &hz);
    WaveShape shape = parseShape(arg1);
    if (n != 3 || a < 0 || a >= kChannelCount || shape == WAVE_STOP || !isfinite(hz) || !(hz == 0.5f || hz == 1.0f || hz == 2.0f || hz == 5.0f)) { Serial.println("ERR WAVE ch shape 0.5|1|2|5"); return; }
    stopAuto(); setWave((uint8_t)a, shape, hz); Serial.println("OK wave selected; ARM ANALOG required for jack output"); return;
  }
  if (!strcmp(op, "STOP")) {
    if (line == "STOP ALL") { stopAuto(); for (uint8_t i=0;i<kChannelCount;++i) setWave(i,WAVE_STOP,0); Serial.println("OK stopped"); return; }
    if (sscanf(line.c_str(), "%*s %d", &a) != 1 || a < 0 || a >= kChannelCount) { Serial.println("ERR STOP ch|ALL"); return; }
    stopAuto(); setWave((uint8_t)a,WAVE_STOP,0); Serial.println("OK stopped"); return;
  }
  if (!strcmp(op, "AUTO")) {
    if (line == "AUTO OFF") { stopAuto(); for (uint8_t i=0;i<kChannelCount;++i) setWave(i,WAVE_STOP,0); Serial.println("OK auto off"); return; }
    float hz = 1.0f; int seconds = 3;
    int n = sscanf(line.c_str(), "%*s %23s %23s %f %d", arg1, arg2, &hz, &c);
    if (n < 1 || strcmp(arg1,"ON")) { Serial.println("ERR AUTO ON [shape hz seconds] | AUTO OFF"); return; }
    if (n >= 2 && parseShape(arg2) != WAVE_STOP) autoShape = parseShape(arg2);
    if (n >= 4) seconds = c;
    if ((n >= 2 && parseShape(arg2) == WAVE_STOP) || !(hz == 0.5f || hz == 1.0f || hz == 2.0f || hz == 5.0f) || seconds < 1 || seconds > 30) { Serial.println("ERR auto range"); return; }
    autoHz = hz; autoStepMs = (uint32_t)seconds * 1000u; autoCycle = true; autoChannel = 0; autoNextMs = millis();
    Serial.println("OK auto cycle; ARM ANALOG/TRIG separately if required"); return;
  }
  if (!strcmp(op, "LED")) {
    if (line == "LED STARTUP") { ledMode=LED_STARTUP;ledFrame=0;ledFrameMs=millis();Serial.println("OK LED startup");return; }
    if (line == "LED RGB") { ledMode=LED_RGB;ledFrame=0;ledFrameMs=millis();Serial.println("OK LED RGB");return; }
    if (line == "LED RING") { ledMode=LED_RING;ledFrame=0;ledFrameMs=millis();Serial.println("OK LED ring");return; }
    if (line == "LED LIVE") { ledMode=LED_LIVE;Serial.println("OK LED live");return; }
    int r=0,g=0,bl=0;
    if (sscanf(line.c_str(), "%*s %23s %d %d %d %d", arg1, &a, &r, &g, &bl) == 5 && !strcmp(arg1,"ONE") && a>=0 && a<NUM_LEDS && r>=0 && r<=255 && g>=0 && g<=255 && bl>=0 && bl<=255) {
      ledMode=LED_ONE;ledOneIndex=(uint8_t)a;ledOneR=(uint8_t)r;ledOneG=(uint8_t)g;ledOneB=(uint8_t)bl;Serial.println("OK LED one");return;
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
    indicatorOverrideMask|=(1u<<a);indicatorOverride[a]=(uint8_t)b;ledMode=LED_LIVE;Serial.println("OK indicator");return;
  }
  if (line == "SYNC?") { Serial.print("SYNC A=");Serial.print(syncCounts[0]);Serial.print(" B=");Serial.println(syncCounts[1]);return; }
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
  pinMode(ALGO_BTN,INPUT_PULLUP);pinMode(FLW_BTN,INPUT);
  pinMode(ALGO_ENC_1,INPUT_PULLUP);pinMode(ALGO_ENC_2,INPUT_PULLUP);
  Serial.begin(115200);
  const uint32_t waitStart=millis();while(!Serial && millis()-waitStart<1200)delay(5);
  leds.begin();leds.setBrightness(brightness);leds.fill(black);leds.show();
  setupPwm();
  nextSampleUs=micros();nextWaveUs=nextSampleUs;
  ledMode=LED_STARTUP;ledFrame=0;ledFrameMs=millis();
  sampleInputs();printHelp();
}

void loop() {
  while(Serial.available()){
    char ch=(char)Serial.read();
    if(ch=='\n'||ch=='\r'){if(commandLine.length())handleCommand(commandLine);commandLine="";}
    else if(commandLine.length()<100)commandLine+=ch;
  }
  uint32_t nowUs=micros();
  if((int32_t)(nowUs-nextWaveUs)>=0){nextWaveUs+=kWaveUpdateUs;updateWaves(nowUs);}
  uint32_t nowMs=millis();
  if(autoCycle && (int32_t)(nowMs-autoNextMs)>=0){for(uint8_t i=0;i<kChannelCount;++i)setWave(i,WAVE_STOP,0);setWave(autoChannel,autoShape,autoHz);autoChannel=(autoChannel+1)%kChannelCount;autoNextMs=nowMs+autoStepMs;}
  if((int32_t)(nowUs-nextSampleUs)>=0){nextSampleUs+=kSamplePeriodUs;sampleInputs();encoderPosition=encoder.read();reportLive();}
  if(nowMs-lastLedRefreshMs>=33){lastLedRefreshMs=nowMs;renderLeds(nowMs);}
}
