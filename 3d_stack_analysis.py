#!/usr/bin/env python3
"""3D-Stacked SRAM Macro Characterization using CACTI

Reads a bsg_fakeram JSON configuration file and runs CACTI on each macro
partitioned across N die tiers. Two partitioning strategies are supported:

  word  – Split memory depth across dies (each die holds depth/N rows).
          Only one die is active per access: access latency and per-access
          energy equal a single die's values; standby leakage multiplies by N.

  bit   – Split memory width across dies (each die holds width/N bits).
          All N dies are active in parallel per access: access latency stays
          the same as a single die, but per-access energy multiplies by N;
          standby leakage multiplies by N.

In both cases the 3D stack footprint equals the area of one die tier (since
the dies are stacked vertically).  Total silicon area = N × single-die area.

Usage
-----
  python3 3d_stack_analysis.py <config.cfg> [options]

  positional arguments:
    config              bsg_fakeram JSON configuration file

  optional arguments:
    --cacti_dir DIR     CACTI build directory (default: $CACTI_BUILD_DIR)
    --partition {word,bit}
                        Partitioning strategy (default: word)
    --num_dies N        Number of die tiers (default: 4)
    --output FILE       Output report file (default: macros.rpt)
    --work_dir DIR      Scratch directory for CACTI temp files
                        (default: system temp, cleaned up on exit)
"""

import sys
import os
import math
import json
import shutil
import tempfile
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# ── locate the cacti_config template from the bsg_fakeram scripts package ────
_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from utils.cacti_config import cacti_config as _CACTI_TEMPLATE  # noqa: E402

# ── column indices in the patched CACTI CSV output ───────────────────────────
# (matches the parsing done in scripts/utils/class_memory.py)
_COL_TECH_NM    = 0
_COL_CAP_BYTES  = 1
_COL_ASSOC      = 2
_COL_OUT_WIDTH  = 3
_COL_ACCESS_NS  = 4
_COL_CYCLE_NS   = 5
# col 6 = dynamic search energy (unused)
_COL_READ_NJ    = 7
_COL_WRITE_NJ   = 8
_COL_LEAK_MW    = 9
_COL_AREA_MM2   = 10
_COL_FO4_PS     = 11
_COL_WIDTH_UM   = 12
_COL_HEIGHT_UM  = 13

# ── minimum number of bits per die partition ─────────────────────────────────
_MIN_BITS_PER_DIE = 8


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DieTierResult:
    """Raw CACTI metrics for a single die tier."""
    tech_node_nm:  int
    access_ns:     float
    cycle_ns:      float
    read_nj:       float
    write_nj:      float
    leak_mw:       float
    area_mm2:      float
    fo4_ps:        float
    width_um_raw:  float   # before snap-grid alignment
    height_um_raw: float
    width_um:      float   # after snap-grid alignment
    height_um:     float
    area_snapped:  float   # width_um × height_um (mm²)


@dataclass
class MacroResult:
    """Combined 3D-stack metrics derived from per-die CACTI results."""
    name:           str
    orig_depth:     int
    orig_width_b:   int
    partition:      str    # 'word' or 'bit'
    num_dies:       int
    sub_depth:      int
    sub_width_b:    int
    die:            DieTierResult
    # stack-level metrics
    access_ns:      float
    cycle_ns:       float
    read_nj:        float
    write_nj:       float
    leak_mw:        float
    footprint_mm2:  float  # area of one stacked die (footprint)
    total_mm2:      float  # total silicon = footprint × num_dies


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_config(path: str) -> dict:
    """Load a bsg_fakeram JSON config file, stripping # comment lines."""
    with open(path) as fh:
        raw = [line for line in fh if not line.strip().startswith("#")]
    return json.loads("\n".join(raw))


def _snap(value_um: float, snap_nm: int) -> float:
    """Round *value_um* up to the nearest *snap_nm* grid."""
    if snap_nm <= 1:
        return value_um
    return math.ceil(value_um * 1000.0 / snap_nm) * snap_nm / 1000.0


def _run_cacti(
    cacti_dir:    str,
    work_dir:     str,
    tag:          str,
    total_bytes:  int,
    width_bytes:  int,
    rw_ports:     int,
    r_ports:      int,
    w_ports:      int,
    tech_um:      float,
    cache_type:   str,
) -> list:
    """Write a CACTI config, invoke CACTI, and return the parsed CSV row.

    CACTI writes its CSV output to ``<cfg_path>.out`` automatically.
    The returned list has at least 14 elements (indices 0–13) matching the
    column layout expected by ``scripts/utils/class_memory.py``.
    """
    cfg_path = os.path.join(work_dir, f"{tag}.cacti.cfg")
    out_path = cfg_path + ".out"

    with open(cfg_path, "w") as fh:
        fh.write(
            _CACTI_TEMPLATE.format(
                total_bytes,        # {0}  -size (bytes)
                width_bytes,        # {1}  -block size (bytes)
                rw_ports,           # {2}  -read-write port
                r_ports,            # {3}  -exclusive read port
                w_ports,            # {4}  -exclusive write port
                tech_um,            # {5}  -technology (u)
                width_bytes * 8,    # {6}  -output/input bus width
                1,                  # {7}  num_banks placeholder (unused in template)
                cache_type,         # {8}  -cache type
            )
        )

    prev_dir = os.getcwd()
    os.chdir(cacti_dir)
    cmd = f"./cacti -infile {cfg_path}"
    ret = os.system(cmd)
    os.chdir(prev_dir)

    if ret != 0:
        raise RuntimeError(
            f"CACTI exited with code {ret} for tag '{tag}'.\n"
            f"  cfg : {cfg_path}\n"
            f"  out : {out_path}"
        )

    with open(out_path) as fh:
        lines = fh.readlines()

    # The last non-blank line containing commas is the result CSV row.
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and "," in stripped:
            return stripped.split(",")

    raise RuntimeError(
        f"Could not find a CSV result row in CACTI output for tag '{tag}'.\n"
        f"  out : {out_path}"
    )


def _cacti_to_die(
    csv:       list,
    snap_w_nm: int,
    snap_h_nm: int,
) -> DieTierResult:
    """Convert a raw CACTI CSV row into a :class:`DieTierResult`."""
    w_raw = float(csv[_COL_WIDTH_UM])
    h_raw = float(csv[_COL_HEIGHT_UM])
    w_snapped = _snap(w_raw, snap_w_nm)
    h_snapped = _snap(h_raw, snap_h_nm)
    return DieTierResult(
        tech_node_nm  = int(csv[_COL_TECH_NM]),
        access_ns     = float(csv[_COL_ACCESS_NS]),
        cycle_ns      = float(csv[_COL_CYCLE_NS]),
        read_nj       = float(csv[_COL_READ_NJ]),
        write_nj      = float(csv[_COL_WRITE_NJ]),
        leak_mw       = float(csv[_COL_LEAK_MW]),
        area_mm2      = float(csv[_COL_AREA_MM2]),
        fo4_ps        = float(csv[_COL_FO4_PS]),
        width_um_raw  = w_raw,
        height_um_raw = h_raw,
        width_um      = w_snapped,
        height_um     = h_snapped,
        area_snapped  = w_snapped * h_snapped,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Core analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_macros(
    cfg_path:    str,
    cacti_dir:   str,
    partition:   str,
    num_dies:    int,
    output_file: str,
    work_dir:    Optional[str] = None,
) -> None:
    """Run the full 3D-stack analysis and write *output_file*.

    Parameters
    ----------
    cfg_path    : path to bsg_fakeram JSON configuration file
    cacti_dir   : path to the CACTI build directory (must contain ``./cacti``)
    partition   : ``'word'`` (split depth) or ``'bit'`` (split width)
    num_dies    : number of die tiers in the 3D stack
    output_file : path to write the report (``macros.rpt``)
    work_dir    : scratch directory for CACTI temporary files; if ``None`` a
                  system temp directory is created and removed on exit
    """
    cfg        = _load_config(cfg_path)
    tech_nm    = int(cfg["tech_nm"])
    tech_um    = tech_nm / 1000.0
    voltage    = float(cfg["voltage"])
    snap_w_nm  = int(cfg.get("snapWidth_nm",  1))
    snap_h_nm  = int(cfg.get("snapHeight_nm", 1))

    _cleanup = False
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="3d_stack_cacti_")
        _cleanup = True
    else:
        os.makedirs(work_dir, exist_ok=True)

    try:
        results = []
        for sram in cfg["srams"]:
            result = _process_sram(
                sram, cacti_dir, work_dir, partition, num_dies,
                tech_um, snap_w_nm, snap_h_nm,
            )
            results.append(result)

        _write_report(
            output_file, cfg_path, tech_nm, voltage,
            partition, num_dies, results,
        )
        print(f"\nReport written to: {output_file}")
    finally:
        if _cleanup:
            shutil.rmtree(work_dir, ignore_errors=True)


def _process_sram(
    sram:      dict,
    cacti_dir: str,
    work_dir:  str,
    partition: str,
    num_dies:  int,
    tech_um:   float,
    snap_w_nm: int,
    snap_h_nm: int,
) -> MacroResult:
    """Run CACTI for one SRAM macro and return a :class:`MacroResult`."""
    name       = str(sram["name"])
    width_b    = int(sram["width"])
    depth      = int(sram["depth"])
    cache_type = str(sram.get("type", "cache"))
    port_type  = str(sram.get("port_type", "1rw"))

    if port_type == "1r1w":
        rw_ports, r_ports, w_ports = 0, 1, 1
    else:
        rw_ports, r_ports, w_ports = 1, 0, 0

    # ── compute per-die dimensions ────────────────────────────────────────────
    if partition == "word":
        sub_depth   = math.ceil(depth / num_dies)
        sub_width_b = width_b
    else:  # 'bit'
        sub_depth   = depth
        sub_width_b = max(math.ceil(width_b / num_dies), _MIN_BITS_PER_DIE)

    sub_width_bytes = math.ceil(sub_width_b / 8)
    sub_total_bytes = sub_width_bytes * sub_depth

    print(
        f"[{name}]  {partition} partition → {num_dies} dies "
        f"each {sub_depth} × {sub_width_b}b "
        f"({sub_total_bytes} bytes)  running CACTI …"
    )

    csv = _run_cacti(
        cacti_dir, work_dir, name,
        sub_total_bytes, sub_width_bytes,
        rw_ports, r_ports, w_ports,
        tech_um, cache_type,
    )
    die = _cacti_to_die(csv, snap_w_nm, snap_h_nm)

    # ── combine metrics for the full stack ────────────────────────────────────
    # Latency is always determined by a single die (parallel or one active).
    stack_access_ns = die.access_ns
    stack_cycle_ns  = die.cycle_ns

    if partition == "word":
        # Only one die is active per access → energy = single die
        stack_read_nj  = die.read_nj
        stack_write_nj = die.write_nj
    else:
        # All dies are active in parallel → energy scales by N
        stack_read_nj  = die.read_nj  * num_dies
        stack_write_nj = die.write_nj * num_dies

    # Leakage: all N dies are powered regardless of partition type
    stack_leak_mw      = die.leak_mw * num_dies
    # Footprint: dies are stacked → same 2-D footprint as one die
    stack_footprint    = die.area_snapped
    stack_total_silicon = die.area_snapped * num_dies

    return MacroResult(
        name          = name,
        orig_depth    = depth,
        orig_width_b  = width_b,
        partition     = partition,
        num_dies      = num_dies,
        sub_depth     = sub_depth,
        sub_width_b   = sub_width_b,
        die           = die,
        access_ns     = stack_access_ns,
        cycle_ns      = stack_cycle_ns,
        read_nj       = stack_read_nj,
        write_nj      = stack_write_nj,
        leak_mw       = stack_leak_mw,
        footprint_mm2 = stack_footprint,
        total_mm2     = stack_total_silicon,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Report formatting
# ─────────────────────────────────────────────────────────────────────────────

def _write_report(
    output_file: str,
    cfg_path:    str,
    tech_nm:     int,
    voltage:     float,
    partition:   str,
    num_dies:    int,
    results:     list,
) -> None:
    W = 80
    SEP_HEAVY = "=" * W
    SEP_LIGHT = "-" * W

    def line(text=""):
        return text

    lines = [
        SEP_HEAVY,
        "  3D-Stacked SRAM Macro Report",
        SEP_HEAVY,
        f"  Config     : {cfg_path}",
        f"  Technology : {tech_nm} nm   Vdd = {voltage} V",
        f"  Partition  : {partition.upper()} partitioning  "
        f"({'split depth across dies' if partition == 'word' else 'split width across dies'})",
        f"  Die tiers  : {num_dies}",
        SEP_HEAVY,
        "",
    ]

    for r in results:
        d = r.die
        orig_bytes = math.ceil(r.orig_width_b / 8) * r.orig_depth
        sub_bytes  = math.ceil(r.sub_width_b  / 8) * r.sub_depth

        lines += [
            SEP_LIGHT,
            f"  Macro : {r.name}",
            SEP_LIGHT,
            "",
            f"  Original dimensions",
            f"    Words (depth)        : {r.orig_depth}",
            f"    Word width           : {r.orig_width_b} bits",
            f"    Total capacity       : {orig_bytes} bytes  "
            f"({orig_bytes / 1024:.2f} KiB)",
            "",
            f"  Per-die partition  [{r.partition} partitioning, {r.num_dies} tiers]",
            f"    Sub-depth            : {r.sub_depth} rows",
            f"    Sub-width            : {r.sub_width_b} bits  "
            f"({math.ceil(r.sub_width_b / 8)} bytes/row)",
            f"    Sub capacity         : {sub_bytes} bytes",
            "",
            "  CACTI results — single die tier",
            f"    Access time          : {d.access_ns:.4f} ns",
            f"    Cycle time           : {d.cycle_ns:.4f} ns",
            f"    FO4 delay            : {d.fo4_ps:.2f} ps",
            f"    Dynamic read energy  : {d.read_nj:.6f} nJ",
            f"    Dynamic write energy : {d.write_nj:.6f} nJ",
            f"    Standby leakage      : {d.leak_mw:.6f} mW",
            f"    Width  (raw → snapped): {d.width_um_raw:.4f} µm  →  {d.width_um:.4f} µm",
            f"    Height (raw → snapped): {d.height_um_raw:.4f} µm  →  {d.height_um:.4f} µm",
            f"    Footprint (snapped)  : {d.area_snapped * 1e6:.2f} µm²  "
            f"({d.area_snapped:.6f} mm²)",
            "",
        ]

        if r.partition == "word":
            activation = "one die active per access (address decoded to one tier)"
            e_note_r   = f"{r.read_nj:.6f} nJ  (= single die)"
            e_note_w   = f"{r.write_nj:.6f} nJ  (= single die)"
        else:
            activation = "all dies active per access (parallel bit-slice)"
            e_note_r   = f"{r.read_nj:.6f} nJ  (×{r.num_dies} vs single die)"
            e_note_w   = f"{r.write_nj:.6f} nJ  (×{r.num_dies} vs single die)"

        lines += [
            f"  3D stack summary  [{r.num_dies} tiers, {activation}]",
            f"    Access time          : {r.access_ns:.4f} ns",
            f"    Cycle time           : {r.cycle_ns:.4f} ns",
            f"    Dynamic read energy  : {e_note_r}",
            f"    Dynamic write energy : {e_note_w}",
            f"    Standby leakage      : {r.leak_mw:.6f} mW  (×{r.num_dies})",
            f"    Stack footprint      : {r.footprint_mm2:.6f} mm²  (= 1 die tier)",
            f"    Total silicon area   : {r.total_mm2:.6f} mm²  (×{r.num_dies})",
            "",
        ]

    lines += [SEP_HEAVY, "  END OF REPORT", SEP_HEAVY, ""]

    with open(output_file, "w") as fh:
        fh.write("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="3d_stack_analysis.py",
        description="Characterize 3D-stacked SRAM macros using the same "
                    "CACTI instance used by bsg_fakeram.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  # word partitioning across 4 dies (default)\n"
            "  python3 3d_stack_analysis.py example_cfgs/vortex_1c8n4w4t_freepdk45.cfg\n"
            "\n"
            "  # bit partitioning across 8 dies\n"
            "  python3 3d_stack_analysis.py example_cfgs/vortex_1c8n4w4t_freepdk45.cfg \\\n"
            "      --partition bit --num_dies 8\n"
            "\n"
            "  # explicit CACTI directory\n"
            "  python3 3d_stack_analysis.py my.cfg --cacti_dir ./tools/cacti\n"
        ),
    )

    parser.add_argument(
        "config",
        help="bsg_fakeram JSON configuration file (.cfg)",
    )
    parser.add_argument(
        "--cacti_dir",
        default=None,
        metavar="DIR",
        help="CACTI build directory (default: $CACTI_BUILD_DIR)",
    )
    parser.add_argument(
        "--partition",
        choices=["word", "bit"],
        default="word",
        help=(
            "Partitioning strategy:\n"
            "  word – split depth (rows) across die tiers [default]\n"
            "  bit  – split width (bits) across die tiers"
        ),
    )
    parser.add_argument(
        "--num_dies",
        type=int,
        default=4,
        metavar="N",
        help="Number of die tiers in the 3D stack (default: 4)",
    )
    parser.add_argument(
        "--output",
        default="macros.rpt",
        metavar="FILE",
        help="Output report file (default: macros.rpt)",
    )
    parser.add_argument(
        "--work_dir",
        default=None,
        metavar="DIR",
        help=(
            "Scratch directory for CACTI temp files. "
            "Default: system temp (auto-cleaned on exit)."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = _get_args()

    # ── resolve CACTI directory ───────────────────────────────────────────────
    cacti_dir = args.cacti_dir or os.environ.get("CACTI_BUILD_DIR")
    if not cacti_dir:
        print(
            "ERROR: CACTI directory not specified.\n"
            "  Set --cacti_dir or export CACTI_BUILD_DIR=/path/to/tools/cacti",
            file=sys.stderr,
        )
        sys.exit(1)

    cacti_exe = os.path.join(cacti_dir, "cacti")
    if not os.path.isfile(cacti_exe):
        print(
            f"ERROR: CACTI executable not found: {cacti_exe}\n"
            "  Run  make tools  to build CACTI first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isfile(args.config):
        print(f"ERROR: configuration file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    if args.num_dies < 2:
        print("ERROR: --num_dies must be >= 2", file=sys.stderr)
        sys.exit(1)

    analyze_macros(
        cfg_path    = args.config,
        cacti_dir   = cacti_dir,
        partition   = args.partition,
        num_dies    = args.num_dies,
        output_file = args.output,
        work_dir    = args.work_dir,
    )


if __name__ == "__main__":
    main()
