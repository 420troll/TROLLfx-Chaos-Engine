/*
Developed by Lucas Henry, May 2024

The main entry point file for the firmware, showing high-level logic.
*/

#include <Arduino.h>
#include <Adafruit_NeoPXL8.h>
#include <hardware/pwm.h>
#include <pico/time.h>
#include <cmath>
#include <atomic>
#include <cstring>
#include <cstdlib>
#include "video_cv.h"

#include "src/classes/Waveformer/waveformer.h"
#include "src/classes/LedRing/led_ring.h"
#include "src/classes/Modulator/modulator.h"
#include "src/classes/NVMWrapper/nvm_wrapper.h"
#include "src/hardware/pins.h"
#include "src/hardware/misc_functions.h"
#include "src/hardware/calibration.h"
#include "src/constants.hpp"
#include "src/wave_algos/generator.h"
#include "src/wave_algos/mod_algorithms.h"
#include "src/tables/colours.h"


// Video-specific secondary-output functions. All return normalized 16-bit signals.
static uint16_t video_sine(uint32_t phase) { return sine_table[phase >> 21]; }
static uint16_t video_quadrature(Waveformer& m, Waveformer&, Modulator& mod) {
    mod.running=false; return video_sine(m.core.acc+0x40000000u);
}
static uint16_t video_phase(Waveformer& m, Waveformer& aux, Modulator& mod) {
    mod.running=false;
    uint32_t offset=uint32_t(aux.val)*uint32_t(m.shp+1)*32u;
    return video_sine(m.core.acc+offset);
}
static uint16_t video_fold(Waveformer& m, Waveformer&, Modulator& mod) {
    mod.running=false; uint32_t x=(uint32_t(m.val)*(2048u+7u*m.shp))>>11;
    x &= 131071u; return uint16_t(x>65535u?131071u-x:x);
}
static uint16_t video_harmonic(Waveformer& m, Waveformer&, Modulator& mod) {
    mod.running=false; uint32_t n=1u+(m.rat>>8);
    return uint16_t((uint32_t(video_sine(m.core.acc))+2u*video_sine(m.core.acc*n))/3u);
}
static uint16_t video_logistic(Waveformer& m, Waveformer&, Modulator& mod) {
    mod.running=false;
    if(m.core.overflow) {
        uint32_t x=mod.param_a?mod.param_a:24248u;
        uint32_t product=(x*(65535u-x))>>16;
        uint32_t gain=13926u+(uint32_t(m.shp)*2450u>>11);
        mod.param_a=uint16_t((product*gain)>>12);
    }
    return mod.param_a?mod.param_a:24248u;
}
struct Attractor { float x=.11f,y=.07f,z=.03f; uint16_t divider=0; uint16_t target=32768; int32_t smooth=32768; };
static Attractor attractors[2][2];
static uint16_t video_attractor(Waveformer& m, Modulator& mod, bool rossler) {
    mod.running=false;
    Attractor& s=attractors[m.is_a?0:1][rossler?1:0];
    // Decimated integration: one step per 128 DSP callbacks, interpolated output.
    if(++s.divider>=128) {
        s.divider=0;
        float f=float(m.core.pha)*(45454.545f/4294967296.0f);
        float dt=(rossler?.018f:.006f)*f;
        if(dt>.025f)dt=.025f;
        if(dt<.000001f)dt=.000001f;
        const float x=s.x,y=s.y,z=s.z;
        if(rossler) { s.x+=dt*(-y-z); s.y+=dt*(x+.2f*y); s.z+=dt*(.2f+z*(x-(3.5f+3.f*m.shp/2047.f))); }
        else { s.x+=dt*10.f*(y-x); s.y+=dt*(x*(18.f+22.f*m.shp/2047.f-z)-y); s.z+=dt*(x*y-2.666667f*z); }
        if(!std::isfinite(s.x+s.y+s.z)||fabsf(s.x)>100||fabsf(s.y)>100||fabsf(s.z)>100) { s.x=.11f;s.y=.07f;s.z=.03f; }
        float v=.5f+s.x*(rossler?.04f:.022f);
        if(v<0)v=0;if(v>1)v=1;s.target=uint16_t(v*65535.f);
    }
    s.smooth+=(int32_t(s.target)-s.smooth)/16;
    return uint16_t(s.smooth);
}
static uint16_t video_lorenz(Waveformer& m, Waveformer&, Modulator& mod) {return video_attractor(m,mod,false);}
static uint16_t video_rossler(Waveformer& m, Waveformer&, Modulator& mod) {return video_attractor(m,mod,true);}
static uint16_t video_smooth_random(Waveformer& m, Waveformer&, Modulator& mod) {
    mod.running=false;
    if(m.core.overflow) mod.param_a=uint16_t(rand_u32()>>16);
    int32_t delta=int32_t(mod.param_a)-mod.param_b;
    int32_t step=delta/64;
    if(!step&&delta)step=delta>0?1:-1;
    mod.param_b=uint16_t(int32_t(mod.param_b)+step);
    return mod.param_b;
}

// --- SELECTED RING ALGORITHMS ---
// on the front panel, runs clockwise starting at the bottom
algo_f_ptr algo_arr[16] = {
    video_quadrature, video_phase, video_fold, video_harmonic,
    video_logistic, video_lorenz, video_rossler, video_smooth_random,
    phase_offset, double_freq, half_freq, amplitude_mod,
    harmonic_fm, frequency_mod, sample_and_hold, exclusive_or   
};

// --- GLOBAL VARIABLES ---
int8_t led_pins[8] = LED_DATA;  // pin setup for led strip
Adafruit_NeoPXL8 leds(NUM_LEDS, led_pins, NEO_GRB);  // led strip controller
LedRing ring(ALGO_ENC_1, ALGO_ENC_2, ALGO_BTN);  // algorithm ring controller
LedRing* _LEDRING = &ring; // used for internal ISR stuff
// Follow button is debounced locally; click sequences are resolved before changing Follow.

Waveformer a(true,  MUX_A, LIN_TIME_A);  // left side waveform generator
Waveformer b(false, MUX_B, LIN_TIME_B);  // right side waveform generator
Modulator mod_a(a, b, ring, algo_arr);  // left side waveform modulator
Modulator mod_b(b, a, ring, algo_arr);  // right side waveform modulator

NVMWrapper nvm;  // interface for loading/storing config data

static std::atomic<bool> panelReady{false};
static std::atomic<uint32_t> dspMeter{0}; // low byte: percent, bit 8: deadline fault
static bool cpuView=false;
static std::atomic<uint32_t> meterLevels{0}, cycleCountsA{0},cycleCountsB{0}, callbackRate{0}, faultCount{0}, maxCallbackUs{0}, timerStatus{0};
static std::atomic<uint32_t> phaseA{0},phaseB{0};
static uint32_t cycleA=0,cycleB=0,windowTicks=0,windowMax=0;
static uint16_t peaks[4]={0,0,0,0};
static uint32_t seenCycleA=0,seenCycleB=0,lastCycleA=0,lastCycleB=0;
static uint32_t lastLedMs=0,selectionMs=0;
static int lastA=-1,lastB=-1;
static bool lastActive=true;
static void write_selection_ring(uint32_t now);
static constexpr uint32_t kRun=65536u;
static std::atomic<uint32_t> dcOverride{kRun};
void poll_serial();
static constexpr uint32_t dspPeriodUs=22;
static uint32_t lastTick=0, windowStart=0, workUs=0, deadlineFaults=0;
static bool tickSeen=false;
static uint32_t missedTotal=0;
uint16_t a_pwm_slice, b_pwm_slice;  // hardware PWM slices allocated to A and B
bool calibrating = false;  // indicates code is in a calibration state
repeating_timer_t pwm_timer;

// --- FORWARD DECLARATIONS ---
void poll_follow();
void write_cpu_ring();
bool pwm_timer_ISR(repeating_timer_t* rt);
void a_sync_ISR();
void b_sync_ISR();
void write_other_leds();

// --- CORE 0 SETUP/LOOP ---
void setup() {
    analogReadResolution(BITS_ADC);
    Serial.begin(115200);

    // initialize objects
    a.init(&b);
    b.init(&a);
    nvm = NVMWrapper();
    a.configs = nvm.get_config_data(true);
    b.configs = nvm.get_config_data(false);
    ring.reversed = nvm.get_encoder_direction();
    a.follow_mode=DISABLED;
    b.follow_mode=DISABLED;
    leds.begin();
    leds.setBrightness(255);
    leds.fill(0);leds.show();

    // Factory calibration read only. No EEPROM writes or calibration entry.
    pinMode(FLW_BTN, INPUT);
    ring.begin(0, 0);
    panelReady.store(true,std::memory_order_release);
}

void loop() {
    // read inputs
    a.read();
    b.read();
    poll_follow();
    poll_serial();
    ring.update(a.mod_idx, b.mod_idx);
    
    const uint32_t now=millis();
    if(ring.a_idx_wo_cv!=lastA||ring.b_idx_wo_cv!=lastB||ring.a_is_active!=lastActive){
        lastA=ring.a_idx_wo_cv;lastB=ring.b_idx_wo_cv;lastActive=ring.a_is_active;selectionMs=now;
    }
    if(now-lastLedMs>=33u){
        lastLedMs=now;
        leds.fill(0);
        if(cpuView)write_cpu_ring();else write_selection_ring(now);
        write_other_leds();
        leds.show();
    }
}


// --- CORE 1 SETUP/LOOP ---
void setup1() {
    // Configure compare values before enabling PWM or assigning output pins.
    const uint8_t pins[4]={PRI_OUT_A,SEC_OUT_A,PRI_OUT_B,SEC_OUT_B};
    for(uint8_t i=0;i<4;i++){
        uint slice=pwm_gpio_to_slice_num(pins[i]);
        pwm_set_enabled(slice,false);
        pwm_set_wrap(slice,2047);
        pwm_set_clkdiv(slice,1.0f);
        pwm_set_gpio_level(pins[i],video_cv::duty(i,0));
    }
    for(uint8_t i=0;i<4;i++)gpio_set_function(pins[i],GPIO_FUNC_PWM);
    a_pwm_slice=pwm_gpio_to_slice_num(PRI_OUT_A);
    b_pwm_slice=pwm_gpio_to_slice_num(PRI_OUT_B);
    pwm_set_enabled(a_pwm_slice,true);pwm_set_enabled(b_pwm_slice,true);
    while(!panelReady.load(std::memory_order_acquire))delay(1);
    pinMode(TRIG_OUT_A, OUTPUT);
    pinMode(TRIG_OUT_B, OUTPUT);

    // timer setup
    int64_t timer_period_us = -int64_t(dspPeriodUs);  // negative means include execution time in period
    alarm_pool_t* pool = alarm_pool_create_with_unused_hardware_alarm(1);
    bool ok=pool&&alarm_pool_add_repeating_timer_us(pool, timer_period_us, pwm_timer_ISR, NULL, &pwm_timer);
    timerStatus.store(ok?1u:2u,std::memory_order_relaxed);
    if(!ok)return;

    // interrupt setup
    attachInterrupt(digitalPinToInterrupt(SIG_IN_A), a_sync_ISR, FALLING);
    attachInterrupt(digitalPinToInterrupt(SIG_IN_B), b_sync_ISR, FALLING);
}

void loop1() {}


// --- OTHER FUNCTIONS ---

bool pwm_timer_ISR(repeating_timer_t* rt) {
    const uint32_t begin=time_us_32();
    if(tickSeen && uint32_t(begin-lastTick)>dspPeriodUs+5){++deadlineFaults;++missedTotal;}
    if(!tickSeen){windowStart=begin;tickSeen=true;}
    lastTick=begin;
    // increment phasors etc.
    const bool ar=a.running,br=b.running;
    a.update();
    b.update();
    if(ar&&a.core.overflow)++cycleA;
    if(br&&b.core.overflow)++cycleB;

    // create new outputs
    a.generate();
    b.generate();
    mod_a.generate();
    mod_b.generate();

    // Normalized waveforms are independent of the physical voltage mapping.
    uint16_t ap=a.running?a.val:0, bp=b.running?b.val:0;
    uint16_t as=(a.running||mod_a.running)?mod_a.val:0;
    uint16_t bs=(b.running||mod_b.running)?mod_b.val:0;
    const uint32_t dc=dcOverride.load(std::memory_order_relaxed);
    if(dc!=kRun)ap=as=bp=bs=uint16_t(dc);
    pwm_set_gpio_level(PRI_OUT_A,video_cv::duty(0,ap));
    pwm_set_gpio_level(SEC_OUT_A,video_cv::duty(1,as));
    pwm_set_gpio_level(PRI_OUT_B,video_cv::duty(2,bp));
    pwm_set_gpio_level(SEC_OUT_B,video_cv::duty(3,bs));

    const uint16_t vals[4]={ap,as,bp,bs};
    // Peak envelope from actual normalized values written to PWM, independent of PWM codes.
    for(uint8_t i=0;i<4;i++){
        if(vals[i]>=peaks[i])peaks[i]=vals[i];
        else if(peaks[i]>8)peaks[i]-=8;
        else peaks[i]=0;
    }
    // Publish only once per ~1.4 ms, not on every sample.
    if((++windowTicks&63u)==0){
        meterLevels.store((uint32_t(peaks[0]>>8))|(uint32_t(peaks[1]>>8)<<8)|(uint32_t(peaks[2]>>8)<<16)|(uint32_t(peaks[3]>>8)<<24),std::memory_order_relaxed);
        cycleCountsA.store(cycleA,std::memory_order_relaxed);cycleCountsB.store(cycleB,std::memory_order_relaxed);
        phaseA.store(a.core.pha,std::memory_order_relaxed);phaseB.store(b.core.pha,std::memory_order_relaxed);
    }
    gpio_put(TRIG_OUT_A, !a.end_of_cycle);
    gpio_put(TRIG_OUT_B, !b.end_of_cycle);
    const uint32_t elapsed=time_us_32()-begin;
    workUs+=elapsed;
    if(elapsed>windowMax)windowMax=elapsed;
    if(elapsed>=dspPeriodUs){++deadlineFaults;++missedTotal;}
    const uint32_t span=begin-windowStart;
    if(span>=250000u){
        uint32_t percent=workUs*100u/span;
        if(percent>100)percent=100;
        dspMeter.store(percent|(deadlineFaults?256u:0u),std::memory_order_relaxed);
        callbackRate.store(uint32_t(uint64_t(windowTicks)*1000000ull/span),std::memory_order_relaxed);
        faultCount.store(deadlineFaults,std::memory_order_relaxed);
        maxCallbackUs.store(windowMax,std::memory_order_relaxed);
        workUs=0;deadlineFaults=0;windowTicks=0;windowMax=0;windowStart=begin;
    }
    return true;
}

static uint32_t side_color(bool sideA,uint8_t v){
    return sideA?leds.Color(v,uint8_t(uint16_t(v)*55/100),0):leds.Color(0,0,v);
}
static void write_selection_ring(uint32_t now){
    static const uint8_t palette[16][3]={
      {255,255,255},{220,0,180},{255,70,0},{255,220,0},
      {120,255,0},{0,220,100},{0,210,255},{70,80,255},
      {160,60,255},{255,0,60},{255,130,80},{30,220,180},
      {170,255,90},{80,170,255},{230,100,220},{255,255,80}};
    uint8_t ai=uint8_t(ring.a_idx_wo_cv)&15u,bi=uint8_t(ring.b_idx_wo_cv)&15u;
    uint8_t selected=ring.a_is_active?ai:bi,other=ring.a_is_active?bi:ai;
    if(other!=selected)leds.setPixelColor(other,side_color(!ring.a_is_active,24));
    // Brief algorithm colour on selection, then steady selected side colour.
    bool accent=now-selectionMs<360u&&((now-selectionMs)/120u)%2u==0;
    leds.setPixelColor(selected,accent?leds.Color(palette[selected][0],palette[selected][1],palette[selected][2]):side_color(ring.a_is_active,200));
}
void write_other_leds(){
    const uint32_t dc=dcOverride.load(std::memory_order_relaxed);
    const uint32_t levels=meterLevels.load(std::memory_order_relaxed);
    const uint8_t pins[4]={PRI_A_LED,SEC_A_LED,PRI_B_LED,SEC_B_LED};
    for(uint8_t i=0;i<4;i++){
        uint8_t v=dc==kRun?uint8_t(levels>>(8*i)):uint8_t(dc>>8);
        leds.setPixelColor(pins[i],side_color(i<2,v));
    }
    const uint32_t now=millis(),ca=cycleCountsA.load(),cb=cycleCountsB.load();
    if(ca!=seenCycleA){seenCycleA=ca;lastCycleA=now;}
    if(cb!=seenCycleB){seenCycleB=cb;lastCycleB=now;}
    leds.setPixelColor(TRIG_A_LED,ca&&now-lastCycleA<75u?side_color(true,200):0);
    leds.setPixelColor(TRIG_B_LED,cb&&now-lastCycleB<75u?side_color(false,200):0);
    leds.setPixelColor(FLW_LED,b.follow_mode!=DISABLED?mix_colour:0);
}

// A single click is deferred until the 600 ms sequence expires.
// Double click is ignored. Three releases within the window toggle CPU view.
void poll_follow(){
    static bool raw=false,stable=false;
    static uint32_t changed=0, first=0;
    static uint8_t clicks=0;
    const uint32_t now=millis();
    bool v=digitalRead(FLW_BTN)==HIGH;
    if(v!=raw){raw=v;changed=now;}
    if(clicks && now-first>=600u){if(clicks==1)b.toggle_follow_mode();clicks=0;}
    if(raw!=stable && now-changed>=20u){
        stable=raw;
        if(!stable){
            if(!clicks)first=now;
            if(++clicks==3){cpuView=!cpuView;clicks=0;}
        }
    }
}
void write_cpu_ring(){
    static int32_t filtered=-1;
    uint32_t m=dspMeter.load(std::memory_order_relaxed);
    int32_t target=int32_t(m&255u)*256;
    if(filtered<0)filtered=target;else filtered+=(target-filtered)/8;
    uint8_t lit=uint8_t((filtered*16+25599)/25600);
    if(lit>16)lit=16;
    for(uint8_t i=0;i<16;i++){
        uint32_t color=i<10?leds.Color(0,160,15):i<13?leds.Color(180,120,0):leds.Color(200,0,0);
        leds.setPixelColor(i,i<lit?color:0);
    }
    // Steady top red marker for timing faults, never flash the whole ring.
    if(m&256u)leds.setPixelColor(15,leds.Color(200,0,0));
    if(timerStatus.load()==2)leds.setPixelColor(0,leds.Color(200,0,200));
}

// called when rising input trigger detected on A sync
void a_sync_ISR() {
    a.reset();
    a.running = true;
    if (b.follow_mode != DISABLED) b_sync_ISR();
}

// called when rising input trigger detected on B sync
void b_sync_ISR() {
    b.reset();
    b.running = true;
}

void poll_serial(){
    static char buf[40];static uint8_t n=0;static bool discard=false;
    for(uint8_t budget=0;budget<32&&Serial.available();++budget){
        char c=char(Serial.read());
        if(c=='\r'||c=='\n'){
            if(discard){discard=false;n=0;continue;}
            if(!n)continue;
            buf[n]=0;n=0;
            if(!strcmp(buf,"RUN")){dcOverride.store(kRun);Serial.println("OK RUN");}
            else if(!strncmp(buf,"DC ",3)){
                char* end=nullptr;long p=strtol(buf+3,&end,10);
                if(end==buf+3||*end||p<0||p>100){Serial.println("ERR DC 0..100");continue;}
                dcOverride.store(uint32_t((p*65535L+50)/100));Serial.println("OK DC");
            }else if(!strcmp(buf,"INFO")){
                uint32_t m=dspMeter.load();Serial.print("Chaos hardware alpha; DSP load ");
                Serial.print(m&255u);Serial.print("%; faults/window ");Serial.print(faultCount.load());
                Serial.print("; callbacks/s ");Serial.print(callbackRate.load());
                Serial.print("; max callback us ");Serial.print(maxCallbackUs.load());
                Serial.print("; timer status ");Serial.println(timerStatus.load());
                Serial.print("A mode ");Serial.print(int(a.mode));Serial.print(" time ADC ");Serial.print(a.raw_vals.fm);
                Serial.print(" pitch ADC ");Serial.print(a.raw_vals.pitch);Serial.print(" phase increment ");Serial.print(phaseA.load());
                Serial.print(" cycles ");Serial.println(cycleCountsA.load());
                Serial.print("B mode ");Serial.print(int(b.mode));Serial.print(" time ADC ");Serial.print(b.raw_vals.fm);
                Serial.print(" pitch ADC ");Serial.print(b.raw_vals.pitch);Serial.print(" phase increment ");Serial.print(phaseB.load());
                Serial.print(" cycles ");Serial.println(cycleCountsB.load());
                Serial.print("Packed output LED levels ");Serial.println(meterLevels.load(),HEX);
            }else Serial.println("DC 0..100 | RUN | INFO");
        }else if(!discard){if(n<sizeof(buf)-1)buf[n++]=c;else{discard=true;n=0;}}
    }
}
