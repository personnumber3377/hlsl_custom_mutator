float foo(float x) { return x; }
float foo(float2 x) { return x.x; }

float main() : SV_Target {
    return foo(1.0);
}
