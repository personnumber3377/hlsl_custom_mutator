// #include "dxclib/dxc.h"

#include "dxc.h"

#include "dxc/Support/Global.h"
#include "dxc/Support/Unicode.h"
#include "dxc/Support/HLSLOptions.h"
// #include "dxc/Support/dxcapi.extval.h"
// #include "dxc/Support/dxcapi.use.h"
#include "dxc/Support/FileIOHelper.h"
#include "dxc/dxcerrors.h"

#include "llvm/Option/OptTable.h"
#include "llvm/Support/raw_ostream.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <array>
#include <fstream>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

using namespace dxc;
using namespace llvm::opt;
using namespace hlsl::options;

namespace {

struct FuzzCursor {
  const uint8_t *data;
  size_t size;
  size_t off = 0;

  bool empty() const { return off >= size; }

  uint8_t get8(uint8_t def = 0) {
    if (off >= size) return def;
    return data[off++];
  }

  uint32_t get32(uint32_t def = 0) {
    if (off + 4 > size) return def;
    uint32_t v = 0;
    memcpy(&v, data + off, 4);
    off += 4;
    return v;
  }

  std::string takeString(size_t max_len) {
    if (off >= size) return {};
    size_t remain = size - off;
    size_t n = std::min<size_t>(get8(0) % (max_len + 1), remain);
    std::string s(reinterpret_cast<const char *>(data + off), n);
    off += n;
    for (char &c : s) {
      if (c == '\0' || c == '\n' || c == '\r')
        c = '_';
    }
    return s;
  }

  std::string restAsString() const {
    if (off >= size) return {};
    return std::string(reinterpret_cast<const char *>(data + off), size - off);
  }
};

static std::string HexByte(uint8_t b) {
  char buf[3];
  snprintf(buf, sizeof(buf), "%02x", b);
  return std::string(buf);
}

static std::string MakeTempPath(const char *prefix, const uint8_t *data, size_t size, const char *ext) {
  std::string path = "/tmp/";
  path += prefix;
  path += "_";
  for (size_t i = 0; i < std::min<size_t>(size, 8); ++i)
    path += HexByte(data[i]);
  path += ext;
  return path;
}

static bool WriteFileAll(const std::string &path, const void *buf, size_t len) {
  std::ofstream os(path, std::ios::binary);
  if (!os) return false;
  os.write(reinterpret_cast<const char *>(buf), len);
  return os.good();
}

static std::string MakeFallbackHlsl(FuzzCursor &cur) {
  // Keeps the parser/compiler busy even when the input is junk.
  static const char *profiles[] = {
      "cs", "ps", "vs"
  };
  const char *stage = profiles[cur.get8() % 3];
  int use_matrix = cur.get8() & 1;
  int use_struct = cur.get8() & 1;
  int use_array  = cur.get8() & 1;
  int use_loop   = cur.get8() & 1;

  std::ostringstream oss;
  if (strcmp(stage, "cs") == 0) {
    oss << "[numthreads(1,1,1)]\n";
    oss << "void main(uint3 tid : SV_DispatchThreadID) {\n";
  } else if (strcmp(stage, "ps") == 0) {
    oss << "float4 main(float4 pos : SV_Position) : SV_Target {\n";
  } else {
    oss << "float4 main(float4 pos : POSITION) : SV_Position {\n";
  }

  if (use_struct) {
    oss << "  struct S { float4 a; int2 b; };\n";
    oss << "  S s; s.a = float4(1,2,3,4); s.b = int2(5,6);\n";
  }
  if (use_matrix) {
    oss << "  float2x2 m = float2x2(1,2,3,4);\n";
    oss << "  float2 v = mul(float2(1,2), m);\n";
  }
  if (use_array) {
    oss << "  float arr[4] = {1,2,3,4};\n";
    oss << "  float x = arr[" << (cur.get8() % 8) << " & 3];\n";
  }
  if (use_loop) {
    oss << "  float acc = 0;\n";
    oss << "  [unroll]\n";
    oss << "  for (int i = 0; i < " << ((cur.get8() % 8) + 1) << "; ++i) acc += i;\n";
  }

  if (strcmp(stage, "cs") == 0) {
    oss << "}\n";
  } else {
    oss << "  return float4(1,1,1,1);\n";
    oss << "}\n";
  }
  return oss.str();
}

static std::string BuildSourceFromInput(FuzzCursor &cur) {
  if (cur.empty())
    return "float4 main(float4 p:POSITION):SV_Position{return p;}";

  uint8_t mode = cur.get8() % 3;
  std::string rest = cur.restAsString();

  // 0: raw input as source
  // 1: wrapped into a compute shader body comment-ish payload
  // 2: generated fallback with some structure
  if (mode == 0) {
    if (rest.empty()) return MakeFallbackHlsl(cur);
    return rest;
  }
  if (mode == 1) {
    std::ostringstream oss;
    oss << "[numthreads(1,1,1)]\n";
    oss << "void main(uint3 tid : SV_DispatchThreadID) {\n";
    oss << "  ";
    for (char c : rest) {
      if (c == '\0' || c == '\r')
        oss << ' ';
      else
        oss << c;
    }
    oss << "\n}\n";
    return oss.str();
  }
  return MakeFallbackHlsl(cur);
}

static std::wstring Widen(const std::string &s) {
  return std::wstring(s.begin(), s.end());
}

static std::vector<std::wstring> BuildArgs(FuzzCursor &cur, const std::string &input_path) {
  std::vector<std::wstring> args;
  args.emplace_back(L"dxc-fuzz");
  args.emplace_back(Widen(input_path));

  // Mode flags from first bytes.
  const uint8_t bits0 = cur.get8();
  const uint8_t bits1 = cur.get8();
  const uint8_t bits2 = cur.get8();

  // Pick shader profile
  static const wchar_t *profiles[] = {
      L"cs_6_0", L"cs_6_2", L"cs_6_6",
      L"ps_6_0", L"vs_6_0", L"lib_6_3"
  };
  args.emplace_back(L"-T");
  args.emplace_back(profiles[bits0 % (sizeof(profiles)/sizeof(profiles[0]))]);

  // Entry point
  args.emplace_back(L"-E");
  args.emplace_back((bits0 & 0x80) ? L"not_main" : L"main");

  // HLSL version
  static const wchar_t *hvs[] = {L"2016", L"2017", L"2018", L"2021"};
  args.emplace_back(L"-HV");
  args.emplace_back(hvs[bits1 % 4]);

  // Optimization
  switch ((bits1 >> 2) & 0x3) {
    case 0: args.emplace_back(L"-O0"); break;
    case 1: args.emplace_back(L"-O1"); break;
    case 2: args.emplace_back(L"-O2"); break;
    case 3: args.emplace_back(L"-O3"); break;
  }

  // Some interesting toggles
  if (bits0 & 0x01) args.emplace_back(L"-Zi");
  if (bits0 & 0x02) args.emplace_back(L"-Zpr");
  if (bits0 & 0x04) args.emplace_back(L"-Zpc");
  if (bits0 & 0x08) args.emplace_back(L"-Ges");
  if (bits0 & 0x10) args.emplace_back(L"-Gis");
  if (bits0 & 0x20) args.emplace_back(L"-enable-16bit-types");
  if (bits0 & 0x40) args.emplace_back(L"-Vd");

  if (bits1 & 0x01) args.emplace_back(L"-flegacy-resource-reservation");
  if (bits1 & 0x02) args.emplace_back(L"-flegacy-macro-expansion");
  if (bits1 & 0x04) args.emplace_back(L"-all-resources-bound");
  if (bits1 & 0x08) args.emplace_back(L"-Odump");
  if (bits1 & 0x10) args.emplace_back(L"-ast-dump");
  if (bits1 & 0x20) args.emplace_back(L"-ftime-report");

  // Macros
  if (bits2 & 0x01) {
    args.emplace_back(L"-D");
    args.emplace_back(L"FUZZ=1");
  }
  if (bits2 & 0x02) {
    args.emplace_back(L"-D");
    args.emplace_back(L"A=3");
  }
  if (bits2 & 0x04) {
    args.emplace_back(L"-D");
    args.emplace_back(L"B(x)=x");
  }

  return args;
}

static void CleanupFile(const std::string &path) {
  unlink(path.c_str());
}

struct TempFiles {
  std::vector<std::string> paths;
  ~TempFiles() {
    for (const auto &p : paths) unlink(p.c_str());
  }
};

} // namespace

extern "C" int LLVMFuzzerInitialize(int *argc, char ***argv) {
  if (FAILED(DxcInitThreadMalloc()))
    abort();

  DxcSetThreadMallocToDefault();

  if (initHlslOptTable())
    abort();

  return 0;
}

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  if (!data || size < 8)
    return 0;

  // DXC has a lot of deliberate error paths. Keep the input size modest.
  if (size > 64 * 1024)
    return 0;

  const char *pStage = "Operation";

  try {

    FuzzCursor cur{data, size};

    // Split control bytes from payload.
    uint8_t top_mode = cur.get8();
    uint8_t sub_mode = cur.get8();

    std::string source = BuildSourceFromInput(cur);
    if (source.empty())
      source = "float4 main(float4 p:POSITION):SV_Position{return p;}";

    TempFiles temps;

    const std::string input_path = MakeTempPath("dxc_input", data, size, ".hlsl");
    if (!WriteFileAll(input_path, source.data(), source.size()))
      return 0;
    temps.paths.push_back(input_path);
    /*
    std::vector<std::wstring> argStorage = BuildArgs(cur, input_path);
    std::vector<const wchar_t *> argvW;
    argvW.reserve(argStorage.size());
    for (auto &s : argStorage)
      argvW.push_back(s.c_str());
    */

    std::vector<std::unique_ptr<wchar_t[]>> argvKeepAlive;
    std::vector<const wchar_t*> argvW;

    auto args = BuildArgs(cur, input_path);

    for (const auto &s : args) {
        size_t len = s.size() + 1;
        auto buf = std::make_unique<wchar_t[]>(len);
        memcpy(buf.get(), s.c_str(), len * sizeof(wchar_t));

        argvW.push_back(buf.get());
        argvKeepAlive.push_back(std::move(buf));
    }

    const OptTable *optionTable = getHlslOptTable();
    DxcOpts dxcOpts;

    MainArgs mainArgs((int)argvW.size(), argvW.data());

    {
      std::string errorString;
      llvm::raw_string_ostream errorStream(errorString);
      /*
      int optResult = ReadDxcOpts(optionTable, DxcFlags,
                                  MainArgs((int)argvW.size(), argvW.data()),
                                  dxcOpts, errorStream);
      */


      int optResult = ReadDxcOpts(optionTable, DxcFlags,
          mainArgs,
          dxcOpts, errorStream);

      errorStream.flush();
      if (optResult != 0) {
        return 0;
      }
    }

    if (dxcOpts.EntryPoint.empty() && !dxcOpts.RecompileFromBinary) {
      dxcOpts.EntryPoint = "main";
    }

    // Make fuzzing side-effect free-ish.
    dxcOpts.ShowHelp = false;
    dxcOpts.ShowVersion = false;
    dxcOpts.Verbose = false;
    dxcOpts.OutputWarnings = false;
    dxcOpts.OutputWarningsFile = "";

    // Avoid writing random output files during normal fuzzing.
    dxcOpts.OutputObject = "";
    dxcOpts.OutputHeader = "";
    dxcOpts.AssemblyCode = "";
    dxcOpts.DebugFile = "";
    dxcOpts.ExtractPrivateFile = "";
    dxcOpts.PrivateSource = "";
    dxcOpts.RootSignatureSource = "";
    dxcOpts.VerifyRootSignatureSource = "";
    dxcOpts.TimeTrace = "";

    // Drive branches manually from top bits.
    // 0: compile
    // 1: preprocess
    // 2: dumpbin
    // 3: compile + ast/opt-ish output
    // 4: link (with generated libs if possible)
    // 5: recompile-from-binary
    uint8_t exec_mode = top_mode % 6;

    // Always use compilation (for now)
    exec_mode = 0;

    DxcDllExtValidationLoader dxcSupport;
    {
      HRESULT dllResult;
      if (!dxcOpts.ExternalLib.empty() || !dxcOpts.ExternalFn.empty())
        dllResult = dxcSupport.InitializeForDll(
            dxcOpts.ExternalLib.str().c_str(),
            dxcOpts.ExternalFn.str().c_str());
      else
        dllResult = dxcSupport.initialize();

      if (DXC_FAILED(dllResult))
        return 0;
    }

    DxcContext context(dxcOpts, dxcSupport);

    switch (exec_mode) {
      case 0: {
        pStage = "Compilation";
        (void)context.Compile();
        break;
      }

      case 1: {
        pStage = "Preprocessing";
        dxcOpts.Preprocess = MakeTempPath("dxc_pp", data, size, ".txt");
        temps.paths.push_back(std::string(dxcOpts.Preprocess.begin(), dxcOpts.Preprocess.end()));
        context.Preprocess();
        break;
      }

      case 2: {
        pStage = "Dumping existing binary";
        // Feed raw bytes as if they were a binary/container.
        // Re-point input to a binary file made from the original data.
        {
          std::string bin_path = MakeTempPath("dxc_bin", data, size, ".bin");
          if (!WriteFileAll(bin_path, data, size))
            return 0;
          temps.paths.push_back(bin_path);
          dxcOpts.InputFile = bin_path;
        }
        (void)context.DumpBinary();
        break;
      }

      case 3: {
        pStage = "Compilation";
        // Hit ActOnBlob text output branch.
        if (sub_mode & 1) dxcOpts.AstDump = true;
        if (sub_mode & 2) dxcOpts.OptDump = true;
        (void)context.Compile();
        break;
      }

      case 4: {
        pStage = "Linking";

        // Build 1-2 small libraries first, then link them.
        // This reaches linker code more realistically than feeding raw junk.
        CComPtr<IDxcLibrary> pLibrary;
        CComPtr<IDxcCompiler> pCompiler;
        if (FAILED(dxcSupport.CreateInstance(CLSID_DxcLibrary, &pLibrary)))
          return 0;
        if (FAILED(dxcSupport.CreateInstance(CLSID_DxcCompiler, &pCompiler)))
          return 0;

        std::string libsrc1 =
            "export float4 foo(float4 a){ return a; }\n";
        std::string libsrc2 =
            "float4 foo(float4);\n"
            "float4 main(float4 a:POSITION):SV_Position { return foo(a); }\n";

        std::string lib1_path = MakeTempPath("dxc_lib1", data, size, ".hlsl");
        std::string lib2_path = MakeTempPath("dxc_lib2", data, size, ".hlsl");
        std::string lib1_out  = MakeTempPath("dxc_lib1", data, size, ".dxil");
        std::string lib2_out  = MakeTempPath("dxc_lib2", data, size, ".dxil");

        if (!WriteFileAll(lib1_path, libsrc1.data(), libsrc1.size())) return 0;
        if (!WriteFileAll(lib2_path, libsrc2.data(), libsrc2.size())) return 0;
        temps.paths.push_back(lib1_path);
        temps.paths.push_back(lib2_path);
        temps.paths.push_back(lib1_out);
        temps.paths.push_back(lib2_out);

        auto compile_lib = [&](const std::string &src_path,
                               const std::string &out_path,
                               const wchar_t *entry,
                               const wchar_t *target) -> bool {
          CComPtr<IDxcBlobEncoding> src;
          CComPtr<IDxcOperationResult> res;
          CComPtr<IDxcIncludeHandler> inc;
          ReadFileIntoBlob(dxcSupport, Widen(src_path).c_str(), &src);
          if (!src) return false;
          if (FAILED(pLibrary->CreateIncludeHandler(&inc))) return false;

          std::vector<const wchar_t *> libArgs;
          libArgs.push_back(L"-T");
          libArgs.push_back(target);
          libArgs.push_back(L"-E");
          libArgs.push_back(entry);

          HRESULT hr = pCompiler->Compile(
              src, Widen(src_path).c_str(), entry, target,
              libArgs.data(), (UINT32)libArgs.size(),
              nullptr, 0, inc, &res);
          if (FAILED(hr) || !res) return false;

          HRESULT status = E_FAIL;
          if (FAILED(res->GetStatus(&status)) || FAILED(status)) return false;

          CComPtr<IDxcBlob> prog;
          if (FAILED(res->GetResult(&prog)) || !prog) return false;

          return WriteFileAll(out_path, prog->GetBufferPointer(), prog->GetBufferSize());
        };

        // One library target and one lib/main-ish target.
        (void)compile_lib(lib1_path, lib1_out, L"foo", L"lib_6_3");
        (void)compile_lib(lib2_path, lib2_out, L"main", L"lib_6_3");

        dxcOpts.Link = true;
        dxcOpts.InputFile = lib1_out + ";" + lib2_out;
        dxcOpts.EntryPoint = "main";
        dxcOpts.TargetProfile = "ps_6_0";
        (void)context.Link();
        break;
      }

      case 5: {
        pStage = "Recompile from binary";

        // First compile something with debug info, save blob, then recompile it.
        CComPtr<IDxcLibrary> pLibrary;
        CComPtr<IDxcCompiler> pCompiler;
        if (FAILED(dxcSupport.CreateInstance(CLSID_DxcLibrary, &pLibrary)))
          return 0;
        if (FAILED(dxcSupport.CreateInstance(CLSID_DxcCompiler, &pCompiler)))
          return 0;

        CComPtr<IDxcBlobEncoding> src;
        CComPtr<IDxcOperationResult> res;
        CComPtr<IDxcIncludeHandler> inc;

        ReadFileIntoBlob(dxcSupport, Widen(input_path).c_str(), &src);
        if (!src)
          return 0;
        if (FAILED(pLibrary->CreateIncludeHandler(&inc)))
          return 0;

        const wchar_t *args[] = {L"-Zi", L"-Qembed_debug"};
        HRESULT hr = pCompiler->Compile(
            src, Widen(input_path).c_str(), L"main", L"cs_6_0",
            args, 2, nullptr, 0, inc, &res);

        if (SUCCEEDED(hr) && res) {
          HRESULT status = E_FAIL;
          if (SUCCEEDED(res->GetStatus(&status)) && SUCCEEDED(status)) {
            CComPtr<IDxcBlob> prog;
            if (SUCCEEDED(res->GetResult(&prog)) && prog) {
              std::string blob_path = MakeTempPath("dxc_recomp", data, size, ".dxil");
              if (WriteFileAll(blob_path, prog->GetBufferPointer(), prog->GetBufferSize())) {
                temps.paths.push_back(blob_path);
                dxcOpts.InputFile = blob_path;
                dxcOpts.RecompileFromBinary = true;
                dxcOpts.TargetProfile = "cs_6_0";
                dxcOpts.EntryPoint = "main";
                (void)context.Compile();
              }
            }
          }
        }
        break;
      }

      default:
        break;
    }
  } catch (const ::hlsl::Exception &) {
    return 0;
  } catch (const std::bad_alloc &) {
    return 0;
  } catch (...) {
    return 0;
  }

  return 0;
}