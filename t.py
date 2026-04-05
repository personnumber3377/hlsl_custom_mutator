
import hlsl_parser, hlsl_unparser
import os

PARSE_TEST_FILE_DIR = "./parse_tests/"

HEADER_SIZE = 8

# Get the null bytes out...
def strip(buf: bytes) -> bytes:
	print(buf)
	print(type(buf))
	return buf[HEADER_SIZE:].rstrip("\x00")

def parse_tests():
	# Run the stuff and then check if parsing failure has occurred...
	test_files = os.listdir(PARSE_TEST_FILE_DIR)
	for fn in test_files:
		with open(PARSE_TEST_FILE_DIR+fn) as fh:
			data = strip(fh.read())
		# Run the parse test...
		try:
			tu = hlsl_parser.parse_to_tree(data)
			out = hlsl_unparser.unparse_tu(tu)
		except Exception as e:
			print("Got this exception here: "+str(e)+" for parse test file "+str(fn))
			return 1
	return 0

def main():
	# Main...
	# Run the parse tests first...
	res = parse_tests()
	if res:
		print("[FAILED]")
		return res
	print("[SUCCESS]")
	return 0

if __name__=="__main__":
	ret = main()
	exit(ret)
