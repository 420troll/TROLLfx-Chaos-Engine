/*
Developed by Lucas Henry, May 2024

The main entry point file for the firmware, showing high-level logic.
*/

#include <Arduino.h>
#include <Adafruit_NeoPXL8.h>
#include <hardware/pwm.h>

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


// Temporary CV window, based on FP06 measurements. Normalized code increases
// with voltage; actual PWM duty is inverted. No factory output offsets here.
// Conservative nominal 0.1–0.9 V; B secondary is unmeasured and held at
// provisional zero-ish code. Do not connect any output before bench verification.
static constexpr uint16_t cvLow[4]={1033,1026,1028,1028};
static constexpr uint16_t cvHigh[4]={1161,1155,1156,1028};
static uint16_t cvDuty(uint8_t ch,uint16_t value) {
    uint32_t code=cvLow[ch]+((uint32_t)value*(cvHigh[ch]-cvLow[ch])+32767u)/65535u;
    return 2047u-code;
}
static uint16_t cvSetupPair(uint8_t p1,uint8_t p2,uint8_t ch) {
    uint16_t slice=pwm_gpio_to_slice_num(p1);
    pwm_set_enabled(slice,false);
    pwm_set_wrap(slice,2047);
    pwm_set_gpio_level(p1,cvDuty(ch,0));
    pwm_set_gpio_level(p2,cvDuty(ch+1,0));
    gpio_set_function(p1,GPIO_FUNC_PWM);
    gpio_set_function(p2,GPIO_FUNC_PWM);
    pwm_set_enabled(slice,true);
    return slice;
}
// Extra video-CV algorithms: continuous phase, integer math only.
// Shape and ratio are original calibrated controls (0..2047).
static uint16_t tri16(uint16_t p) {
    return p<32768u ? (uint16_t)(p*2u) : (uint16_t)((65535u-p)*2u);
}
static uint16_t cvQuadrature(Waveformer& main, Waveformer&, Modulator&) {
    return tri16((uint16_t)((main.core.acc >> 16)+16384u));
}
static uint16_t cvFold(Waveformer& main, Waveformer&, Modulator&) {
    return tri16((uint16_t)(((uint32_t)main.val*(2048u+7u*main.shp))>>11));
}
static uint16_t cvCrossPhase(Waveformer& main, Waveformer& aux, Modulator&) {
    uint32_t shift=((uint32_t)aux.val*main.shp)>>11;
    return tri16((uint16_t)((main.core.acc>>16)+shift));
}
static uint16_t cvHarmonic(Waveformer& main, Waveformer&, Modulator&) {
    uint32_t p=main.core.acc>>16;
    uint32_t n=1u+((uint32_t)main.rat*7u>>11);
    return (uint16_t)(((uint32_t)tri16((uint16_t)(p*n))+tri16((uint16_t)p))/2u);
}
// --- SELECTED RING ALGORITHMS ---
// on the front panel, runs clockwise starting at the bottom
algo_f_ptr algo_arr[16] = {
    sine_pm,
    cvFold,
    cvQuadrature,
    double_freq,
    invert,
    half_freq,
    sum,
    amplitude_mod,
    harmonic_fm,
    frequency_mod,
    crosscrush,
    sample_and_hold,
    rungle,
    exclusive_or,
    cvCrossPhase,
    cvHarmonic   
};

// --- GLOBAL VARIABLES ---
int8_t led_pins[8] = LED_DATA;  // pin setup for led strip
Adafruit_NeoPXL8 leds(NUM_LEDS, led_pins, NEO_GRB);  // led strip controller
LedRing ring(ALGO_ENC_1, ALGO_ENC_2, ALGO_BTN);  // algorithm ring controller
LedRing* _LEDRING = &ring; // used for internal ISR stuff
OneButton follow_btn(FLW_BTN, false, false);  // follow button

Waveformer a(true,  MUX_A, LIN_TIME_A);  // left side waveform generator
Waveformer b(false, MUX_B, LIN_TIME_B);  // right side waveform generator
Modulator mod_a(a, b, ring, algo_arr);  // left side waveform modulator
Modulator mod_b(b, a, ring, algo_arr);  // right side waveform modulator

NVMWrapper nvm;  // interface for loading/storing config data

bool save_mod_pos_flag;  // flag raised when user triggers encoder position save
uint16_t a_pwm_slice, b_pwm_slice;  // hardware PWM slices allocated to A and B
bool calibrating = false;  // indicates code is in a calibration state
repeating_timer_t pwm_timer;

// --- FORWARD DECLARATIONS ---
void encoder_long_press_ISR();
void follow_ISR();
bool pwm_timer_ISR(repeating_timer_t* rt);
void a_sync_ISR();
void b_sync_ISR();
void write_other_leds();

// --- CORE 0 SETUP/LOOP ---
void setup() {
    analogReadResolution(BITS_ADC);
    Serial.begin(9600);

    // initialize objects
    a.init(&b);
    b.init(&a);
    nvm = NVMWrapper();
    a.configs = nvm.get_config_data(true);
    b.configs = nvm.get_config_data(false);
    ring.reversed = nvm.get_encoder_direction();
    if (nvm.get_follow()) {
        b.toggle_follow_mode();
    }
    leds.begin();
    leds.setBrightness(0x70);

    // Factory calibration is read only for this experiment.

    // No EEPROM saving or PWM disabling in this experiment.
    ring.begin(0, 2);

    follow_btn.attachClick(follow_ISR);
}

void loop() {
    // read inputs
    a.read();
    b.read();
    follow_btn.tick();
    ring.update(a.mod_idx, b.mod_idx);
    
    ring.write_leds(leds);
    write_other_leds();
    leds.show();
}


// --- CORE 1 SETUP/LOOP ---
void setup1() {
    // setup outputs
    a_pwm_slice = cvSetupPair(PRI_OUT_A, SEC_OUT_A, 0);
    b_pwm_slice = cvSetupPair(PRI_OUT_B, SEC_OUT_B, 2);
    pinMode(TRIG_OUT_A, OUTPUT);
    pinMode(TRIG_OUT_B, OUTPUT);

    // timer setup
    int64_t timer_period_us = - (1000 / PWM_FREQ_kHz);  // negative means include execution time in period
    alarm_pool_t* pool = alarm_pool_create(0, 1);
    alarm_pool_add_repeating_timer_us(pool, timer_period_us, pwm_timer_ISR, NULL, &pwm_timer);

    // interrupt setup
    attachInterrupt(digitalPinToInterrupt(SIG_IN_A), a_sync_ISR, FALLING);
    attachInterrupt(digitalPinToInterrupt(SIG_IN_B), b_sync_ISR, FALLING);
}

void loop1() {}


// --- OTHER FUNCTIONS ---

bool pwm_timer_ISR(repeating_timer_t* rt) {
    if (calibrating) return true;
    // increment phasors etc.
    a.update();
    b.update();

    // create new outputs
    a.generate();
    b.generate();
    mod_a.generate();
    mod_b.generate();

    pwm_set_gpio_level(PRI_OUT_A, cvDuty(0,a.val));
    pwm_set_gpio_level(SEC_OUT_A, cvDuty(1,mod_a.val));
    pwm_set_gpio_level(PRI_OUT_B, cvDuty(2,b.val));
    pwm_set_gpio_level(SEC_OUT_B, cvDuty(3,mod_b.val));

    gpio_put(TRIG_OUT_A, !a.end_of_cycle);
    gpio_put(TRIG_OUT_B, !b.end_of_cycle);
    return true;
}

void write_other_leds() {
    uint8_t a_brightness = a.val >> 8;
    uint8_t a_mod_brightness = mod_a.val >> 8;

    uint8_t b_brightness = b.val >> 8;
    uint8_t b_mod_brightness = 0;

    // write signal indicators
    leds.setPixelColor(PRI_A_LED, (!a.running)? 0 : a_brightness_table[a_brightness]);
    leds.setPixelColor(SEC_A_LED, (!a.running && !mod_a.running)? 0 : a_brightness_table[a_mod_brightness]);
    leds.setPixelColor(PRI_B_LED, (!b.running)? 0 : b_brightness_table[b_brightness]);
    leds.setPixelColor(SEC_B_LED, (!b.running && !mod_b.running)? 0 : b_brightness_table[b_mod_brightness]);

    // write trig LEDs
    leds.setPixelColor(TRIG_A_LED, (a.eos_led)? a_colour : black);
    leds.setPixelColor(TRIG_B_LED, (b.eos_led)? b_colour : black);

    // write follow LED
    leds.setPixelColor(FLW_LED, (b.follow_mode != DISABLED)? mix_colour : black);
}

// responsible for triggering saving code
void encoder_long_press_ISR() {
    // Intentionally disabled: preserve factory EEPROM and output state.
}

// called when the follow button is pressed
void follow_ISR() {
    b.toggle_follow_mode();
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
