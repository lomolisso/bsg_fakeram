# bsg_fakeram — SRAM Configuration Guide

## Table of Contents

1. [Overview](#overview)
2. [Configuration File Format](#configuration-file-format)
3. [Process Parameters](#process-parameters)
4. [SRAM Entry Parameters](#sram-entry-parameters)
5. [Port Types in Detail](#port-types-in-detail)
   - [1rw — Single Read-Write Port](#1rw--single-read-write-port)
   - [1r1w — One Read Port + One Write Port](#1r1w--one-read-port--one-write-port)
6. [Output Register Mode (`out_reg`)](#output-register-mode-out_reg)
7. [Same-Address Collision Policy (`rdw_mode`)](#same-address-collision-policy-rdw_mode)
8. [Generated Files](#generated-files)
9. [Parameter Reference Table](#parameter-reference-table)
10. [Mapping to Vortex `VX_dp_ram`](#mapping-to-vortex-vx_dp_ram)
11. [Known Limitations](#known-limitations)

---

## Overview

bsg_fakeram generates abstract SRAM macro collateral (`.lef`, `.lib`, `.v`,
`.bb.v`) from a JSON configuration file.  Cacti is called under the hood to
estimate area, timing, and power; the generator then synthesises the physical
and logical views from those numbers.

**What bsg_fakeram produces is _fakeram_**, sized and timed from Cacti —
not a compiled hard-IP GDS.  The generated files are suitable for
place-and-route, static timing analysis, and behavioural simulation, but the
numbers are approximations.

---

## Configuration File Format

The configuration file is JSON with `#`-prefixed line comments stripped before
parsing.  Pass it to the generator with:

```bash
./scripts/run.py <config.cfg> [--output_dir DIR] [--cacti_dir DIR]
```

Top-level structure:

```json
{
  "tech_nm":     45,
  "voltage":     1.1,
  "metalPrefix": "metal",
  "pinWidth_nm": 70,
  "pinPitch_nm": 140,
  "snapWidth_nm":  190,
  "snapHeight_nm": 1400,
  "flipPins":    true,
  "srams": [ ... ]
}
```

---

## Process Parameters

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `tech_nm` | integer | yes | Technology node in nm (e.g. `45`, `130`). Passed to Cacti. |
| `voltage` | float | yes | Nominal supply voltage in V. Used in Liberty header and power calculations. |
| `metalPrefix` | string | yes | Prefix prepended to every metal layer number in the LEF (e.g. `"metal"` → `metal1`, `metal4`). |
| `pinWidth_nm` | integer | yes | Signal-pin width in nm. |
| `pinPitch_nm` | integer | yes | Minimum signal-pin pitch in nm. All pins are placed at integer multiples of this pitch. |
| `snapWidth_nm` | integer | no | Round macro width up to a multiple of this value (default: no snapping). |
| `snapHeight_nm` | integer | no | Round macro height up to a multiple of this value (default: no snapping). |
| `pinHeight_nm` | integer | no | Pin rectangle height (depth into the cell) in nm. Defaults to `pinWidth_nm`. |
| `flipPins` | boolean | no | `true`: signal pins on metal3, power straps vertical on metal4. `false` (default): signal pins and power straps both on metal4, power horizontal. |

---

## SRAM Entry Parameters

Each item in the `"srams"` list describes one macro to generate.

| Key | Type | Required | Default | Description |
|-----|------|----------|---------|-------------|
| `name` | string | yes | — | Unique macro name. Used as the output directory name and all generated identifiers. |
| `width` | integer | yes | — | Data word width in bits. |
| `depth` | integer | yes | — | Number of words (address space). Must be a power of two. |
| `banks` | integer | yes | — | Number of internal Cacti banks. Use `1` unless you have a specific reason to split. |
| `type` | string | no | `"cache"` | Cacti memory type string (`"cache"` or `"main memory"`). Rarely needs changing. |
| `port_type` | string | no | `"1rw"` | Port configuration. See [Port Types](#port-types-in-detail). |
| `rdw_mode` | string | no | `"R"` | Same-address collision policy for 1r1w only. See [rdw_mode](#same-address-collision-policy-rdw_mode). |
| `out_reg` | boolean | no | `true` | Read output register mode. See [out_reg](#output-register-mode-out_reg). |

---

## Port Types in Detail

### 1rw — Single Read-Write Port

`"port_type": "1rw"` (default)

A single port that can either read **or** write in any given clock cycle, selected
by `we_in`.

#### Interface

| Signal | Direction | Width | Description |
|--------|-----------|-------|-------------|
| `clk` | input | 1 | Clock |
| `ce_in` | input | 1 | Chip enable (active-high). Port is idle when low. |
| `we_in` | input | 1 | Write enable. When `ce_in=1` and `we_in=1`: write. When `ce_in=1` and `we_in=0`: read. |
| `addr_in` | input | ⌈log₂(depth)⌉ | Shared address for both read and write. |
| `wd_in` | input | width | Write data. |
| `w_mask_in` | input | width | Write byte mask (per-bit). A `1` in position `i` enables writing bit `i`. |
| `rd_out` | output | width | Read data (registered by default; see `out_reg`). |

#### Cacti mapping

```
-read-write port 1  -exclusive read port 0  -exclusive write port 0
```

#### Example

```json
{"name": "sram_32x32_1rw", "width": 32, "depth": 32, "banks": 1}
```

---

### 1r1w — One Read Port + One Write Port

`"port_type": "1r1w"`

Two fully independent ports with separate addresses.  In one clock cycle the
design may assert a read to `r_addr_in` **and** a write to `w_addr_in`
simultaneously — there is no arbitration or port-sharing.

This is the correct port type for dual-port RAMs (GPR files, tag arrays, etc.)
where concurrent read and write are required.

#### Interface

| Signal | Direction | Width | Description |
|--------|-----------|-------|-------------|
| `clk` | input | 1 | Shared clock |
| `r_ce_in` | input | 1 | Read chip enable. Read port is idle when low. |
| `r_addr_in` | input | ⌈log₂(depth)⌉ | Read address. |
| `rd_out` | output | width | Read data (registered by default; see `out_reg`). |
| `w_ce_in` | input | 1 | Write chip enable. Write port is idle when low. |
| `w_addr_in` | input | ⌈log₂(depth)⌉ | Write address (independent of read address). |
| `wd_in` | input | width | Write data. |
| `w_mask_in` | input | width | Write byte mask (per-bit). |

#### Cacti mapping

```
-read-write port 0  -exclusive read port 1  -exclusive write port 1
```

#### Example

```json
{"name": "sram_128x128_1r1w", "width": 128, "depth": 128, "banks": 1,
 "port_type": "1r1w"}
```

---

## Output Register Mode (`out_reg`)

Controls whether the read data output is registered (clocked) or combinational.

### `out_reg: true` (default) — Registered Output

`rd_out` is driven by a flip-flop that captures the addressed word on the
rising clock edge.  This is the standard, synchronous SRAM model and
corresponds to 1-cycle read latency.

**Liberty**: `rd_out` has a `rising_edge` timing arc from `clk`
(clock-to-Q).

**Verilog** (`out_reg=true`, 1r1w example):
```verilog
always @(posedge clk) begin
    if (r_ce_in)
        rd_out <= mem[r_addr_in];   // captured on clock edge
    else
        rd_out <= 'x;
end
```

### `out_reg: false` — Combinational Output

`rd_out` is driven combinationally from the array; it is transparent to the
current state of `mem` without waiting for a clock edge.  This is sometimes
called an asynchronous or latch-based read.

**Liberty**: `rd_out` has a `combinational` timing arc from `r_addr_in`
and `r_ce_in` (for 1r1w) or `addr_in` and `ce_in` (for 1rw).

**Verilog** (`out_reg=false`, 1r1w example):
```verilog
// write still clocked
always @(posedge clk) begin
    if (w_ce_in)
        mem[w_addr_in] <= (wd_in & w_mask_in) | (mem[w_addr_in] & ~w_mask_in);
end

// read is combinational
assign rd_out = r_ce_in ? mem[r_addr_in] : 'x;
```

> **Note:** Physical SRAM macros from a foundry compiler are always
> synchronous.  `out_reg: false` is primarily useful for simulating
> latch-based or register-file-style arrays in RTL.  When targeting a real
> macro (e.g. Vortex `OUT_REG=0`), the SRAM itself still has one clock cycle
> of latency; the `OUT_REG=0` flag at the RTL level typically means the
> wrapper does **not** add an additional pipeline register after the SRAM
> output.

#### Example

```json
{"name": "sram_32x32_1rw_async", "width": 32, "depth": 32, "banks": 1,
 "out_reg": false}
```

---

## Same-Address Collision Policy (`rdw_mode`)

**Applies to `port_type: "1r1w"` only.**

When `r_addr_in == w_addr_in` and both `r_ce_in` and `w_ce_in` are asserted
in the same cycle, the `rdw_mode` parameter determines what value appears on
`rd_out`.

### `rdw_mode: "R"` (default) — Read-First

`rd_out` receives the value that was stored in the array **before** the
write takes effect.  No forwarding logic is required; in a clocked model
this is the natural result of Verilog non-blocking assignment semantics.

```
cycle N:  r_addr == w_addr, write new_val, read → old_val appears on rd_out
cycle N+1: mem[addr] == new_val
```

**Verilog kernel** (registered, read-first):
```verilog
always @(posedge clk) begin
    if (w_ce_in)
        mem[w_addr_in] <= (wd_in & w_mask_in) | (mem[w_addr_in] & ~w_mask_in);
    if (r_ce_in)
        rd_out <= mem[r_addr_in];   // RHS evaluated with pre-clock mem
end
```

### `rdw_mode: "W"` — Write-First

`rd_out` receives the value **being written** this cycle when
`r_addr_in == w_addr_in`.  This requires an explicit forwarding path that
merges `wd_in` / `w_mask_in` with the existing array contents and drives
`rd_out` with the merged result.

```
cycle N:  r_addr == w_addr, write new_val, read → new_val appears on rd_out
cycle N+1: mem[addr] == new_val
```

**Verilog kernel** (registered, write-first):
```verilog
always @(posedge clk) begin
    if (w_ce_in)
        mem[w_addr_in] <= (wd_in & w_mask_in) | (mem[w_addr_in] & ~w_mask_in);
    if (r_ce_in) begin
        if (w_ce_in && (r_addr_in == w_addr_in))
            // Forward: apply mask against current (pre-write) array value
            rd_out <= (wd_in & w_mask_in) | (mem[r_addr_in] & ~w_mask_in);
        else
            rd_out <= mem[r_addr_in];
    end else
        rd_out <= 'x;
end
```

> **Note:** `rdw_mode` affects only the **behavioural Verilog model**.
> The Liberty timing model is identical for both policies (it cannot express
> the forwarding path in NLDM format).  For correct STA, ensure that
> same-address cycles are either avoided or that hold-time margins are
> sufficient regardless of the policy.

#### Example

```json
{"name": "sram_128x128_1r1w_wf", "width": 128, "depth": 128, "banks": 1,
 "port_type": "1r1w", "rdw_mode": "W"}
```

---

## Generated Files

For each SRAM entry, the generator creates a subdirectory
`<output_dir>/<name>/` containing:

| File | Description |
|------|-------------|
| `<name>.lef` | LEF 5.7 abstract macro (pin locations and obstructions) |
| `<name>.lib` | Liberty timing/power model |
| `<name>.v` | Full behavioural Verilog model |
| `<name>.bb.v` | Verilog black-box (port list only, no body) |
| `cacti.cfg` | Cacti input file used for this SRAM |
| `cacti.cfg.out` | Raw Cacti output |

---

## Parameter Reference Table

| Parameter | Scope | Type | Default | Valid values |
|-----------|-------|------|---------|--------------|
| `port_type` | SRAM | string | `"1rw"` | `"1rw"`, `"1r1w"` |
| `rdw_mode` | 1r1w only | string | `"R"` | `"R"` (read-first), `"W"` (write-first) |
| `out_reg` | SRAM | boolean | `true` | `true` (registered), `false` (combinational) |

---

## Mapping to Vortex `VX_dp_ram`

The Vortex GPU uses `VX_dp_ram` for dual-port storage (GPR files, caches,
tag arrays).  Here is how `VX_dp_ram` parameters map to bsg_fakeram config:

| `VX_dp_ram` parameter | bsg_fakeram config | Notes |
|---|---|---|
| `DATAW` | `width` | Data word width in bits |
| `SIZE` | `depth` | Number of words |
| `OUT_REG=1` | `"out_reg": true` (default) | Registered output; SRAM is the register |
| `OUT_REG=0` | `"out_reg": false` | Combinational output; no extra pipeline stage in wrapper |
| `RDW_MODE="R"` | `"rdw_mode": "R"` (default) | Read-first collision policy |
| `RDW_MODE="W"` | `"rdw_mode": "W"` | Write-first collision policy |
| `WRENW` | covered by `w_mask_in` | bsg_fakeram uses per-bit mask; group `DATAW/WRENW` bits per `wren` slice |
| Read enable (`read`) | `r_ce_in` | Active-high chip enable on read port |
| Write enable (`write`) | `w_ce_in` | Active-high chip enable on write port |
| `raddr` | `r_addr_in` | Read address |
| `waddr` | `w_addr_in` | Write address |
| `rdata` | `rd_out` | Read data output |
| `wdata` | `wd_in` | Write data input |

### Recommended configurations for common Vortex instances

**GPR file (concurrent read + write, write-first, registered output):**
```json
{
  "name":      "sram_gpr_1r1w",
  "width":     32,
  "depth":     32,
  "banks":     1,
  "port_type": "1r1w",
  "rdw_mode":  "W",
  "out_reg":   true
}
```

**Tag/data array (read-first, combinational output for zero-latency wrapper):**
```json
{
  "name":      "sram_tag_1r1w",
  "width":     128,
  "depth":     128,
  "banks":     1,
  "port_type": "1r1w",
  "rdw_mode":  "R",
  "out_reg":   false
}
```

### Limitation: `sram_dp_to_1rw` adapter

The adapters in `sram_dp_to_1rw.sv` multiplex a single 1rw port and
**cannot perform concurrent read + write in one cycle**.  When both ports
are active, write wins and the read is silently dropped.  Replace those
adapters with a direct 1r1w fakeram instance to remove this restriction.

---

## Known Limitations

1. **Liberty for `out_reg: false`** — The combinational timing arc uses the
   same numerical values as the registered version (Cacti's `access_time_ns`
   treated as propagation delay).  This is a reasonable approximation but
   may not match a real async-read compiler's characterisation.

2. **`rdw_mode` is not reflected in Liberty** — The Liberty model is
   identical for `"R"` and `"W"`.  STA cannot distinguish the two policies;
   behaviour differs only in simulation.

3. **Single clock domain** — All generated macros have one shared `clk`.
   Dual-clock SRAMs (read and write on different clocks) are not supported.

4. **Cacti approximation** — Area, timing, and power numbers come from Cacti,
   not a foundry memory compiler.  Treat them as order-of-magnitude estimates
   for early design-space exploration, not sign-off values.

5. **Write-first forwarding in the Verilog model** — The forwarding path for
   `rdw_mode: "W"` is implemented with an `if/else` inside the clocked
   `always` block, which correctly models the intent in RTL simulation.
   In a real SRAM macro the same behaviour would require a dedicated
   forwarding mux outside the bitcell array; the fakeram model does not
   explicitly represent this extra logic or its area/timing cost.
