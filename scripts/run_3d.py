#!/usr/bin/env python3

import sys
import os
import json
import argparse

from utils.class_process import Process
from utils.class_memory_3d import Memory3D

from utils.generate_lib import generate_lib
from utils.generate_lef import generate_lef
from utils.generate_verilog import generate_verilog
from utils.generate_verilog import generate_verilog_bb

################################################################################
# RUN 3D GENERATOR
#
# Entry point for generating 3D-stacked SRAM hard macros (.lef, .lib, .v)
# using CACTI-M3D.  The config file follows the same JSON format as the 2D
# generator (run.py) with two additional top-level keys:
#
#   "num_dies"  : int  – number of stacked die tiers (>= 2)
#   "partition" : str  – "bit"  for BLP (bit-line, splits width across dies)
#                        "word" for WLP (word-line, splits depth across dies)
#
# CACTI-M3D models the full memory array with the specified 3D partitioning
# internally and reports per-tier footprint dimensions that are used directly
# for the LEF/LIB files.
################################################################################


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="""
    BSG Black-box 3D SRAM Generator --
    Generates black-boxed 3D-stacked SRAM hard macros (.lef, .lib, .v) using
    CACTI-M3D.  The JSON config must include "num_dies" and "partition" keys in
    addition to the standard bsg_fakeram fields.
    """
    )

    parser.add_argument("config", help="JSON configuration file")

    parser.add_argument(
        "--output_dir",
        action="store",
        help="Output directory",
        required=False,
        default=None,
    )

    parser.add_argument(
        "--cacti_m3d_dir",
        action="store",
        help="CACTI-M3D installation directory (default: $CACTI_M3D_BUILD_DIR)",
        required=False,
        default=None,
    )

    return parser.parse_args()


def main(args: argparse.Namespace):

    # Resolve CACTI-M3D directory
    cacti_m3d_dir = args.cacti_m3d_dir or os.environ.get("CACTI_M3D_BUILD_DIR")
    if not cacti_m3d_dir:
        print(
            "ERROR: CACTI-M3D directory not specified.\n"
            "  Set --cacti_m3d_dir or export CACTI_M3D_BUILD_DIR=/path/to/tools/CACTI-M3D",
            file=sys.stderr,
        )
        sys.exit(1)

    cacti_m3d_exe = os.path.join(cacti_m3d_dir, "cacti")
    if not os.path.isfile(cacti_m3d_exe):
        print(
            f"ERROR: CACTI-M3D executable not found: {cacti_m3d_exe}\n"
            "  Run  make tools-m3d  to build CACTI-M3D first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load the JSON configuration file (same format as run.py, strips # comments)
    with open(args.config, 'r') as fid:
        raw = [line.strip() for line in fid if not line.strip().startswith('#')]
    json_data = json.loads('\n'.join(raw))

    # Read 3D-specific top-level parameters
    if 'num_dies' not in json_data:
        print("ERROR: config must contain a top-level 'num_dies' key.", file=sys.stderr)
        sys.exit(1)
    if 'partition' not in json_data:
        print("ERROR: config must contain a top-level 'partition' key ('bit' or 'word').",
              file=sys.stderr)
        sys.exit(1)

    num_dies  = int(json_data['num_dies'])
    partition = str(json_data['partition'])

    if partition not in ('bit', 'word'):
        print(f"ERROR: 'partition' must be 'bit' or 'word', got '{partition}'.",
              file=sys.stderr)
        sys.exit(1)
    if num_dies < 2:
        print(f"ERROR: 'num_dies' must be >= 2, got {num_dies}.", file=sys.stderr)
        sys.exit(1)

    # Create a process object shared by all SRAMs
    process = Process(json_data)

    # Go through each SRAM and generate the lib, lef, and v files
    for sram_data in json_data['srams']:
        memory = Memory3D(
            process,
            sram_data,
            args.output_dir,
            cacti_m3d_dir,
            num_dies,
            partition,
        )
        generate_lib(memory)
        generate_lef(memory)
        generate_verilog(memory, tmChkExpand=process.vlogTimingCheckSignalExpansion)
        generate_verilog_bb(memory)


### Entry point
if __name__ == '__main__':
    args = get_args()
    main(args)
