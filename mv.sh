for file in *.src
do
  mv "$file" "${file%.html}.hlsl"
done
