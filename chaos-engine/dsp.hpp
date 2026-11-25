#pragma once

#include <cmath>
#include <cstdint>

namespace chaos {
constexpr float kPi = 3.14159265358979323846f;
enum class Bank : uint8_t { Complex, Chaos, Geometry, Motion };
enum class Algo : uint8_t { A, B, C, D, E, F, G, H };

// Q16.16 primitives for a later integer-only ISR implementation.
struct Q16 {
  int32_t raw;
  static constexpr Q16 fromRaw(int32_t x) { return {x}; }
  static Q16 fromFloat(float x) {
    if (x > 32767.0f) x = 32767.0f;
    if (x < -32768.0f) x = -32768.0f;
    return {static_cast<int32_t>(x * 65536.0f)};
  }
  constexpr float toFloat() const { return static_cast<float>(raw) / 65536.0f; }
};
inline Q16 qmul(Q16 a, Q16 b) { return {static_cast<int32_t>((static_cast<int64_t>(a.raw) * b.raw) >> 16)}; }
inline Q16 qadd(Q16 a, Q16 b) { return {static_cast<int32_t>(static_cast<uint32_t>(a.raw) + static_cast<uint32_t>(b.raw))}; }
inline Q16 qsub(Q16 a, Q16 b) { return {static_cast<int32_t>(static_cast<uint32_t>(a.raw) - static_cast<uint32_t>(b.raw))}; }

struct State {
  float phase = 0.0f;
  float previousPhase = 0.0f;
  float x = 0.11f, y = 0.07f, z = 0.03f;
  float held = 0.0f;
  uint32_t rng = 0x8f7011eeu;
  uint32_t edge = 0;
};

inline float wrap01(float x) { return x - std::floor(x); }
inline float clamp11(float x) { return x < -1.0f ? -1.0f : (x > 1.0f ? 1.0f : x); }
inline float sine(float p) { return std::sin(p * 2.0f * kPi); }
inline uint32_t randomStep(uint32_t &x) {
  if (!x) x = 0x8f7011eeu;
  x ^= x << 13; x ^= x >> 17; x ^= x << 5;
  return x;
}

inline float render(Bank bank, Algo algo, State &s, float frequency, float sampleRate,
                    float a = 0.0f, float b = 0.0f) {
  const float dt = sampleRate > 0.0f ? 1.0f / sampleRate : 0.0f;
  s.previousPhase = s.phase;
  s.phase = wrap01(s.phase + frequency * dt);
  const float p = s.phase;
  float out = 0.0f;
  const uint8_t n = static_cast<uint8_t>(algo);
  if (bank == Bank::Complex) {
    const float sx = sine(p), sy = sine(p + a * 0.5f);
    switch (algo) {
      case Algo::A: out = sine(p + b * sx); break; // phase modulation
      case Algo::B: out = sine(p + a * sy); break; // frequency-like modulation
      case Algo::C: out = sx * sy; break; // ring modulation
      case Algo::D: { const float x = sx * (1.0f + 4.0f * a); out = 2.0f * std::fabs(x - std::floor(x + 0.5f)) - 1.0f; break; }
      case Algo::E: out = (sine(p) + sine(2*p) * a + sine(3*p) * b) / (1.0f + std::fabs(a) + std::fabs(b)); break;
      case Algo::F: out = sine(p * 0.5f + a); break;
      case Algo::G: out = static_cast<float>((static_cast<int32_t>(p * 65535.0f) ^ static_cast<int32_t>(a * 65535.0f)) & 0xffff) / 32767.5f - 1.0f; break;
      case Algo::H: s.held = clamp11(s.held * 0.985f + (sx + a * sy) * 0.18f); out = s.held; break;
    }
  } else if (bank == Bank::Chaos) {
    switch (algo) {
      case Algo::A: { // Lorenz, normalized and Euler-integrated at the sample tick
        const float dx = 10.0f * (s.y - s.x), dy = s.x * (28.0f - s.z) - s.y, dz = s.x*s.y - (8.0f/3.0f)*s.z;
        s.x += dx * dt * 12.0f; s.y += dy * dt * 12.0f; s.z += dz * dt * 12.0f; out = s.x / 24.0f; break;
      }
      case Algo::B: { const float dx = -s.y - s.z, dy = s.x + 0.2f*s.y, dz = 0.2f + s.z*(s.x - 5.7f); s.x += dx*dt*12; s.y += dy*dt*12; s.z += dz*dt*12; out=s.x/12; break; }
      case Algo::C: s.x = (3.57f + a*0.4f) * s.x * (1.0f-s.x); out = s.x*2.0f-1.0f; break;
      case Algo::D: { const float x=s.x, y=s.y; s.x=1.0f-1.4f*x*x+y; s.y=0.3f*x; out=s.x/1.5f; break; }
      case Algo::E: s.x = std::fmod(s.x + (s.y > 0 ? 0.37f : 0.17f), 1.0f); s.y = sine(p * 3.0f + s.x); out = s.x*2.0f-1.0f; break;
      case Algo::F: { const float dx=s.y, dy=-0.2f*s.y-s.x-0.25f*s.x*s.x*s.x+0.3f*sine(p); s.x+=dx*dt*20; s.y+=dy*dt*20; out=s.x/2.0f; break; }
      case Algo::G: out = (static_cast<float>(randomStep(s.rng) >> 8) / 8388607.5f) - 1.0f; s.held = 0.91f*s.held+0.09f*out; out=s.held; break;
      case Algo::H: { const float dx=10*(s.y-s.x), dy=s.x*(28-s.z)-s.y+0.3f*b, dz=s.x*s.y-(8.0f/3.0f)*s.z; s.x+=dx*dt*12; s.y+=dy*dt*12; s.z+=dz*dt*12; out=(s.x-s.y)/28; break; }
    }
  } else if (bank == Bank::Geometry) {
    switch (algo) {
      case Algo::A: out=sine(p); break; // horizontal
      case Algo::B: out=sine(p+a); break; // vertical
      case Algo::C: out=sine(p)*sine(p+b); break; // radial
      case Algo::D: out=sine(p+0.25f*sine(p*0.5f)); break; // spiral
      case Algo::E: out=(std::fmod(p*8.0f,1.0f)<0.5f?1.0f:-1.0f)*(std::fmod(p*4.0f,1.0f)<0.5f?1.0f:-1.0f); break;
      case Algo::F: out=sine(p*7.0f)*sine(p*7.0f+a); break; // moire
      case Algo::G: out=(static_cast<int>(p*16.0f)&1)?1.0f:-1.0f; break; // Walsh
      case Algo::H: out=sine(p*3.0f)*sine(p*3.17f+a); break;
    }
  } else {
    switch (algo) {
      case Algo::A: out=sine(p); break; // quadrature pair via phase input
      case Algo::B: out=sine(p+a); break; // Lissajous
      case Algo::C: out=sine(p+0.12f*sine(p*0.1f)); break; // orbit
      case Algo::D: out=sine(p+0.06f*sine(p*0.07f)); break; // pendulum
      case Algo::E: s.held=0.997f*s.held+0.003f*sine(p*0.09f); out=s.held; break;
      case Algo::F: out=(sine(p*0.03f)+sine(p*0.071f+a))*0.5f; break;
      case Algo::G: if (p < s.previousPhase) s.held=static_cast<float>(randomStep(s.rng)>>8)/8388607.5f-1.0f; out=s.held; break;
      case Algo::H: out=0.65f*sine(p*0.17f)+0.35f*sine(p*0.071f); break;
    }
  }
  (void)n;
  return clamp11(out);
}
}
