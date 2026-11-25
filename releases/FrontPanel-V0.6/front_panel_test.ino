// TROLLfx Front Panel Test V0.6 Reliability Repair; static DC calibration retained
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
static constexpr uint32_t kScanPeriodUs = 5000;      // 200 Hz control scan
static constexpr uint32_t kReportPeriodUs = 100000;  // 10 Hz USB state report
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
enum ControlType : uint8_t { CONTROL_POT, CONTROL_CV, CONTROL_SWITCH };
struct ControlState {
  const char *id;
  char side;
  ControlType type;
  uint16_t raw = 0;
  uint16_t filteredRaw = 0;
  uint16_t normalized = 0;
  bool seeded = false;
};
struct InputStats { uint16_t low = kAdcMax, high = 0; };
enum LedMode : uint8_t { LED_LIVE, LED_STARTUP, LED_ONE, LED_RGB, LED_RING };
static ControlState controls[kInputCount] = {
  {"A_TIME",'A',CONTROL_POT}, {"A_RATIO",'A',CONTROL_POT}, {"A_SLOPE",'A',CONTROL_POT},
  {"B_TIME",'B',CONTROL_POT}, {"B_RATIO",'B',CONTROL_POT}, {"B_SLOPE",'B',CONTROL_POT},
  {"A_RATIO_CV",'A',CONTROL_CV}, {"A_SLOPE_CV",'A',CONTROL_CV}, {"A_MOD_CV",'A',CONTROL_CV}, {"A_EXP_CV",'A',CONTROL_CV},
  {"B_RATIO_CV",'B',CONTROL_CV}, {"B_SLOPE_CV",'B',CONTROL_CV}, {"B_MOD_CV",'B',CONTROL_CV}, {"B_EXP_CV",'B',CONTROL_CV},
  {"A_SW1",'A',CONTROL_SWITCH}, {"A_SW2",'A',CONTROL_SWITCH}, {"B_SW1",'B',CONTROL_SWITCH}, {"B_SW2",'B',CONTROL_SWITCH}
};

static int8_t ledPins[8] = LED_DATA;
static Adafruit_NeoPXL8 leds(NUM_LEDS, ledPins, NEO_GRB);
static admux::Mux muxA(admux::Pin(MUX_A, INPUT, admux::PinType::Analog), admux::Pinset(MUX_S0, MUX_S1, MUX_S2));
static admux::Mux muxB(admux::Pin(MUX_B, INPUT, admux::PinType::Analog), admux::Pinset(MUX_S0, MUX_S1, MUX_S2));
static Encoder encoder(ALGO_ENC_1, ALGO_ENC_2);
static uint16_t outputCode[kChannelCount] = {0, 0, 0, 0};
static uint8_t outputPercent[kChannelCount] = {0, 0, 0, 0};
static InputStats inputStats[kInputCount];
static bool syncEnabled = false;
static volatile uint32_t syncCounts[2] = {0, 0};
static volatile bool syncLedPending[2] = {false, false};
static uint32_t syncLedDeadline[2] = {0, 0};
static uint32_t nextScanUs = 0;
static uint32_t nextReportUs = 0;
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
static uint32_t activeHoldUntilMs = 0;
static uint32_t lastMoveAtMs[kInputCount] = {0};
static bool previousEncoderButton = false, previousFollowButton = false;
static bool encoderButtonState = false, followButtonState = false;
static uint32_t feedbackUntilMs = 0;
static uint8_t feedbackPixel = FLW_LED;
static bool changeOnly = false;
static bool serialConnected = false;
static String previousTelemetry[20];
static LedMode ledMode = LED_LIVE;
static String commandLine;

static void printHelp() {
  Serial.println("PROTO=FP06");
  Serial.println("FrontPanel-Test-V0.6; outputs hold static DC codes; calibration storage untouched");
  Serial.println("PROTO? | HELLO GUI=0.6 | SNAPSHOT | DC ch percent | DC? | TIME DIAG | DIAG | STATS");
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

static uint16_t movementBaseline[kInputCount] = {0};
static bool movementBaselineReady = false;
static bool switchHigh[4] = {false, false, false, false};
static const uint16_t kPotMoveThreshold = 24;
static const uint16_t kCvMoveThreshold = 64;
static constexpr uint32_t kActiveHoldMs = 750;
static constexpr uint32_t kMoveDebounceMs = 70;

static void updateInput(uint8_t index, uint16_t raw) {
  if (index >= kInputCount) return;
  if (raw > kAdcMax) raw = kAdcMax;
  ControlState &c = controls[index];
  c.raw = raw;  // Preserve unfiltered ADC data as the canonical raw reading.
  if (!c.seeded) { c.filteredRaw = raw; c.seeded = true; }
  else c.filteredRaw = (uint16_t)(((uint32_t)c.filteredRaw * 3u + raw + 2u) / 4u);
  c.normalized = c.type == CONTROL_POT ? (uint16_t)(kAdcMax - c.filteredRaw) : c.filteredRaw;
  if (raw < inputStats[index].low) inputStats[index].low = raw;
  if (raw > inputStats[index].high) inputStats[index].high = raw;
}

static uint8_t normalizedRingPosition(uint16_t value) { return (uint8_t)(((uint32_t)value * NUM_RING_LEDS) / 4096u); }
static void activateControl(uint8_t index, uint32_t nowMs) {
  if (index >= kInputCount) return;
  lastMovedInput = index;
  lastMovedRing = normalizedRingPosition(controls[index].normalized);
  movementBaseline[index] = controls[index].normalized;
  lastMoveAtMs[index] = nowMs;
  activeHoldUntilMs = nowMs + kActiveHoldMs;
}
static void activateSpecial(uint8_t index, uint32_t nowMs) {
  lastMovedInput = index;
  activeHoldUntilMs = nowMs + kActiveHoldMs;
}

static void detectLastMoved() {
  uint32_t now = millis();
  if (!movementBaselineReady) {
    for (uint8_t i=0;i<kInputCount;++i) movementBaseline[i]=controls[i].normalized;
    for (uint8_t i=0;i<4;++i) switchHigh[i]=controls[14+i].raw > kAdcMax/2;
    movementBaselineReady=true; return;
  }
  int8_t bestPot = -1; uint16_t bestPotDelta = 0;
  for (uint8_t i=0;i<6;++i) {
    uint16_t value=controls[i].normalized;
    uint16_t delta=value>movementBaseline[i]?value-movementBaseline[i]:movementBaseline[i]-value;
    if(delta>=kPotMoveThreshold && now-lastMoveAtMs[i]>=kMoveDebounceMs && delta>bestPotDelta) { bestPot=i; bestPotDelta=delta; }
  }
  int8_t candidate = bestPot; uint16_t bestDelta=bestPotDelta;
  if(candidate<0) {
    for(uint8_t i=6;i<14;++i) {
      uint16_t value=controls[i].normalized;
      uint16_t delta=value>movementBaseline[i]?value-movementBaseline[i]:movementBaseline[i]-value;
      if(delta>=kCvMoveThreshold && now-lastMoveAtMs[i]>=kMoveDebounceMs && delta>bestDelta) { candidate=i; bestDelta=delta; }
    }
  }
  if(candidate>=0 && (lastMovedInput==(uint8_t)candidate || (int32_t)(now-activeHoldUntilMs)>=0)) activateControl((uint8_t)candidate,now);

  // Hysteresis on muxed switch ADC readings avoids chatter around half scale.
  for(uint8_t i=0;i<4;++i) {
    uint16_t raw=controls[14+i].raw;
    bool next=switchHigh[i];
    if(raw>=2800) next=true; else if(raw<=1300) next=false;
    if(next!=switchHigh[i]) {
      switchHigh[i]=next;
      activateControl((uint8_t)(14+i),now);
      feedbackPixel=(i<2)?(i==0?PRI_A_LED:SEC_A_LED):(i==2?PRI_B_LED:SEC_B_LED);
      feedbackUntilMs=now+180;
    }
  }
}

static void scanSideA() {
  // Match upstream read_all() order and retain every reading in the canonical control table.
  updateInput(9,muxA.read(EXP_CV_A));
  updateInput(0,analogRead(LIN_TIME_A));
  updateInput(2,muxA.read(S_POT_A)); updateInput(7,muxA.read(S_CV_A));
  updateInput(1,muxA.read(R_POT_A)); updateInput(6,muxA.read(R_CV_A));
  updateInput(8,muxA.read(M_CV_A));
  updateInput(14,muxA.read(SW_1_A)); updateInput(15,muxA.read(SW_2_A));
}
static void scanSideB() {
  updateInput(13,muxB.read(EXP_CV_B));
  updateInput(3,analogRead(LIN_TIME_B));
  updateInput(5,muxB.read(S_POT_B)); updateInput(11,muxB.read(S_CV_B));
  updateInput(4,muxB.read(R_POT_B)); updateInput(10,muxB.read(R_CV_B));
  updateInput(12,muxB.read(M_CV_B));
  updateInput(16,muxB.read(SW_1_B)); updateInput(17,muxB.read(SW_2_B));
}
static void sampleInputs() { scanSideA(); scanSideB(); detectLastMoved(); }

static const char *modeA() {
  bool s1=controls[14].raw>kAdcMax/2, s2=controls[15].raw>kAdcMax/2;
  if(s1&&s2) return "INVALID";
  if(s1) return "ENV";
  if(s2) return "VCO";
  return "LFO";
}
static const char *modeB() {
  bool s1=controls[16].raw>kAdcMax/2, s2=controls[17].raw>kAdcMax/2;
  if(s1&&s2) return "INVALID";
  if(s1) return "VCO";
  if(s2) return "ENV";
  return "LFO";
}
static const char *movedName(uint8_t index) {
  if(index<kInputCount) return controls[index].id;
  if(index==18) return "ENCODER";
  if(index==19) return "ENCODER_BUTTON";
  if(index==20) return "FOLLOW_BUTTON";
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
  char line[160];
  for(uint8_t i=0;i<6;++i) {
    snprintf(line,sizeof(line),"CTRL ID=%s RAW=%u VALUE=%u",controls[i].id,controls[i].raw,controls[i].normalized);
    sendTelemetry(i,String(line),force);
  }
  snprintf(line,sizeof(line),"SWITCH A MODE=%s SW1_RAW=%u SW2_RAW=%u",modeA(),controls[14].raw,controls[15].raw);
  sendTelemetry(6,String(line),force);
  snprintf(line,sizeof(line),"SWITCH B MODE=%s SW1_RAW=%u SW2_RAW=%u",modeB(),controls[16].raw,controls[17].raw);
  sendTelemetry(7,String(line),force);
  snprintf(line,sizeof(line),"ENCODER %ld",(long)encoderPosition); sendTelemetry(8,String(line),force);
  sendTelemetry(9,String("ENCODER_BUTTON ")+(encoderButtonState?"ON":"OFF"),force);
  sendTelemetry(10,String("FOLLOW_BUTTON ")+(followButtonState?"ON":"OFF"),force);
  snprintf(line,sizeof(line),"CV=%u,%u,%u,%u,%u,%u,%u,%u",
      controls[6].raw,controls[7].raw,controls[8].raw,controls[9].raw,
      controls[10].raw,controls[11].raw,controls[12].raw,controls[13].raw);
  sendTelemetry(11,String(line),force);
  snprintf(line,sizeof(line),"OUT PCT=%u,%u,%u,%u CODE=%u,%u,%u,%u DUTY=%u,%u,%u,%u",
      outputPercent[0],outputPercent[1],outputPercent[2],outputPercent[3],
      outputCode[0],outputCode[1],outputCode[2],outputCode[3],
      kPwmTop-outputCode[0],kPwmTop-outputCode[1],kPwmTop-outputCode[2],kPwmTop-outputCode[3]);
  sendTelemetry(12,String(line),force);
  snprintf(line,sizeof(line),"TIMERAW=%u,%u",controls[0].raw,controls[3].raw);
  sendTelemetry(13,String(line),force);
  snprintf(line,sizeof(line),"MOVED=%s",movedName(lastMovedInput)); sendTelemetry(14,String(line),force);
  snprintf(line,sizeof(line),"SYNC=%lu,%lu",(unsigned long)syncCounts[0],(unsigned long)syncCounts[1]);
  sendTelemetry(15,String(line),force);
}

static void printSnapshot() {
  Serial.println("PROTO=FP06");
  reportTelemetry(true);
}

static void pollPanelControls() {
  encoderPosition = -encoder.read();  // Front-panel test: clockwise is increasing.
  if (encoderPosition != previousEncoderPosition) {
    activateSpecial(18,millis());
    lastMovedRing = (uint8_t)(((encoderPosition / 4) % NUM_RING_LEDS + NUM_RING_LEDS) % NUM_RING_LEDS);
    previousEncoderPosition = encoderPosition;
  }
  bool encPressed = digitalRead(ALGO_BTN) == LOW;
  bool followPressed = digitalRead(FLW_BTN) == HIGH;
  if (encPressed && !previousEncoderButton) {
    activateSpecial(19,millis()); lastMovedRing = (uint8_t)(((encoderPosition/4)%NUM_RING_LEDS+NUM_RING_LEDS)%NUM_RING_LEDS);
    feedbackPixel=FLW_LED; feedbackUntilMs=millis()+180;
  }
  if (followPressed && !previousFollowButton) {
    activateSpecial(20,millis()); feedbackPixel=FLW_LED; feedbackUntilMs=millis()+180;
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
    Serial.print("RANGE "); Serial.print(controls[i].id); Serial.print(" raw="); Serial.print(controls[i].raw);
    Serial.print(" min="); Serial.print(inputStats[i].low); Serial.print(" max="); Serial.print(inputStats[i].high);
    Serial.print(" noise="); Serial.println(inputStats[i].high-inputStats[i].low);
  }
}

static void handleCommand(String line) {
  line.trim(); if (!line.length()) return;
  char op[20] = {0}, arg1[24] = {0};
  int a = 0, b = 0;
  if (sscanf(line.c_str(), "%19s", op) != 1) return;
  if (!strcmp(op, "HELP")) { printHelp(); return; }
  if (!strcmp(op, "INFO")) {
    Serial.print("INFO protocol=FP06 mode=DC outputs=static sync_enabled="); Serial.print(syncEnabled);
    Serial.print(" brightness="); Serial.print(brightness); Serial.print(" mux_a="); Serial.print(MUX_A);
    Serial.print(" mux_b="); Serial.println(MUX_B); return;
  }
  if (line == "PROTO?") { Serial.println("PROTO=FP06"); return; }
  if (!strncmp(line.c_str(), "HELLO GUI=", 10)) {
    char guiVersion[16]={0};
    if(sscanf(line.c_str(),"HELLO GUI=%15s",guiVersion)==1) { Serial.print("HELLO FW=FP06 GUI=");Serial.println(guiVersion); }
    else Serial.println("ERR HELLO GUI=version");
    return;
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
    Serial.print("TIME A_GPIO=27 A_SCAN="); Serial.print(controls[0].raw); Serial.print(" A_ARDUINO="); Serial.print(ar27); Serial.print(" A_SDK="); Serial.print(sdk27);
    Serial.print(" B_GPIO=28 B_SCAN="); Serial.print(controls[3].raw); Serial.print(" B_ARDUINO="); Serial.print(ar28); Serial.print(" B_SDK="); Serial.println(sdk28); return;
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
  if (line == "RESET STATS") { for(uint8_t i=0;i<kInputCount;++i){inputStats[i].low=controls[i].raw;inputStats[i].high=controls[i].raw;}Serial.println("OK stats reset");return; }
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
  nextScanUs=micros(); nextReportUs=nextScanUs+kReportPeriodUs;
  for(uint8_t i=0;i<kChannelCount;++i) setOutputPercent(i,0);
  ledMode=LED_STARTUP;ledFrame=0;ledFrameMs=millis();
  sampleInputs();
}

void loop() {
  bool connected = (bool)Serial;
  if (connected && !serialConnected) { serialConnected=true; sampleInputs(); pollPanelControls(); printSnapshot(); }
  else if (!connected) serialConnected=false;
  uint8_t commandBudget=64;
  while(Serial.available() && commandBudget--){
    char ch=(char)Serial.read();
    if(ch=='\n'||ch=='\r'){if(commandLine.length())handleCommand(commandLine);commandLine="";}
    else if(commandLine.length()<100)commandLine+=ch;
  }
  uint32_t nowMs=millis();
  pollPanelControls();
  uint32_t nowUs=micros();
  if((int32_t)(nowUs-nextScanUs)>=0){nextScanUs+=kScanPeriodUs;sampleInputs();}
  if((int32_t)(nowUs-nextReportUs)>=0){nextReportUs+=kReportPeriodUs;if((bool)Serial)reportTelemetry();}
  if(nowMs-lastLedRefreshMs>=33){lastLedRefreshMs=nowMs;renderLeds(nowMs);}
}
