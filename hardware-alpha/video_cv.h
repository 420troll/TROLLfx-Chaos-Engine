#pragma once
#include <stdint.h>
namespace video_cv {
// Diagnostic command code (not inverted PWM compare). Endpoints use measured
// local midpoints and full-span slope; B secondary provisional from B primary.
// Guarded nominal .05-.95 V until disconnected DMM verification.
struct Range { uint16_t low,high; };
constexpr Range ranges[4]={{1024,1169},{1018,1164},{1019,1164},{1019,1164}};
inline uint16_t duty(uint8_t ch,uint16_t signal){
    const Range r=ranges[ch];
    uint32_t code=r.low+((uint32_t(signal)*(r.high-r.low)+32767u)/65535u);
    return uint16_t(2047u-code);
}
}
