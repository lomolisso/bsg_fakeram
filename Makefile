export TOP_DIR :=$(shell git rev-parse --show-toplevel)

export CACTI_BUILD_DIR     := $(TOP_DIR)/tools/cacti
export CACTI_M3D_BUILD_DIR := $(TOP_DIR)/tools/CACTI-M3D

CONFIG ?= $(TOP_DIR)/example_cfgs/freepdk45.cfg

OUT_DIR := $(TOP_DIR)/results

.PHONY: run

# Default run: uses CONFIG (defaults to freepdk45.cfg).
#   make run
#   make run CONFIG=example_cfgs/my.cfg
run:
	./scripts/run.py $(CONFIG) --output_dir $(OUT_DIR)

# Named-config targets: make run.<cfg_stem>
#   Looks up  example_cfgs/<cfg_stem>.cfg  and writes to  results/<cfg_stem>/
#   Example:  make run.1c8n4w4t
#             make run.freepdk45
run.%:
	./scripts/run.py $(TOP_DIR)/example_cfgs/$*.cfg --output_dir $(OUT_DIR)/$*

# 3D named-config targets: make run_3d.<cfg_stem>
#   Looks up  example_cfgs/<cfg_stem>.cfg  (must contain num_dies + partition)
#   Example:  make run_3d.3d_vortex_1c8n4w4t_freepdk45
run_3d.%:
	./scripts/run_3d.py $(TOP_DIR)/example_cfgs/$*.cfg --output_dir $(OUT_DIR)/$*

view.%:
	klayout ./$(OUT_DIR)/$*/$*.lef &

clean:
	rm -rf ./$(OUT_DIR)

#=======================================
# TOOLS
#=======================================

tools: $(CACTI_BUILD_DIR)

$(CACTI_BUILD_DIR):
	mkdir -p $(@D)
	git clone https://github.com/HewlettPackard/Cacti.git $@
	cd $@; git checkout 1ffd8dfb10303d306ecd8d215320aea07651e878
	cd $@; git apply $(TOP_DIR)/patches/cacti.patch
	sh $(TOP_DIR)/patches/nmlimitremoval_patch.sh
	cd $@; make -j4

# Build CACTI-M3D (already cloned at tools/CACTI-M3D).
# Applies patches/cacti_m3d.patch if not yet applied, then builds.
tools-m3d: $(CACTI_M3D_BUILD_DIR)/cacti

$(CACTI_M3D_BUILD_DIR)/cacti:
	cd $(CACTI_M3D_BUILD_DIR); git apply --check $(TOP_DIR)/patches/cacti_m3d.patch 2>/dev/null && \
	  git apply $(TOP_DIR)/patches/cacti_m3d.patch || true
	cd $(CACTI_M3D_BUILD_DIR); make -j4

clean_tools:
	rm -rf $(CACTI_BUILD_DIR)

clean_tools_m3d:
	cd $(CACTI_M3D_BUILD_DIR); make clean; git checkout io.h io.cc

