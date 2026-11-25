#include "../chaos-engine/dsp.hpp"
#include <cassert>
#include <cmath>
#include <cstdio>

int main() {
  auto q=chaos::qmul(chaos::Q16::fromFloat(1.5f),chaos::Q16::fromFloat(-2.0f));
  assert(std::fabs(q.toFloat()+3.0f)<0.0001f);
  for(int bank=0;bank<4;bank++) for(int algo=0;algo<8;algo++) {
    chaos::State s;
    float lo=2,hi=-2;
    for(int i=0;i<10000;i++) {
      const float v=chaos::render(static_cast<chaos::Bank>(bank),static_cast<chaos::Algo>(algo),s,17.0f,12000.0f,0.2f,-0.1f);
      assert(std::isfinite(v)); assert(v>=-1.0f && v<=1.0f);
      if(v<lo) lo=v;
      if(v>hi) hi=v;
    }
    assert(lo<=hi);
  }
  chaos::State a,b;
  for(int i=0;i<12000;i++) assert(chaos::render(chaos::Bank::Chaos,chaos::Algo::G,a,30,12000)==chaos::render(chaos::Bank::Chaos,chaos::Algo::G,b,30,12000));
  std::puts("DSP tests passed: Q16 multiply, 32 algorithms finite/bounded, deterministic RNG");
}
