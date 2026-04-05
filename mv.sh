for file in *.src.hlsl
do
  mv "$file" "${file%.src.hlsl}.hlsl"
done
