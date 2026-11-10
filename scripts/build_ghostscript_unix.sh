#!/usr/bin/env bash
# Build the standalone CLI from the checksum-verified Ghostscript source release.
# Usage: bash scripts/build_ghostscript_unix.sh SOURCE_DIR OUTPUT_DIR
# OUTPUT_DIR defaults to vendor/ghostscript. Licensing/manifest staging is done
# by prepare_ghostscript.py. Run natively on Linux or macOS, not through WSL.
set -euo pipefail

platform=$(uname -s)
case "$platform" in
    Linux|Darwin) ;;
    *) echo "Build Ghostscript on a native Linux or macOS runner." >&2; exit 1 ;;
esac
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: $0 SOURCE_DIR [OUTPUT_DIR]" >&2
    exit 2
fi
source_dir=$(cd "$1" && pwd -P)
output_dir=${2:-vendor/ghostscript}
mkdir -p "$output_dir/bin"
output_dir=$(cd "$output_dir" && pwd -P)
jobs=${JOBS:-$(getconf _NPROCESSORS_ONLN)}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo "JOBS must be positive." >&2; exit 2; }

# An incomplete source checkout can silently select system libraries instead.
# The official source archive supplies these dependencies for static inclusion.
for component in freetype jpeg libpng zlib brotli lcms2mt jbig2dec openjpeg tiff \
                 pdf Resource/Init Resource/Font Resource/CMap iccprofiles; do
    [[ -d "$source_dir/$component" ]] || {
        echo "Incomplete Ghostscript source: missing $component" >&2
        exit 1
    }
done

cd "$source_dir"
# These options are from the shipped 10.08.0 configure --help. There is no
# generic --enable-static option: the normal 'gs' target embeds the bundled
# codec libraries. Avoid the shared-library 'so' target.
# Keep PostScript/PDF, embedded fonts, CMaps, ICC profiles and all input codecs;
# omit only unused output drivers, GUI/printing integration and OCR.
CFLAGS="${CFLAGS:--Os}" ./configure \
    --prefix="$output_dir" \
    --with-drivers=pdfwrite,pngalpha,ps2write,eps2write,nullpage \
    --without-x \
    --disable-contrib \
    --disable-cups \
    --without-pdftoraster \
    --without-ijs \
    --disable-gtk \
    --disable-dbus \
    --disable-fontconfig \
    --without-tesseract \
    --without-libpaper \
    --without-libidn \
    --with-libiconv=native \
    --with-system-libtiff=no \
    --without-urf \
    --without-so \
    --with-fontpath='%rom%Resource/Font'

# Only codec/font libraries used by these devices must be embedded. Ghostscript
# leaves SHARE_LCUPS/SHARE_LCUPSI=1 even with CUPS disabled; those flags describe
# an unused build rule, not a linked dependency. Check the selected drivers
# separately and retain the final ldd/otool dependency check below.
shared_codecs='^SHARE_(FT|JPEG|LIBPNG|LIBTIFF|ZLIB|BROTLI|JBIG2|JPX|LCMS)[[:space:]]*=[[:space:]]*1([[:space:]]|$)'
if grep -Eq "$shared_codecs" Makefile; then
    echo "A Ghostscript codec unexpectedly selected a shared system library:" >&2
    grep -E "$shared_codecs" Makefile >&2
    exit 1
fi
if grep -E '^DEVICE_DEVS[0-9]*[[:space:]]*=' Makefile | grep -Eq 'cups\.dev|ijs\.dev'; then
    echo "An unused printing driver was unexpectedly enabled." >&2
    exit 1
fi
make -j "$jobs" COMPILE_INITS=1 \
    GS_LIB_DEFAULT='%rom%Resource/Init:%rom%lib:%rom%Resource/Font' gs

check_dir=$(mktemp -d "${TMPDIR:-/tmp}/eps-gs-check.XXXXXX")
trap 'rm -rf -- "$check_dir"' EXIT
cp bin/gs "$check_dir/gs"
chmod 755 "$check_dir/gs"
if [[ "$platform" == Darwin ]]; then
    strip -x "$check_dir/gs"
    codesign --force --sign - "$check_dir/gs"
    linked_libraries=$(otool -L "$check_dir/gs")
    while IFS= read -r library; do
        case "$library" in
            /usr/lib/*|/System/Library/*) ;;
            *) echo "Non-system Ghostscript dependency: $library" >&2; exit 1 ;;
        esac
    done < <(printf '%s\n' "$linked_libraries" | awk 'NR > 1 {print $1}')
else
    strip --strip-unneeded "$check_dir/gs"
    linked_libraries=$(ldd "$check_dir/gs")
    while IFS= read -r library; do
        case "$library" in
            linux-vdso.so.*|ld-linux*.so.*|libc.so.*|libm.so.*|libpthread.so.*|\
            libdl.so.*|librt.so.*|libgcc_s.so.*|libstdc++.so.*) ;;
            *) echo "Non-system Ghostscript dependency: $library" >&2; exit 1 ;;
        esac
    done < <(printf '%s\n' "$linked_libraries" | awk '{n=$1; sub(/^.*\//,"",n); print n}')
fi

# Run the copied executable outside its build tree, ignoring any installed GS
# environment. Explicit ROM paths verify the resources came from this binary.
cd "$check_dir"
run_gs() {
    env -u GS_LIB -u GS_FONTPATH -u GS_OPTIONS -u GS_DEVICE \
        "$check_dir/gs" "$@"
}
help_output=$(run_gs -h)
for device in pdfwrite pngalpha ps2write eps2write nullpage; do
    if ! printf ' %s ' "$help_output" | tr '\n' ' ' | grep -Fq " $device "; then
        echo "Missing Ghostscript device: $device" >&2
        exit 1
    fi
done
run_gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=nullpage -c '
    [(%rom%Resource/Init/gs_init.ps)
     (%rom%Resource/Font/NimbusSans-Regular)
     (%rom%Resource/CMap/Identity-H)
     (%rom%iccprofiles/default_rgb.icc)]
    { (r) file closefile } forall
    /Helvetica findfont pop /Times-Roman findfont pop /Symbol findfont pop'

cat > sample.ps <<'POSTSCRIPT'
%!PS-Adobe-3.0
%%Pages: 2
<< /PageSize [200 150] >> setpagedevice
/Helvetica findfont 18 scalefont setfont
20 80 moveto (EPS Live Viewer) show
showpage
/Symbol findfont 20 scalefont setfont
20 80 moveto (abg) show
showpage
%%EOF
POSTSCRIPT
run_gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pdfwrite -sOutputFile=sample.pdf sample.ps
run_gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=pngalpha -r72 -sOutputFile=page-%d.png sample.pdf
run_gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=ps2write -sOutputFile=roundtrip.ps sample.pdf
run_gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=eps2write -dFirstPage=1 -dLastPage=1 \
    -sOutputFile=roundtrip.eps sample.pdf
run_gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=nullpage roundtrip.ps roundtrip.eps
for result in sample.pdf page-1.png page-2.png roundtrip.ps roundtrip.eps; do
    [[ -s "$result" ]] || { echo "Ghostscript smoke check failed: $result" >&2; exit 1; }
done

cp "$check_dir/gs" "$output_dir/bin/gs"
chmod 755 "$output_dir/bin/gs"
printf 'Built standalone Ghostscript %s (%s bytes): %s\n' \
    "$(run_gs --version)" "$(wc -c < "$output_dir/bin/gs" | tr -d ' ')" "$output_dir/bin/gs"
