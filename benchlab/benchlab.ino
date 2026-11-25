// Separate diagnostic target. Keeps the upstream SpellTwister sketch and its
// calibration/control architecture intact.
#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pwm.h>
#include <math.h>
#include <string.h>

static constexpr uint8_t kPins[4] = {13, 12, 1, 0};
static constexpr uint8_t kSyncPins[2] = {17, 18};
static constexpr uint32_t kDefaultCarrier = 44100;
static constexpr uint32_t kDefaultUpdateHz = 1000;
static constexpr uint8_t kChannels = 4;

enum Wave : uint8_t { W_STOP, W_SINE, W_TRIANGLE, W_SAW, W_SQUARE, W_STAIR, W_RAMP };
struct Channel {
  Wave wave = W_STOP;
  float frequency = 1.0f;
  uint16_t low = 0;
  uint16_t high = 0;
  uint16_t raw = 0;
  uint32_t sweepStartHz = 0, sweepEndHz = 0, sweepMs = 0, sweepT0 = 0;
  bool sweeping = false;
};

static Channel channels[kChannels];
static uint8_t pwmBits = 11;
static uint16_t pwmTop = 2047;
static uint32_t requestedCarrier = kDefaultCarrier;
static float actualCarrier = 0.0f;
static uint32_t updateHz = kDefaultUpdateHz;
static uint32_t updatePeriodUs = 1000;
static uint32_t nextUpdateUs = 0;
static uint32_t updates = 0, overruns = 0;
static uint32_t rateWindowStartUs = 0, rateWindowUpdates = 0;
static float measuredUpdateHz = 0.0f;
static volatile uint32_t syncCount[2] = {0, 0};
static volatile uint32_t syncLastUs[2] = {0, 0};
static bool syncEnabled = false;
static bool armed = false;

static uint16_t toCode(float unit) {
  if (unit < 0.0f) unit = 0.0f;
  if (unit > 1.0f) unit = 1.0f;
  return (uint16_t)lroundf(unit * pwmTop);
}

static bool configurePwm(uint8_t bits, uint32_t carrierHz) {
  if (bits < 6 || bits > 11 || carrierHz == 0) return false;
  pwmBits = bits;
  pwmTop = (uint16_t)((1u << bits) - 1u);
  requestedCarrier = carrierHz;
  const float dividerRaw = (float)clock_get_hz(clk_sys) / ((float)carrierHz * (pwmTop + 1u));
  float divider = roundf(dividerRaw * 16.0f) / 16.0f;
  if (divider < 1.0f) divider = 1.0f;
  if (divider > 255.9375f) divider = 255.9375f;
  actualCarrier = (float)clock_get_hz(clk_sys) / (divider * (pwmTop + 1u));
  for (uint8_t i = 0; i < kChannels; ++i) {
    const uint8_t pin = kPins[i];
    const uint slice = pwm_gpio_to_slice_num(pin);
    pwm_config cfg = pwm_get_default_config();
    pwm_config_set_wrap(&cfg, pwmTop);
    pwm_config_set_clkdiv(&cfg, divider);
    gpio_set_function(pin, GPIO_FUNC_PWM);
    pwm_init(slice, &cfg, true);
    if (channels[i].raw > pwmTop) channels[i].raw = pwmTop;
    pwm_set_gpio_level(pin, armed ? channels[i].raw : 0);
  }
  return true;
}

static void writeChannel(uint8_t channel, uint16_t code) {
  if (channel >= kChannels) return;
  if (code > pwmTop) code = pwmTop;
  channels[channel].raw = code;
  pwm_set_gpio_level(kPins[channel], armed ? code : 0);
}

static void syncA() { ++syncCount[0]; syncLastUs[0] = micros(); }
static void syncB() { ++syncCount[1]; syncLastUs[1] = micros(); }

static void reportInfo() {
  Serial.print("INFO armed="); Serial.print(armed ? 1 : 0);
  Serial.print(" resolution_bits="); Serial.print(pwmBits);
  Serial.print(" pwm_top="); Serial.print(pwmTop);
  Serial.print(" carrier_requested_hz="); Serial.print(requestedCarrier);
  Serial.print(" carrier_actual_hz="); Serial.print(actualCarrier, 2);
  Serial.print(" waveform_update_requested_hz="); Serial.print(updateHz);
  Serial.print(" waveform_update_target_hz="); Serial.print(updateHz);
  Serial.print(" waveform_update_measured_hz="); Serial.print(measuredUpdateHz, 2);
  Serial.print(" updates="); Serial.print(updates);
  Serial.print(" overruns="); Serial.println(overruns);
}

static Wave parseWave(const String &s) {
  if (s.equalsIgnoreCase("sine")) return W_SINE;
  if (s.equalsIgnoreCase("triangle")) return W_TRIANGLE;
  if (s.equalsIgnoreCase("saw")) return W_SAW;
  if (s.equalsIgnoreCase("square")) return W_SQUARE;
  if (s.equalsIgnoreCase("stair")) return W_STAIR;
  if (s.equalsIgnoreCase("ramp")) return W_RAMP;
  return W_STOP;
}

static void help() {
  Serial.println("Commands: HELP | INFO | ARM | DISARM | RAW ch code | DC ch percent");
  Serial.println("WAVE ch sine|triangle|saw|square|stair|ramp hz [lowCode highCode]");
  Serial.println("SWEEP ch startHz stopHz durationMs | RES 6..11 | CARRIER hz | UPDATE hz");
  Serial.println("RIPPLE ch | CROSSTALK ch | SYNC ON|OFF | SYNC? | STOP ch|ALL");
  Serial.println("ch is 0..3: A primary, A secondary, B primary, B secondary.");
}

static void handleLine(String line) {
  line.trim();
  if (!line.length()) return;
  char op[20] = {0}, arg[20] = {0};
  int ch = 0, a = 0, b = 0, c = 0;
  if (sscanf(line.c_str(), "%19s", op) != 1) return;
  if (!strcmp(op, "HELP")) { help(); return; }
  if (!strcmp(op, "INFO")) { reportInfo(); return; }
  if (!strcmp(op, "ARM")) {
    armed = true;
    for (uint8_t i = 0; i < kChannels; ++i) pwm_set_gpio_level(kPins[i], channels[i].raw);
    Serial.println("OK armed"); return;
  }
  if (!strcmp(op, "DISARM")) {
    armed = false;
    for (uint8_t i = 0; i < kChannels; ++i) pwm_set_gpio_level(kPins[i], 0);
    Serial.println("OK disarmed"); return;
  }
  if (!strcmp(op, "RES") && sscanf(line.c_str(), "%*s %d", &a) == 1) {
    if (armed) Serial.println("ERR disarm outputs before changing resolution");
    else if (!configurePwm((uint8_t)a, requestedCarrier)) Serial.println("ERR range 6..11 bits");
    else reportInfo(); return;
  }
  if (!strcmp(op, "CARRIER") && sscanf(line.c_str(), "%*s %d", &a) == 1) {
    if (armed) Serial.println("ERR disarm outputs before changing carrier");
    else if (a < 100 || !configurePwm(pwmBits, (uint32_t)a)) Serial.println("ERR invalid carrier");
    else reportInfo(); return;
  }
  if (!strcmp(op, "UPDATE") && sscanf(line.c_str(), "%*s %d", &a) == 1) {
    if (a < 1 || a > 50000) Serial.println("ERR update range 1..50000");
    else {
      bool incompatibleWave = false;
      for (uint8_t i = 0; i < kChannels; ++i) {
        if ((channels[i].wave != W_STOP && channels[i].frequency > a / 2.0f) ||
            (channels[i].sweeping && (channels[i].sweepStartHz > (uint32_t)a / 2u || channels[i].sweepEndHz > (uint32_t)a / 2u))) incompatibleWave = true;
      }
      if (incompatibleWave) Serial.println("ERR stop high-frequency waves before lowering UPDATE");
      else { updateHz = (uint32_t)a; updatePeriodUs = 1000000u / updateHz; Serial.println("OK"); }
    }
    return;
  }
  if (!strcmp(op, "RAW") && sscanf(line.c_str(), "%*s %d %d", &ch, &a) == 2) {
    if (ch < 0 || ch >= kChannels || a < 0 || a > pwmTop) Serial.println("ERR channel/code range");
    else { channels[ch].wave = W_STOP; channels[ch].sweeping = false; writeChannel(ch, a); Serial.println("OK"); }
    return;
  }
  if (!strcmp(op, "DC") && sscanf(line.c_str(), "%*s %d %d", &ch, &a) == 2) {
    if (ch < 0 || ch >= kChannels || a < 0 || a > 100) Serial.println("ERR channel/percent range");
    else { channels[ch].wave = W_STOP; channels[ch].sweeping = false; writeChannel(ch, toCode(a / 100.0f)); Serial.println("OK"); }
    return;
  }
  if (!strcmp(op, "WAVE")) {
    char shape[20] = {0}; float hz = 0.0f;
    const int n = sscanf(line.c_str(), "%*s %d %19s %f %d %d", &ch, shape, &hz, &a, &b);
    if (n < 3 || ch < 0 || ch >= kChannels || !isfinite(hz) || hz <= 0.0f || hz > updateHz / 2.0f) { Serial.println("ERR WAVE syntax/range (frequency must be <= UPDATE/2)"); return; }
    const Wave w = parseWave(String(shape));
    if (w == W_STOP) { Serial.println("ERR waveform"); return; }
    const int low = n >= 4 ? a : 0;
    const int high = n >= 5 ? b : pwmTop;
    if (low < 0 || high < 0 || low > pwmTop || high > pwmTop || low > high) { Serial.println("ERR waveform code range/order"); return; }
    channels[ch].wave = w; channels[ch].frequency = hz;
    channels[ch].low = (uint16_t)low;
    channels[ch].high = (uint16_t)high;
    channels[ch].sweeping = false; Serial.println("OK"); return;
  }
  if (!strcmp(op, "SWEEP") && sscanf(line.c_str(), "%*s %d %d %d %d", &ch, &a, &b, &c) == 4) {
    if (ch < 0 || ch >= kChannels || a <= 0 || b <= 0 || c <= 0 || a > updateHz / 2 || b > updateHz / 2) { Serial.println("ERR sweep range (frequencies must be <= UPDATE/2)"); return; }
    channels[ch].sweepStartHz = (uint32_t)a; channels[ch].sweepEndHz = (uint32_t)b;
    channels[ch].sweepMs = (uint32_t)c; channels[ch].sweeping = true;
    channels[ch].sweepT0 = millis(); channels[ch].frequency = (float)a;
    channels[ch].wave = W_SINE; Serial.println("OK"); return;
  }
  if (!strcmp(op, "STOP")) {
    if (sscanf(line.c_str(), "%*s %19s", arg) != 1 || !strcmp(arg, "ALL")) {
      for (uint8_t i = 0; i < kChannels; ++i) { channels[i].wave = W_STOP; channels[i].sweeping = false; }
    } else {
      char extra = 0;
      if (sscanf(arg, "%d%c", &ch, &extra) != 1 || ch < 0 || ch >= kChannels) { Serial.println("ERR channel"); return; }
      channels[ch].wave = W_STOP; channels[ch].sweeping = false;
    }
    Serial.println("OK"); return;
  }
  if (!strcmp(op, "RIPPLE") && sscanf(line.c_str(), "%*s %d", &ch) == 1 && ch >= 0 && ch < kChannels) {
    channels[ch].wave = W_STOP; writeChannel(ch, pwmTop / 2); Serial.println("OK scope ripple: DC midscale"); return;
  }
  if (!strcmp(op, "CROSSTALK") && sscanf(line.c_str(), "%*s %d", &ch) == 1 && ch >= 0 && ch < kChannels) {
    for (uint8_t i = 0; i < kChannels; ++i) { channels[i].wave = W_STOP; writeChannel(i, i == ch ? pwmTop : 0); }
    Serial.println("OK scope crosstalk: selected channel full scale, others zero"); return;
  }
  if (!strcmp(op, "SYNC")) {
    char mode[8] = {0};
    if (sscanf(line.c_str(), "%*s %7s", mode) != 1) { Serial.println("ERR SYNC ON|OFF"); return; }
    if (!strcmp(mode, "ON")) {
      if (!syncEnabled) { pinMode(kSyncPins[0], INPUT_PULLUP); pinMode(kSyncPins[1], INPUT_PULLUP); attachInterrupt(digitalPinToInterrupt(kSyncPins[0]), syncA, RISING); attachInterrupt(digitalPinToInterrupt(kSyncPins[1]), syncB, RISING); syncEnabled = true; }
      Serial.println("OK sync monitor (conditioned module SIG inputs only)");
    } else if (!strcmp(mode, "OFF")) {
      if (syncEnabled) { detachInterrupt(digitalPinToInterrupt(kSyncPins[0])); detachInterrupt(digitalPinToInterrupt(kSyncPins[1])); syncEnabled = false; }
      Serial.println("OK sync off");
    } else { Serial.println("ERR SYNC ON|OFF"); }
    return;
  }
  if (!strcmp(op, "SYNC?")) { Serial.print("SYNC A="); Serial.print(syncCount[0]); Serial.print(" last_us="); Serial.print(syncLastUs[0]); Serial.print(" B="); Serial.print(syncCount[1]); Serial.print(" last_us="); Serial.println(syncLastUs[1]); return; }
  Serial.println("ERR unknown command; HELP");
}

static float waveformUnit(Wave w, float phase) {
  phase -= floorf(phase);
  switch (w) {
    case W_SINE: return 0.5f + 0.5f * sinf(phase * 6.28318530718f);
    case W_TRIANGLE: return phase < 0.5f ? phase * 2.0f : 2.0f - phase * 2.0f;
    case W_SAW: case W_RAMP: return phase;
    case W_SQUARE: return phase < 0.5f ? 0.0f : 1.0f;
    case W_STAIR: return floorf(phase * 16.0f) / 15.0f;
    default: return 0.5f;
  }
}

static void updateWaves(uint32_t now) {
  const float t = now * 1.0e-6f;
  for (uint8_t i = 0; i < kChannels; ++i) {
    Channel &s = channels[i];
    if (s.wave == W_STOP) continue;
    if (s.sweeping) {
      const uint32_t elapsed = millis() - s.sweepT0;
      const float x = elapsed >= s.sweepMs ? 1.0f : (float)elapsed / s.sweepMs;
      s.frequency = expf(logf((float)s.sweepStartHz) * (1.0f - x) + logf((float)s.sweepEndHz) * x);
      if (x >= 1.0f) s.sweeping = false;
    }
    const float phase = t * s.frequency;
    const float u = waveformUnit(s.wave, phase);
    const uint16_t code = s.low + (uint16_t)lroundf(u * (s.high - s.low));
    writeChannel(i, code);
  }
  ++updates;
  const uint32_t elapsed = now - rateWindowStartUs;
  if (elapsed >= 1000000u) {
    measuredUpdateHz = (float)(updates - rateWindowUpdates) * 1000000.0f / elapsed;
    rateWindowStartUs = now;
    rateWindowUpdates = updates;
  }
}

void setup() {
  Serial.begin(115200);
  const uint32_t waitStart = millis();
  while (!Serial && millis() - waitStart < 1800) delay(10);
  for (uint8_t i = 0; i < kChannels; ++i) channels[i].raw = 0;
  configurePwm(pwmBits, requestedCarrier);
  nextUpdateUs = micros();
  rateWindowStartUs = nextUpdateUs;
  Serial.println("TROLLfx Bench Lab READY; outputs DISARMED");
  help(); reportInfo();
}

void loop() {
  static String line;
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c == '\n' || c == '\r') { if (line.length()) handleLine(line); line = ""; }
    else if (line.length() < 120) line += c;
  }
  const uint32_t now = micros();
  if ((int32_t)(now - nextUpdateUs) >= 0) {
    if ((uint32_t)(now - nextUpdateUs) > updatePeriodUs) ++overruns;
    nextUpdateUs += updatePeriodUs;
    updateWaves(now);
  }
}
