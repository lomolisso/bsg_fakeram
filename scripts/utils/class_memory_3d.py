import os
from utils.class_memory import Memory
from utils.cacti_m3d_config import cacti_m3d_config

################################################################################
# MEMORY3D CLASS
#
# Extends Memory to use CACTI-M3D for 3D-stacked SRAM characterization.
# CACTI-M3D models the full memory array with 3D partitioning internally via:
#   -layers N          : number of stacked die tiers
#   -partitioning 1|0  : 1 = BLP (bit-line, splits width), 0 = WLP (split depth)
#
# The full memory dimensions are passed to CACTI-M3D unchanged; the tool
# handles partitioning internally and reports per-tier footprint dimensions
# (width_um, height_um) which are used directly for the LEF.
################################################################################

_PARTITION_INT = {'bit': 1, 'word': 0}


class Memory3D(Memory):
    """Memory subclass that uses CACTI-M3D for 3D-stacked SRAM modeling.

    Parameters
    ----------
    process     : Process object (shared across all SRAMs)
    sram_data   : dict entry from the 'srams' list in the JSON config
    output_dir  : top-level output directory (a sub-directory named after the
                  SRAM is created inside it)
    cacti_m3d_dir : path to the built CACTI-M3D directory (must contain ./cacti)
    num_dies    : number of 3D die tiers (>= 2)
    partition   : 'bit' for BLP (split width) or 'word' for WLP (split depth)
    """

    def __init__(self, process, sram_data, output_dir, cacti_m3d_dir,
                 num_dies: int, partition: str):
        if partition not in _PARTITION_INT:
            raise ValueError(
                f"partition must be 'bit' or 'word', got '{partition}'"
            )
        if num_dies < 2:
            raise ValueError(f"num_dies must be >= 2, got {num_dies}")

        # Store 3D params before super().__init__ calls _run_cacti so the
        # overridden _run_cacti can access them.
        self._num_dies_3d   = num_dies
        self._partition_3d  = partition
        self._partition_int = _PARTITION_INT[partition]

        super().__init__(process, sram_data, output_dir, cacti_dir=cacti_m3d_dir)

    # ------------------------------------------------------------------
    # Override _run_cacti to write a CACTI-M3D config and invoke the
    # CACTI-M3D binary.  The output file (cacti.cfg.out) has the same
    # CSV column layout as patched regular CACTI thanks to cacti_m3d.patch.
    # ------------------------------------------------------------------
    def _run_cacti(self):
        cfg_path = os.sep.join([self.results_dir, 'cacti.cfg'])
        with open(cfg_path, 'w') as fid:
            fid.write(
                cacti_m3d_config.format(
                    self.total_size,            # {0}  -size (bytes)
                    self.width_in_bytes,        # {1}  -block size (bytes)
                    self.rw_ports,              # {2}  -read-write port
                    self.r_ports,               # {3}  -exclusive read port
                    self.w_ports,               # {4}  -exclusive write port
                    self.process.tech_um,       # {5}  -technology (u)
                    self.width_in_bytes * 8,    # {6}  -output/input bus width
                    self.num_banks,             # {7}  (unused placeholder)
                    self.cache_type,            # {8}  -cache type
                    self._num_dies_3d,          # {9}  -layers
                    self._partition_int,        # {10} -partitioning
                )
            )
        odir = os.getcwd()
        os.chdir(self.cacti_dir)
        cmd = os.sep.join(['.', 'cacti -infile ']) + cfg_path
        os.system(cmd)
        os.chdir(odir)
