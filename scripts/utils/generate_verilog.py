import os
import math

################################################################################
# GENERATE VERILOG VIEW
#
# Generate a .v file based on the given SRAM.
# Supports two port types:
#   1rw  - one combined read/write port
#   1r1w - one exclusive read port + one exclusive write port
#
# For 1r1w, two additional options are honoured:
#   rdw_mode  'R' (read-first)  : on a same-cycle address collision rd_out
#             'W' (write-first) : returns the value being written this cycle
#   out_reg   True  : rd_out is registered (clocked, 1-cycle latency)
#             False : rd_out is combinational (transparent to array state)
################################################################################

# Template line for a 'setuphold' time check
SH_LINE = '      $setuphold (posedge clk, {sig}, 0, 0, notifier);\n'


# ---------------------------------------------------------------------------
# Verilog module builder helpers
# ---------------------------------------------------------------------------

def _build_1rw_verilog(name, data_width, depth, addr_width, crpt_on_x,
                       out_reg, setuphold_checks):
    """Return a string containing a complete 1rw behavioral Verilog module."""
    rd_decl = 'output reg [BITS-1:0]' if out_reg else 'output     [BITS-1:0]'

    s  = f'module {name}\n'
    s += '(\n'
    s += '   rd_out,\n'
    s += '   addr_in,\n'
    s += '   we_in,\n'
    s += '   wd_in,\n'
    s += '   w_mask_in,\n'
    s += '   clk,\n'
    s += '   ce_in\n'
    s += ');\n'
    s += f'   parameter BITS = {data_width};\n'
    s += f'   parameter WORD_DEPTH = {depth};\n'
    s += f'   parameter ADDR_WIDTH = {addr_width};\n'
    s += f'   parameter corrupt_mem_on_X_p = {crpt_on_x};\n'
    s += '\n'
    s += f'   {rd_decl}    rd_out;\n'
    s += '   input  [ADDR_WIDTH-1:0]  addr_in;\n'
    s += '   input                    we_in;\n'
    s += '   input  [BITS-1:0]        wd_in;\n'
    s += '   input  [BITS-1:0]        w_mask_in;\n'
    s += '   input                    clk;\n'
    s += '   input                    ce_in;\n'
    s += '\n'
    s += '   reg    [BITS-1:0]        mem [0:WORD_DEPTH-1];\n'
    s += '\n'
    s += '   integer j;\n'
    s += '\n'

    if out_reg:
        # Registered output: single always block handles both read and write
        s += '   always @(posedge clk)\n'
        s += '   begin\n'
        s += '      if (ce_in)\n'
        s += '      begin\n'
        s += '         if (corrupt_mem_on_X_p &&\n'
        s += '             ((^we_in === 1\'bx) || (^addr_in === 1\'bx))\n'
        s += '            )\n'
        s += '         begin\n'
        s += '            // WEN or ADDR is unknown: corrupt entire array\n'
        s += '            for (j = 0; j < WORD_DEPTH; j = j + 1)\n'
        s += '               mem[j] <= \'x;\n'
        s += f'            $display("warning: ce_in=1, we_in is %b, addr_in = %x in {name}", we_in, addr_in);\n'
        s += '         end\n'
        s += '         else if (we_in)\n'
        s += '         begin\n'
        s += '            mem[addr_in] <= (wd_in & w_mask_in) | (mem[addr_in] & ~w_mask_in);\n'
        s += '         end\n'
        s += '         // Read: captures old value (read-first semantics via non-blocking assignment)\n'
        s += '         rd_out <= mem[addr_in];\n'
        s += '      end\n'
        s += '      else\n'
        s += '      begin\n'
        s += '         // Make sure read fails if ce_in is low\n'
        s += '         rd_out <= \'x;\n'
        s += '      end\n'
        s += '   end\n'
    else:
        # Combinational output: clocked write, combinational read
        s += '   // Clocked write port\n'
        s += '   always @(posedge clk)\n'
        s += '   begin\n'
        s += '      if (ce_in)\n'
        s += '      begin\n'
        s += '         if (corrupt_mem_on_X_p &&\n'
        s += '             ((^we_in === 1\'bx) || (^addr_in === 1\'bx))\n'
        s += '            )\n'
        s += '         begin\n'
        s += '            for (j = 0; j < WORD_DEPTH; j = j + 1)\n'
        s += '               mem[j] <= \'x;\n'
        s += f'            $display("warning: ce_in=1, we_in is %b, addr_in = %x in {name}", we_in, addr_in);\n'
        s += '         end\n'
        s += '         else if (we_in)\n'
        s += '         begin\n'
        s += '            mem[addr_in] <= (wd_in & w_mask_in) | (mem[addr_in] & ~w_mask_in);\n'
        s += '         end\n'
        s += '      end\n'
        s += '   end\n'
        s += '\n'
        s += '   // Combinational read port (read-first: reflects array state before write commits)\n'
        s += '   assign rd_out = ce_in ? mem[addr_in] : \'x;\n'
        s += '\n'

    s += '   // Timing check placeholders (will be replaced during SDF back-annotation)\n'
    s += '   reg notifier;\n'
    s += '   specify\n'
    if out_reg:
        s += '      // Clock-to-Q delay\n'
        s += '      (posedge clk *> rd_out) = (0, 0);\n'
    else:
        s += '      // Combinational propagation: address to read output\n'
        s += '      (addr_in *> rd_out) = (0, 0);\n'
    s += '\n'
    s += '      // Timing checks\n'
    s += '      $width     (posedge clk,               0, 0, notifier);\n'
    s += '      $width     (negedge clk,               0, 0, notifier);\n'
    s += '      $period    (posedge clk,               0,    notifier);\n'
    s += setuphold_checks
    s += '   endspecify\n'
    s += '\n'
    s += 'endmodule\n'
    return s


def _build_1r1w_verilog(name, data_width, depth, addr_width, crpt_on_x,
                        rdw_mode, out_reg, setuphold_checks):
    """Return a string containing a complete 1r1w behavioral Verilog module.

    rdw_mode : 'R' (read-first) or 'W' (write-first) — collision policy when
               r_addr_in == w_addr_in in the same cycle.
    out_reg  : True  → rd_out is registered (clocked flip-flop output)
               False → rd_out is combinational (transparent to array state)
    """
    rd_decl = 'output reg [BITS-1:0]' if out_reg else 'output     [BITS-1:0]'
    write_first = (rdw_mode == 'W')

    s  = f'module {name}\n'
    s += '(\n'
    s += '   rd_out,\n'
    s += '   r_addr_in,\n'
    s += '   r_ce_in,\n'
    s += '   w_addr_in,\n'
    s += '   w_ce_in,\n'
    s += '   wd_in,\n'
    s += '   w_mask_in,\n'
    s += '   clk\n'
    s += ');\n'
    s += f'   parameter BITS = {data_width};\n'
    s += f'   parameter WORD_DEPTH = {depth};\n'
    s += f'   parameter ADDR_WIDTH = {addr_width};\n'
    s += f'   parameter corrupt_mem_on_X_p = {crpt_on_x};\n'
    s += '\n'
    s += f'   {rd_decl}    rd_out;\n'
    s += '   input  [ADDR_WIDTH-1:0]  r_addr_in;\n'
    s += '   input                    r_ce_in;\n'
    s += '   input  [ADDR_WIDTH-1:0]  w_addr_in;\n'
    s += '   input                    w_ce_in;\n'
    s += '   input  [BITS-1:0]        wd_in;\n'
    s += '   input  [BITS-1:0]        w_mask_in;\n'
    s += '   input                    clk;\n'
    s += '\n'
    s += '   reg    [BITS-1:0]        mem [0:WORD_DEPTH-1];\n'
    s += '\n'
    s += '   integer j;\n'
    s += '\n'

    if out_reg:
        # Single clocked always block — both ports fire on posedge clk.
        # Non-blocking assignment RHS is evaluated with pre-clock array state,
        # so read-first is the natural semantic. Write-first requires explicit
        # forwarding of the incoming write data to the read output.
        s += '   always @(posedge clk)\n'
        s += '   begin\n'
        s += '\n'
        s += '      // Write port\n'
        s += '      if (w_ce_in)\n'
        s += '      begin\n'
        s += '         if (corrupt_mem_on_X_p &&\n'
        s += '             ((^w_ce_in === 1\'bx) || (^w_addr_in === 1\'bx))\n'
        s += '            )\n'
        s += '         begin\n'
        s += '            for (j = 0; j < WORD_DEPTH; j = j + 1)\n'
        s += '               mem[j] <= \'x;\n'
        s += f'            $display("warning: w_ce_in or w_addr_in is unknown in {name}");\n'
        s += '         end\n'
        s += '         else\n'
        s += '         begin\n'
        s += '            mem[w_addr_in] <= (wd_in & w_mask_in) | (mem[w_addr_in] & ~w_mask_in);\n'
        s += '         end\n'
        s += '      end\n'
        s += '\n'

        if write_first:
            s += '      // Read port - WRITE-FIRST: when r_addr_in == w_addr_in, rd_out receives\n'
            s += '      // the value being written this cycle (forwarded before array is updated).\n'
        else:
            s += '      // Read port - READ-FIRST: rd_out always reflects the array state at the\n'
            s += '      // start of the cycle, even when r_addr_in == w_addr_in.\n'

        s += '      if (r_ce_in)\n'
        s += '      begin\n'
        s += '         if (corrupt_mem_on_X_p && (^r_addr_in === 1\'bx))\n'
        s += '         begin\n'
        s += '            rd_out <= \'x;\n'
        s += f'            $display("warning: r_addr_in is unknown in {name}");\n'
        s += '         end\n'

        if write_first:
            s += '         else if (w_ce_in && (r_addr_in == w_addr_in))\n'
            s += '         begin\n'
            s += '            // Forward write data: apply mask against current array value\n'
            s += '            rd_out <= (wd_in & w_mask_in) | (mem[r_addr_in] & ~w_mask_in);\n'
            s += '         end\n'

        s += '         else\n'
        s += '         begin\n'
        s += '            rd_out <= mem[r_addr_in];\n'
        s += '         end\n'
        s += '      end\n'
        s += '      else\n'
        s += '      begin\n'
        s += '         rd_out <= \'x;\n'
        s += '      end\n'
        s += '\n'
        s += '   end\n'

    else:
        # out_reg=False: clocked write, combinational read.
        # Write-first is implemented by combinationally forwarding current
        # write-port inputs before they are committed to the array.
        s += '   // Clocked write port\n'
        s += '   always @(posedge clk)\n'
        s += '   begin\n'
        s += '      if (w_ce_in)\n'
        s += '      begin\n'
        s += '         if (corrupt_mem_on_X_p &&\n'
        s += '             ((^w_ce_in === 1\'bx) || (^w_addr_in === 1\'bx))\n'
        s += '            )\n'
        s += '         begin\n'
        s += '            for (j = 0; j < WORD_DEPTH; j = j + 1)\n'
        s += '               mem[j] <= \'x;\n'
        s += f'            $display("warning: w_ce_in or w_addr_in is unknown in {name}");\n'
        s += '         end\n'
        s += '         else\n'
        s += '         begin\n'
        s += '            mem[w_addr_in] <= (wd_in & w_mask_in) | (mem[w_addr_in] & ~w_mask_in);\n'
        s += '         end\n'
        s += '      end\n'
        s += '   end\n'
        s += '\n'

        if write_first:
            s += '   // Combinational read port - WRITE-FIRST: forward active write data when\n'
            s += '   // r_addr_in == w_addr_in so the read sees the new value immediately.\n'
            s += '   wire [BITS-1:0] _rd_raw;\n'
            s += '   assign _rd_raw = mem[r_addr_in];\n'
            s += '   wire [BITS-1:0] _rd_fwd;\n'
            s += '   assign _rd_fwd = (w_ce_in && (r_addr_in == w_addr_in)) ?\n'
            s += '                    ((wd_in & w_mask_in) | (_rd_raw & ~w_mask_in)) : _rd_raw;\n'
            s += '   assign rd_out = r_ce_in ? _rd_fwd : \'x;\n'
        else:
            s += '   // Combinational read port - READ-FIRST: reflects committed array state;\n'
            s += '   // a same-cycle write to the same address is NOT visible on rd_out.\n'
            s += '   assign rd_out = r_ce_in ? mem[r_addr_in] : \'x;\n'
        s += '\n'

    s += '   // Timing check placeholders (will be replaced during SDF back-annotation)\n'
    s += '   reg notifier;\n'
    s += '   specify\n'
    if out_reg:
        s += '      // Clock-to-Q delay\n'
        s += '      (posedge clk *> rd_out) = (0, 0);\n'
    else:
        s += '      // Combinational propagation: read address to read output\n'
        s += '      (r_addr_in *> rd_out) = (0, 0);\n'
    s += '\n'
    s += '      // Timing checks\n'
    s += '      $width     (posedge clk,               0, 0, notifier);\n'
    s += '      $width     (negedge clk,               0, 0, notifier);\n'
    s += '      $period    (posedge clk,               0,    notifier);\n'
    s += setuphold_checks
    s += '   endspecify\n'
    s += '\n'
    s += 'endmodule\n'
    return s


def _build_1rw_bb(name, data_width, depth, addr_width, crpt_on_x):
    """Return a 1rw black-box Verilog module string."""
    s  = f'module {name}\n'
    s += '(\n'
    s += '   rd_out,\n'
    s += '   addr_in,\n'
    s += '   we_in,\n'
    s += '   wd_in,\n'
    s += '   w_mask_in,\n'
    s += '   clk,\n'
    s += '   ce_in\n'
    s += ');\n'
    s += f'   parameter BITS = {data_width};\n'
    s += f'   parameter WORD_DEPTH = {depth};\n'
    s += f'   parameter ADDR_WIDTH = {addr_width};\n'
    s += f'   parameter corrupt_mem_on_X_p = {crpt_on_x};\n'
    s += '\n'
    s += '   output [BITS-1:0]        rd_out;\n'
    s += '   input  [ADDR_WIDTH-1:0]  addr_in;\n'
    s += '   input                    we_in;\n'
    s += '   input  [BITS-1:0]        wd_in;\n'
    s += '   input  [BITS-1:0]        w_mask_in;\n'
    s += '   input                    clk;\n'
    s += '   input                    ce_in;\n'
    s += '\n'
    s += 'endmodule\n'
    return s


def _build_1r1w_bb(name, data_width, depth, addr_width, crpt_on_x):
    """Return a 1r1w black-box Verilog module string."""
    s  = f'module {name}\n'
    s += '(\n'
    s += '   rd_out,\n'
    s += '   r_addr_in,\n'
    s += '   r_ce_in,\n'
    s += '   w_addr_in,\n'
    s += '   w_ce_in,\n'
    s += '   wd_in,\n'
    s += '   w_mask_in,\n'
    s += '   clk\n'
    s += ');\n'
    s += f'   parameter BITS = {data_width};\n'
    s += f'   parameter WORD_DEPTH = {depth};\n'
    s += f'   parameter ADDR_WIDTH = {addr_width};\n'
    s += f'   parameter corrupt_mem_on_X_p = {crpt_on_x};\n'
    s += '\n'
    s += '   output [BITS-1:0]        rd_out;\n'
    s += '   input  [ADDR_WIDTH-1:0]  r_addr_in;\n'
    s += '   input                    r_ce_in;\n'
    s += '   input  [ADDR_WIDTH-1:0]  w_addr_in;\n'
    s += '   input                    w_ce_in;\n'
    s += '   input  [BITS-1:0]        wd_in;\n'
    s += '   input  [BITS-1:0]        w_mask_in;\n'
    s += '   input                    clk;\n'
    s += '\n'
    s += 'endmodule\n'
    return s


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_verilog(mem, tmChkExpand=False):
    """Generate a behavioral Verilog view for the RAM."""
    name       = str(mem.name)
    depth      = int(mem.depth)
    bits       = int(mem.width_in_bits)
    addr_width = math.ceil(math.log2(depth))
    crpt_on_x  = 1
    out_reg    = mem.out_reg
    rdw_mode   = mem.rdw_mode

    fout = os.sep.join([mem.results_dir, name + '.v'])

    if mem.port_type == '1r1w':
        if tmChkExpand:
            setuphold_checks  = ''
            for i in range(addr_width): setuphold_checks += SH_LINE.format(sig=f'r_addr_in[{i}]')
            for i in range(addr_width): setuphold_checks += SH_LINE.format(sig=f'w_addr_in[{i}]')
            for i in range(      bits): setuphold_checks += SH_LINE.format(sig=f'    wd_in[{i}]')
            for i in range(      bits): setuphold_checks += SH_LINE.format(sig=f'w_mask_in[{i}]')
        else:
            setuphold_checks  = SH_LINE.format(sig='   r_ce_in')
            setuphold_checks += SH_LINE.format(sig='   w_ce_in')
            setuphold_checks += SH_LINE.format(sig=' r_addr_in')
            setuphold_checks += SH_LINE.format(sig=' w_addr_in')
            setuphold_checks += SH_LINE.format(sig='     wd_in')
            setuphold_checks += SH_LINE.format(sig=' w_mask_in')
        body = _build_1r1w_verilog(name, bits, depth, addr_width, crpt_on_x,
                                   rdw_mode, out_reg, setuphold_checks)
    else:
        setuphold_checks  = SH_LINE.format(sig='       we_in')
        setuphold_checks += SH_LINE.format(sig='       ce_in')
        if tmChkExpand:
            for i in range(addr_width): setuphold_checks += SH_LINE.format(sig=f'  addr_in[{i}]')
            for i in range(      bits): setuphold_checks += SH_LINE.format(sig=f'    wd_in[{i}]')
            for i in range(      bits): setuphold_checks += SH_LINE.format(sig=f'w_mask_in[{i}]')
        else:
            setuphold_checks += SH_LINE.format(sig='     addr_in')
            setuphold_checks += SH_LINE.format(sig='       wd_in')
            setuphold_checks += SH_LINE.format(sig='   w_mask_in')
        body = _build_1rw_verilog(name, bits, depth, addr_width, crpt_on_x,
                                  out_reg, setuphold_checks)

    with open(fout, 'w') as f:
        f.write(body)


def generate_verilog_bb(mem):
    """Generate a Verilog black-box (interface-only) view for the RAM."""
    name       = str(mem.name)
    depth      = int(mem.depth)
    bits       = int(mem.width_in_bits)
    addr_width = math.ceil(math.log2(depth))
    crpt_on_x  = 1

    fout = os.sep.join([mem.results_dir, name + '.bb.v'])

    if mem.port_type == '1r1w':
        body = _build_1r1w_bb(name, bits, depth, addr_width, crpt_on_x)
    else:
        body = _build_1rw_bb(name, bits, depth, addr_width, crpt_on_x)

    with open(fout, 'w') as f:
        f.write(body)
