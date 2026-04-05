
import hlsl_parser, hlsl_unparser
import os

# PARSE_TEST_FILE_DIR = "./parse_tests/"

PARSE_TEST_FILE_DIR = "./basic_parse_tests/"

HEADER_SIZE = 8

# Get the null bytes out...
def strip(buf: bytes) -> bytes:
	# print(buf)
	# print(type(buf))
	if "\x00" not in buf: # Check for null bytes here...
		return buf # No null bytes so just return the thing...
	return buf[HEADER_SIZE:].rstrip("\x00")

def parse_tests():
	# Run the stuff and then check if parsing failure has occurred...
	test_files = os.listdir(PARSE_TEST_FILE_DIR)
	ret = 0
	for fn in test_files:
		with open(PARSE_TEST_FILE_DIR+fn) as fh:
			data = strip(fh.read())
		assert "\x00" not in data
		# Run the parse test...
		try:
			tu = hlsl_parser.parse_to_tree(data)
			out = hlsl_unparser.unparse_tu(tu)
			# Try to parse again to see if the contents have substantially changed...
			tu2 = hlsl_parser.parse_to_tree(out)
			# out2 = hlsl_unparser.unparse_tu(tu2)
			if len(str(tu)) != len(str(tu2)): # Round trip the translation units too. We are kinda "cheating" here because we are only checking the string representation length and not actually the objects themselves...
				print("Roundtripping parser failed. Got different translation units...")
				print("Originally got this here: "+str(tu))
				print("The new one was this here: "+str(tu2))
				assert False
			print(fn + " passed parse test.")
		except Exception as e:
			print("Got this exception here: "+str(e)+" for parse test file "+str(fn))
			print("Dumping tokens...")
			hlsl_parser.dump_tokens(data)
			ret = 1
			continue
	return ret

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
