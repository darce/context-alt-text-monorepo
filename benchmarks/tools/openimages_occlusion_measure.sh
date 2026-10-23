#!/bin/bash
# Regenerates every Open Images occlusion figure cited in §19 of
# benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html.
#
# Usage:  benchmarks/tools/openimages_occlusion_measure.sh [ANNOTATION_DIR]
# Or set OPENIMAGES_ANNOTATION_DIR; no machine-specific default.
# Requires: awk, python3 with numpy (bootstrap only).
#
# Column layout (1-indexed) is identical across splits for cols 1-13; train appends
# 8 XClick columns after col 13. Face class is /m/0dzct (Human face).
#   1 ImageID  2 Source  3 LabelName  5 XMin  6 XMax  7 YMin  8 YMax  9 IsOccluded  11 IsGroupOf
#
# IsOccluded is tri-valued: 1 occluded, 0 not occluded, -1 NOT ANNOTATED. Train carries
# -1 rows; val/test carry none. Every rate below states its denominator explicitly.
set -eu
usage() {
  cat <<'HELP'
Usage: openimages_occlusion_measure.sh [ANNOTATION_DIR]
Set ANNOTATION_DIR explicitly or use OPENIMAGES_ANNOTATION_DIR.
Requires the validation, test and train annotation CSVs, awk, and python3 with numpy.
Prints measurements to stdout; does not write result files.
HELP
}
if [ "$#" -eq 1 ] && { [ "$1" = "--help" ] || [ "$1" = "-h" ]; }; then
  usage
  exit 0
fi
if [ "$#" -gt 1 ]; then
  usage >&2
  exit 2
fi
D="${1:-${OPENIMAGES_ANNOTATION_DIR:-}}"
if [ -z "$D" ]; then
  echo "error: annotation directory is required (argument or OPENIMAGES_ANNOTATION_DIR)" >&2
  exit 2
fi
if [ ! -d "$D" ]; then
  echo "error: annotation directory does not exist: $D" >&2
  exit 2
fi
for csv in validation-annotations-bbox.csv test-annotations-bbox.csv oidv6-train-annotations-bbox.csv; do
  if [ ! -f "$D/$csv" ] || [ ! -r "$D/$csv" ]; then
    echo "error: required annotation CSV is missing or unreadable: $D/$csv" >&2
    exit 2
  fi
done
FACE=/m/0dzct
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

splits="validation:validation-annotations-bbox.csv test:test-annotations-bbox.csv train:oidv6-train-annotations-bbox.csv"

echo "=== [1] Flag value counts over ALL face boxes (denominator = all face boxes) ==="
for p in $splits; do
  awk -F, -v S="${p%%:*}" -v FACE="$FACE" 'FNR>1 && $3==FACE {c[$9]++; n++}
    END {printf "%-11s total=%d ", S, n; for (k in c) printf "%s=%d(%.2f%%) ", k, c[k], 100*c[k]/n; print ""}' \
    "$D/${p#*:}"
done

echo
echo "=== [2] Occlusion rate by crowd size (faces per image); denominator EXCLUDES IsOccluded=-1 ==="
for p in $splits; do
  echo "--- ${p%%:*}"
  awk -F, -v FACE="$FACE" '
    NR==FNR { if ($3==FACE) fc[$1]++; next }
    FNR==1 { next }
    $3==FACE && $9!=-1 {
      n=fc[$1]; b = (n==1)?"1":(n==2)?"2":(n==3)?"3":(n<=5)?"4-5":(n<=10)?"6-10":"11+"
      box[b]++; if ($9==1) occ[b]++
      a=($6-$5)*($8-$7); if ($9==1) {so+=a; no++} else {su+=a; nu++}
    }
    END {
      split("1 2 3 4-5 6-10 11+", ord, " ")
      printf "%-6s %8s %8s\n", "faces", "boxes", "occ%"
      for (i=1;i<=6;i++) { b=ord[i]; if (box[b]) printf "%-6s %8d %7.1f%%\n", b, box[b], 100*occ[b]/box[b] }
      printf "mean box area  occluded %.5f (n=%d)  unoccluded %.5f (n=%d)  ratio %.2f\n",
             so/no, no, su/nu, nu, (so/no)/(su/nu)
    }' "$D/${p#*:}" "$D/${p#*:}"
done

echo
echo "=== [3] Train only: Source stratification (denominator excludes -1) ==="
awk -F, -v FACE="$FACE" 'FNR>1 && $3==FACE && $9!=-1 {
    s=$2; n[s]++; if ($9==1) {o[s]++; sa[s]+=($6-$5)*($8-$7); soN[s]++} else {ua[s]+=($6-$5)*($8-$7); uaN[s]++}
    tot++ }
  END { for (s in n) printf "%-10s boxes=%8d (%5.2f%%)  occ=%5.2f%%  ratio=%.2f\n",
          s, n[s], 100*n[s]/tot, 100*o[s]/n[s], (sa[s]/soN[s])/(ua[s]/uaN[s]) }' \
  "$D/oidv6-train-annotations-bbox.csv"

echo
echo "=== [4] Composition control: single-face images only; bootstrap CIs on the area ratio ==="
for p in $splits; do
  s="${p%%:*}"
  awk -F, -v FACE="$FACE" 'NR==FNR { if ($3==FACE) c[$1]++; next }
       FNR==1 { next }
       $3==FACE && c[$1]==1 { printf "%d\t%.8f\n", $9, ($6-$5)*($8-$7) }' \
      "$D/${p#*:}" "$D/${p#*:}" > "$TMP/sf-$s.tsv"
done

python3 - "$TMP" <<'PY'
import sys
import numpy as np
tmp = sys.argv[1]
B, SEED = 4000, 20260728
rng = np.random.default_rng(SEED)

def load(s):
    a = np.loadtxt(f'{tmp}/sf-{s}.tsv', delimiter='\t')
    a = a[a[:, 0] != -1]                      # drop unannotated flag rows
    return a[a[:, 0] == 1][:, 1], a[a[:, 0] == 0][:, 1]

def boot_mean(x):
    n = len(x); out = np.empty(B)
    for i in range(0, B, 250):
        k = min(250, B - i)
        out[i:i + k] = x[rng.integers(0, n, size=(k, n))].mean(axis=1)
    return out

print(f'B={B} percentile bootstrap, seed={SEED}. Single-face images carry one box each,')
print('so box-level resampling is image-level resampling (no cluster correction needed).')
R = {}
for s in ('train', 'validation', 'test'):
    o, u = load(s)
    n = len(o) + len(u); rate = len(o) / n
    se = np.sqrt(rate * (1 - rate) / n)
    br = np.sort(boot_mean(o) / boot_mean(u)); R[s] = br
    print(f'{s:11s} n={n:6d}  occ={rate*100:5.2f}% [{(rate-1.96*se)*100:.2f},{(rate+1.96*se)*100:.2f}]  '
          f'meanA_occ={o.mean():.5f} meanA_unocc={u.mean():.5f}  '
          f'ratio={o.mean()/u.mean():.3f} 95%CI [{br[int(.025*B)]:.3f},{br[int(.975*B)]:.3f}]')
print()
print('Size-discrimination deficit = 1 - ratio. Attenuation = deficit(split) / deficit(train).')
for s in ('validation', 'test'):
    dt, dv = 1 - R['train'], 1 - R[s]
    dif = np.sort(dv - dt); att = np.sort(dv / dt)
    print(f'train vs {s:10s} deficit gap {np.median(dif):+.3f} 95%CI [{dif[int(.025*B)]:+.3f},{dif[int(.975*B)]:+.3f}]  '
          f'attenuation x{np.median(att):.2f} 95%CI [{att[int(.025*B)]:.2f},{att[int(.975*B)]:.2f}]')
PY
