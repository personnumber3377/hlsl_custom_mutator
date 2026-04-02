from hlsl_input_format import Header, pack_blob

src = b"""[numthreads(1,1,1)]
void main(uint3 tid : SV_DispatchThreadID) {
  float x = 1.0;
  x = x + 2.0;
}
"""

blob = pack_blob(Header(exec_mode=0, sub_mode=0, src_mode=0, bits0=0, bits1=0, bits2=0), src)
open("seed.bin", "wb").write(blob)
