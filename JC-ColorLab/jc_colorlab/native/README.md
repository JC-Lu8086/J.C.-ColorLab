# Windows LittleCMS runtime

`liblcms2-2.dll` is LittleCMS 2.19.1, Windows x64/UCRT, supplied by MSYS2.
It exposes the floating-point color-management API that Pillow's Windows extension does not export.
Only the MIT-licensed core library is included; the GPL fast-float plugin and command-line utilities are not included.

- Upstream: https://github.com/mm2/Little-CMS/
- Package: https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-lcms2
- Archive: https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-lcms2-2.19.1-1-any.pkg.tar.zst
- Archive SHA-256: `144518cc80679f7bcc1d31b5dd7ec92e8737a1d8162014e30c8c1c181f47a156`
- License: `LICENSE-LittleCMS.txt`

The DLL is loaded only on Windows. Its PE imports and required exported API symbols were inspected on macOS; execution on Windows remains untested.
