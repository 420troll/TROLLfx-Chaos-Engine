// Prototype signal core. Original SpellTwister controls/calibration remain in
// upstream/; hardware-panel integration is staged as a branch-level change.
#include <Arduino.h>
#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pwm.h>
#include <string.h>
#include "dsp.hpp"

static constexpr uint8_t kPins[4] = {13, 12, 1, 0};
static constexpr uint8_t kBits = 11;
static constexpr uint16_t kTop = (1u << kBits) - 1;
static constexpr uint32_t kCarrierHz = 44100;
static constexpr uint32_t kUpdateHz = 12000;
static chaos::Bank banks[4] = {chaos::Bank::Complex, chaos::Bank::Complex, chaos::Bank::Geometry, chaos::Bank::Motion};
static chaos::Algo algos[4] = {chaos::Algo::A, chaos::Algo::C, chaos::Algo::A, chaos::Algo::A};
static chaos::State states[4];
static float frequency[4] = {1.0f, 1.01f, 0.5f, 0.37f};
static bool armed = false;
static uint32_t missedTicks = 0;

static void allCode(uint8_t ch, uint16_t code) { pwm_set_gpio_level(kPins[ch], armed ? code : 0); }
static bool parseBank(const char *s, chaos::Bank &b) {
  if (!strcmp(s,"complex")) b=chaos::Bank::Complex;
  else if (!strcmp(s,"chaos")) b=chaos::Bank::Chaos;
  else if (!strcmp(s,"geometry")) b=chaos::Bank::Geometry;
  else if (!strcmp(s,"motion")) b=chaos::Bank::Motion;
  else return false;
  return true;
}
static void command(String line) {
  char op[20]={0}, val[20]={0}; int ch=-1, a=0; float f=0;
  if (sscanf(line.c_str(),"%19s",op)!=1) return;
  if (!strcmp(op,"ARM")) { armed=true; for(uint8_t i=0;i<4;i++) allCode(i,kTop/2); Serial.println("OK armed"); return; }
  if (!strcmp(op,"DISARM")) { armed=false; for(uint8_t i=0;i<4;i++) allCode(i,0); Serial.println("OK disarmed"); return; }
  if (!strcmp(op,"INFO")) { Serial.print("INFO armed=");Serial.print(armed);Serial.print(" carrier_hz=");Serial.print(kCarrierHz);Serial.print(" update_hz=");Serial.print(kUpdateHz);Serial.print(" missed_ticks=");Serial.println(missedTicks);return; }
  if (!strcmp(op,"BANK") && sscanf(line.c_str(),"%*s %d %19s",&ch,val)==2 && ch>=0&&ch<4) {
    if(!parseBank(val,banks[ch])) Serial.println("ERR bank"); else Serial.println("OK"); return;
  }
  if (!strcmp(op,"ALGO") && sscanf(line.c_str(),"%*s %d %d",&ch,&a)==2 && ch>=0&&ch<4&&a>=0&&a<8) { algos[ch]=static_cast<chaos::Algo>(a); Serial.println("OK"); return; }
  if (!strcmp(op,"FREQ") && sscanf(line.c_str(),"%*s %d %f",&ch,&f)==2 && ch>=0&&ch<4&&f>0&&f<10000) { frequency[ch]=f; Serial.println("OK"); return; }
  Serial.println("Commands: ARM DISARM INFO | BANK ch complex|chaos|geometry|motion | ALGO ch 0..7 | FREQ ch hz");
}
void setup() {
  Serial.begin(115200); delay(300);
  const float div=static_cast<float>(clock_get_hz(clk_sys))/(kCarrierHz*(kTop+1));
  for(uint8_t i=0;i<4;i++) { const uint8_t pin=kPins[i]; const uint slice=pwm_gpio_to_slice_num(pin); pwm_config c=pwm_get_default_config();pwm_config_set_wrap(&c,kTop);pwm_config_set_clkdiv(&c,div);gpio_set_function(pin,GPIO_FUNC_PWM);pwm_init(slice,&c,true);allCode(i,kTop/2); }
  Serial.println("TROLLfx Chaos Engine prototype READY; outputs DISARMED");
}
void loop() {
  static String line; while(Serial.available()){char c=Serial.read();if(c=='\n'||c=='\r'){if(line.length())command(line);line="";}else if(line.length()<100)line+=c;}
  static uint32_t last=micros(); const uint32_t period=1000000u/kUpdateHz, now=micros();
  if((int32_t)(now-last)>=(int32_t)period){if((uint32_t)(now-last)>period*2)++missedTicks;last+=period;
    for(uint8_t i=0;i<4;i++){const float v=chaos::render(banks[i],algos[i],states[i],frequency[i],kUpdateHz,states[(i+1)&3].x,states[(i+1)&3].y);allCode(i,static_cast<uint16_t>((v+1.0f)*0.5f*kTop));}
  }
}
