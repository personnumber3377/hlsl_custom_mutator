struct S {
    float x;
    float y;
};

float main() : SV_Target {
    S s;
    s.x = 1;
    return s.x;
}
