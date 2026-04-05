void foo(in float a, out float b, inout float c) {
    b = a + c;
    c = b;
}
