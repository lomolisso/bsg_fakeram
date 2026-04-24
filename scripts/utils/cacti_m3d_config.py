################################################################################
# CACTI-M3D CONFIG
#
# CACTI-M3D input template for 3D-stacked SRAM modeling.
# Extends the base cacti_config with three extra parameters required by
# CACTI-M3D:
#
#   {9}  -layers       : number of stacked die tiers (num_dies)
#   {10} -partitioning : 1 = BLP (bit-line, splits width across dies)
#                        0 = WLP (word-line, splits depth across dies)
#
# Slots {0}–{8} are identical to cacti_config:
#   {0}  -size (bytes)
#   {1}  -block size (bytes)
#   {2}  -read-write port
#   {3}  -exclusive read port
#   {4}  -exclusive write port
#   {5}  -technology (u)
#   {6}  -output/input bus width
#   {7}  (unused placeholder – num_banks kept at 1 in template)
#   {8}  -cache type
################################################################################

from utils.cacti_config import cacti_config as _base

# Strip trailing newline from base template so the 3D params are appended
# cleanly, then re-add a final newline.
cacti_m3d_config = _base.rstrip('\n') + '''
-layers {9}
-degradation 1.0
-partitioning {10}
'''
